"""Best-effort зеркалирование диалога в Bitrix как ЛИД + комментарии таймлайна (ТЗ 02.07 п.3).

Отдельный сайд-канал, НЕ через get_crm()/crm_backend: на первое касание находим или создаём
ЛИД по телефону (не сделку — воронки Bitrix начинаются после оплаты), id кэшируем на карточке
диалога (`bitrix_lead_id`), дальше каждую реплику бота/клиента/менеджера льём комментарием.

Гейт: флаг `bitrix_mirror_enabled` (БД) + непустой `bitrix24_webhook_url`. Никогда не роняет
диалог и не задерживает ответ клиенту — вызывается через `fire()` фоновой задачей.

Антидубли: find-or-create лида идёт ПОД локом на диалог (single-flight) с double-check кэша —
иначе client-хук и bot-хук на быстрый детерминированный ответ создали бы ДВА лида (гонка).
"""
from __future__ import annotations

import asyncio
import logging
import time

from app.config import settings
from app.core import flags
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("crm.bitrix_mirror")

_LABEL = {"client": "Клиент", "bot": "Бот", "manager": "Менеджер"}

# Лок на диалог для single-flight создания лида + strong-ref фоновых задач (иначе GC съест).
_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()
# С какого момента ждём лид Открытой линии по диалогу (см. _ensure_lead).
_pending: dict[str, float] = {}


def _lock_for(conv_key: str) -> asyncio.Lock:
    lock = _locks.get(conv_key)
    if lock is None:
        lock = _locks[conv_key] = asyncio.Lock()
    return lock


async def _enabled() -> bool:
    if not settings.bitrix24_webhook_url:
        return False
    return await flags.get_flag("bitrix_mirror_enabled", settings.bitrix_mirror_enabled)


def _is_openline(lead: dict) -> bool:
    """Лид, созданный интеграцией Wappi через Открытую линию.

    Признак — `SOURCE_ID` вида «25|02A4708D-EC6C» (линия | профиль Wappi). У наших
    лидов там «CALL» (Битрикс ставит по умолчанию, мы источник не задаём).
    Проверено на живом портале 06.08.2026 по трём линиям: 23, 25, 27.
    """
    return "|" in str(lead.get("SOURCE_ID") or "")


def _pick_lead(leads: list[dict]) -> str:
    """Выбрать целевую карточку: лид Открытой линии приоритетнее любого другого.

    Именно его открывает менеджер — там очередь линии уже проставила ответственного.
    """
    for lead in leads:
        if _is_openline(lead):
            return str(lead.get("ID") or "")
    return str(leads[0].get("ID") or "") if leads else ""


async def _history_text(conv) -> list[str]:
    """Вся переписка диалога строками для выгрузки в только что найденный лид."""
    return [f"[{_LABEL.get(m.sender, m.sender)}] {m.text}"
            for m in (getattr(conv, "messages", None) or []) if (m.text or "").strip()]


async def _ensure_lead(store, adapter, conv_key: str, phone: str, name: str,
                       funnel: str | None, bot_id: str = "") -> tuple[str, bool]:
    """Найти/создать лид под локом на диалог (антидубли), с double-check кэша.

    Возвращает `(lead_id, is_fresh)` — `is_fresh=True`, когда карточка найдена/создана
    впервые: тогда в неё выгружается вся история, а не только текущая реплика.
    """
    async with _lock_for(conv_key):
        conv = await store.get(conv_key)
        lead_id = (getattr(conv, "bitrix_lead_id", "") if conv else "") or ""
        if lead_id:
            return lead_id, False                 # уже связан (в т.ч. параллельным хуком)

        if not settings.bitrix_prefer_openline_lead:
            # Прежнее поведение: первый попавшийся лид по телефону, иначе создаём свой.
            if phone:
                lead_id = await adapter.find_lead_id_by_phone(phone)
            if not lead_id:
                lead_id = await adapter.create_lead(
                    {"user_id": phone, "phone": phone, "name": name}, funnel or "",
                    (getattr(conv, "qualification", None) if conv else None) or {})
            if lead_id:
                await store.update_meta(conv_key, bitrix_lead_id=str(lead_id))
            return lead_id, False

        leads = await adapter.find_leads_by_phone(phone) if phone else []
        lead_id = _pick_lead(leads)
        if lead_id:
            await store.update_meta(conv_key, bitrix_lead_id=str(lead_id))
            return lead_id, True

        # Лида ещё нет. НЕ создаём свой сразу: из 12 наших лидов у 6 близнец от Wappi
        # появился в ту же минуту — поспешив, мы гарантированно плодим дубль. Ничего
        # не теряем: вся переписка лежит в панели и выгрузится, как только лид найдётся.
        started = _pending.setdefault(conv_key, time.monotonic())
        if time.monotonic() - started < settings.bitrix_openline_wait_seconds:
            return "", False

        lead_id = await adapter.create_lead(
            {"user_id": phone, "phone": phone, "name": name}, funnel or "",
            (getattr(conv, "qualification", None) if conv else None) or {},
            assigned_by_id=settings.bitrix_assignee_by_bot.get(bot_id, ""))
        _pending.pop(conv_key, None)
        if lead_id:
            await store.update_meta(conv_key, bitrix_lead_id=str(lead_id))
        return lead_id, True


async def mirror_message(conv_key: str, *, sender: str, text: str,
                         phone: str = "", name: str = "", funnel: str | None = None,
                         bot_id: str = "") -> None:
    """Зеркалить одну реплику в Bitrix-лид. Самозащитная: любые сбои гасит в лог.

    Пишем ТОЛЬКО комментарий в карточку. В чат Открытой линии писать нельзя: Битрикс
    перешлёт сообщение клиенту через коннектор, и человек получит одну и ту же реплику
    дважды — от бота и от Битрикса.
    """
    text = (text or "").strip()
    if not text or not await _enabled():
        return
    try:
        from app.integrations.crm.bitrix24 import Bitrix24Crm
        adapter = Bitrix24Crm()
        store = get_conversation_store()
        lead_id, is_fresh = await _ensure_lead(
            store, adapter, conv_key, phone, name, funnel, bot_id)
        if not lead_id:
            return                      # ждём лид Открытой линии — история не потеряна
        line = f"[{_LABEL.get(sender, sender)}] {text}"
        if is_fresh:
            # Карточка нашлась впервые: выгружаем всю переписку, включая то, что
            # накопилось за время ожидания. Иначе менеджер увидит диалог с середины.
            # Текущая реплика в панель уже записана (log_in идёт до fire), но если
            # истории нет — дописываем её вручную, чтобы сообщение не потерялось.
            lines = await _history_text(await store.get(conv_key))
            if not lines or lines[-1] != line:
                lines.append(line)
            for text_line in lines:
                await adapter.add_note(str(lead_id), text_line)
            return
        await adapter.add_note(str(lead_id), line)
    except Exception:  # noqa: BLE001 — зеркало не должно ломать диалог
        log.warning("bitrix mirror failed (key=%s sender=%s)", conv_key, sender, exc_info=True)


def fire(conv_key: str, **kwargs) -> None:
    """Запустить зеркалирование в фоне — не блокирует ответ клиенту, не роняет обработку."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # нет running loop (часть тестов) — тихо пропускаем
    task = loop.create_task(mirror_message(conv_key, **kwargs))
    _tasks.add(task)                        # strong-ref: иначе loop держит weakref и GC съест
    task.add_done_callback(_tasks.discard)
