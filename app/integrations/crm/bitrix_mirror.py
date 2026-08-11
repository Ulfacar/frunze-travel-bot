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
# Потолок на живой поиск карточки для пуша (см. resolve_lead_now).
RESOLVE_TIMEOUT_SECONDS = 8


def _lock_for(conv_key: str) -> asyncio.Lock:
    lock = _locks.get(conv_key)
    if lock is None:
        lock = _locks[conv_key] = asyncio.Lock()
    return lock


async def _enabled() -> bool:
    if not settings.bitrix24_webhook_url:
        return False
    return await flags.get_flag("bitrix_mirror_enabled", settings.bitrix_mirror_enabled)


async def _prefer_openline() -> bool:
    """Флаг из БД, а не из env.

    Тумблер «Бот пишет в карточку менеджера» стоит в панели и пишет в `app_flags`.
    Пока здесь читались только settings, он был декоративным: на проде флаг стоял `t`
    с 06.08, а переменной `BITRIX_PREFER_OPENLINE_LEAD` в prod.env нет — и все ссылки
    в уведомлениях продолжали вести в служебную карточку (замер 11.08: 17 из 21).
    Соседний `bitrix_mirror_enabled` всегда читался правильно — теперь читаются оба.
    """
    return await flags.get_flag("bitrix_prefer_openline_lead",
                                settings.bitrix_prefer_openline_lead)


def _assignee_for(conv, bot_id: str) -> str:
    """На кого вешать СВОЙ лид: владелец диалога точнее канала (на getvisa их двое)."""
    login = ((getattr(conv, "assigned_to", "") if conv else "") or "").strip().lower()
    by_manager = settings.bitrix_assignee_by_manager or {}
    return by_manager.get(login, "") or settings.bitrix_assignee_by_bot.get(bot_id, "")


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

    Среди линий берём САМУЮ СВЕЖУЮ (наибольший ID). Причина из данных 11.08: признак
    «есть `|` в SOURCE_ID» ловит не только Wappi, но и мёртвую интеграцию i2crm
    (`5|I2CRM`), чьи карточки 2024 года висят на уволенных — 106217 у 83049, 114005 и
    124241 у 27691. У троих клиентов такая карточка соседствует со свежей карточкой
    Wappi, и по порядку списка (findbycomm отдаёт по возрастанию ID) мы бы уверенно
    выбрали архив двухлетней давности. Возраст здесь и есть различитель.
    """
    openline = [str(l.get("ID") or "") for l in leads if _is_openline(l)]
    if openline:
        return max(openline, key=lambda i: int(i) if i.isdigit() else 0)
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

        if not await _prefer_openline():
            # Прежнее поведение: первый попавшийся лид по телефону, иначе создаём свой.
            # Ответственного проставляем и здесь: на служебный аккаунт лид не уходит ни
            # в одной из веток, иначе откат тумблера вернул бы 604 невидимые карточки.
            if phone:
                lead_id = await adapter.find_lead_id_by_phone(phone)
            if not lead_id:
                lead_id = await adapter.create_lead(
                    {"user_id": phone, "phone": phone, "name": name}, funnel or "",
                    (getattr(conv, "qualification", None) if conv else None) or {},
                    assigned_by_id=_assignee_for(conv, bot_id))
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
            assigned_by_id=_assignee_for(conv, bot_id))
        _pending.pop(conv_key, None)
        if lead_id:
            await store.update_meta(conv_key, bitrix_lead_id=str(lead_id))
        return lead_id, True


async def resolve_lead_now(phone: str) -> str:
    """Найти карточку клиента в портале ПРЯМО СЕЙЧАС. Ничего не создаёт, "" при неудаче.

    Нужна мгновенному пушу: зеркало работает по сообщениям и рано или поздно карточку
    подхватит, а у пуша второго шанса нет — он уходит один раз. Замер 11.08: визовая
    заявка готова через 2–8 минут, и карточка Открытой линии к этому моменту уже есть
    (её ID даже МЕНЬШЕ нашего — Wappi заводит её первой, в ту же минуту).

    Создавать лид отсюда нельзя: окно `bitrix_openline_wait_seconds` стоит против
    дублей, и «поторопиться ради красивой ссылки» — ровно тот путь, которым мы уже
    один раз наплодили близнецов.

    Свой таймаут жёстче общего (у адаптера 20 с на вызов, а их здесь два): это
    последний шаг обработки входящего, и висеть на нём почти минуту нельзя.
    """
    phone = str(phone or "").strip()
    if not phone or not await _enabled():
        return ""

    async def _lookup() -> str:
        from app.integrations.crm.bitrix24 import Bitrix24Crm
        adapter = Bitrix24Crm()
        if not await _prefer_openline():
            return str(await adapter.find_lead_id_by_phone(phone) or "")
        return _pick_lead(await adapter.find_leads_by_phone(phone))

    try:
        return await asyncio.wait_for(_lookup(), timeout=RESOLVE_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 — ссылка не стоит потерянной заявки
        log.warning("bitrix resolve_lead_now failed", exc_info=True)
        return ""


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
