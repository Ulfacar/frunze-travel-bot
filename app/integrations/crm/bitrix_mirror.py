"""Best-effort зеркалирование диалога в Bitrix как ЛИД + комментарии таймлайна (ТЗ 02.07 п.3).

Отдельный сайд-канал, НЕ через get_crm()/crm_backend: на первое касание находим или создаём
ЛИД по телефону (не сделку — воронки Bitrix начинаются после оплаты), id кэшируем на карточке
диалога (`bitrix_lead_id`), дальше каждую реплику бота/клиента/менеджера льём комментарием.

Гейт: флаг `bitrix_mirror_enabled` (БД) + непустой `bitrix24_webhook_url`. Никогда не роняет
диалог и не задерживает ответ клиенту — вызывается через `fire()` фоновой задачей.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.core import flags
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("crm.bitrix_mirror")

_LABEL = {"client": "Клиент", "bot": "Бот", "manager": "Менеджер"}


async def _enabled() -> bool:
    if not settings.bitrix24_webhook_url:
        return False
    return await flags.get_flag("bitrix_mirror_enabled", settings.bitrix_mirror_enabled)


async def mirror_message(conv_key: str, *, sender: str, text: str,
                         phone: str = "", name: str = "", funnel: str | None = None) -> None:
    """Зеркалить одну реплику в Bitrix-лид. Самозащитная: любые сбои гасит в лог."""
    text = (text or "").strip()
    if not text or not await _enabled():
        return
    try:
        from app.integrations.crm.bitrix24 import Bitrix24Crm
        adapter = Bitrix24Crm()
        store = get_conversation_store()
        conv = await store.get(conv_key)
        lead_id = (getattr(conv, "bitrix_lead_id", "") if conv else "") or ""
        if not lead_id:
            if phone:
                lead_id = await adapter.find_lead_id_by_phone(phone)  # антидубли
            if not lead_id:
                qualification = (getattr(conv, "qualification", None) if conv else None) or {}
                lead_id = await adapter.create_lead(
                    {"user_id": phone, "phone": phone, "name": name}, funnel or "", qualification)
            if lead_id:
                await store.update_meta(conv_key, bitrix_lead_id=str(lead_id))
        if lead_id:
            await adapter.add_note(str(lead_id), f"[{_LABEL.get(sender, sender)}] {text}")
    except Exception:  # noqa: BLE001 — зеркало не должно ломать диалог
        log.warning("bitrix mirror failed (key=%s sender=%s)", conv_key, sender, exc_info=True)


def fire(conv_key: str, **kwargs) -> None:
    """Запустить зеркалирование в фоне — не блокирует ответ клиенту, не роняет обработку."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # нет running loop (часть тестов) — тихо пропускаем
    loop.create_task(mirror_message(conv_key, **kwargs))
