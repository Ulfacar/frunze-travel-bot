"""Bitrix24Crm — интеграция через входящий вебхук портала (getvisakg.bitrix24.kz).

Бот создаёт ЛИД (не сделку!) на каждый диалог и льёт в него реплики комментариями.
Почему лид, а не сделка: воронки Bitrix у клиента начинаются ПОСЛЕ оплаты (стадия 1 =
«подписан договор / оплата получена»), поэтому неоплаченный поток идёт в Лиды, а менеджер
конвертит Лид → Сделку после оплаты (согласовано 06.07).

Методы Bitrix REST:
  crm.lead.add                 — создать лид (NAME/PHONE/COMMENTS/SOURCE_DESCRIPTION)
  crm.duplicate.findbycomm     — найти существующий лид по телефону (антидубли)
  crm.lead.update              — обновить статус лида (STATUS_ID)
  crm.timeline.comment.add     — комментарий в таймлайн лида (ENTITY_TYPE=lead)
  imbot.message.add            — сообщение в Открытые линии (если заведём линию Bitrix; пока не используется)

HTTP-клиент инъектируется (тесты) — иначе создаётся по `bitrix24_webhook_url`.
"""
from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("crm.bitrix24")

# Маркер собственного текста в COMMENTS лида. Без эмодзи и BBCode: портал молча
# обрезает поле на первом символе вне BMP, а неизвестные [tags] вырезает.
LEAD_COMMENTS_MARKER = "Досье бота:"

# Наш ключ анкеты → код турового поля лида в портале getvisakg (`crm.lead.fields`, 14.09).
# Константа, а не настройка: портал один, а словарь из env с пустым дефолтом в compose
# уронил бы разбор настроек при старте.
TOUR_LEAD_FIELDS = {
    "destination": "UF_CRM_1650440002892",   # «Какая страна ?»
    "dates": "UF_CRM_1650441175540",         # «Даты поездки ?»
    "tourists": "UF_CRM_1650441245612",      # «Количество туристов ( взрослые), (дети)»
}

_BBCODE_TAG_RE = re.compile(r"\[/?[a-z][a-z0-9]*(?:=[^\]\r\n]*)?\]", re.IGNORECASE)


def _bitrix_time(moment) -> str:
    """Время в формате, который понимает фильтр Битрикса (ISO без микросекунд)."""
    return moment.replace(microsecond=0).isoformat()


def sanitize_lead_comments(text: str) -> str:
    """Remove characters that the portal cannot store in lead COMMENTS."""
    return "".join(ch for ch in str(text) if ord(ch) < 0x10000)


def strip_lead_comments_bbcode(text: str) -> str:
    """Return the visible COMMENTS text after Bitrix BBCode decoration."""
    return _BBCODE_TAG_RE.sub("", str(text))


class Bitrix24Crm:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._base = settings.bitrix24_webhook_url.rstrip("/")
        self._client = client

    async def _call(self, method: str, payload: dict) -> dict:
        """Вызов REST-метода. Возвращает тело ответа (с ключом `result`)."""
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            resp = await client.post(f"{self._base}/{method}.json", json=payload)
            resp.raise_for_status()
            return resp.json()
        finally:
            if owns:
                await client.aclose()

    async def create_lead(self, contact: dict[str, Any], funnel: str, data: dict,
                          assigned_by_id: str = "") -> str:
        """Создать ЛИД (crm.lead.add). Возвращает ID лида (строкой).

        `assigned_by_id` обязателен по смыслу, хоть и не по сигнатуре: без него Битрикс
        вешает лид на владельца вебхука — служебный аккаунт, чьи карточки менеджер
        не видит. Именно так 604 лида с полной перепиской оказались невидимыми.
        """
        phone = str(contact.get("phone") or contact.get("user_id") or "")
        name = str(contact.get("name") or "").strip()
        fields: dict[str, Any] = {
            "TITLE": f"{funnel or 'lead'}: {name or phone or 'WhatsApp'}",
            "NAME": name,
            "COMMENTS": sanitize_lead_comments(
                LEAD_COMMENTS_MARKER + "\n" + _format_qualification(data)
            ) if data else "",
            "SOURCE_DESCRIPTION": f"WhatsApp бот ({funnel})" if funnel else "WhatsApp бот",
        }
        if assigned_by_id:
            fields["ASSIGNED_BY_ID"] = assigned_by_id
        if phone:
            fields["PHONE"] = [{"VALUE": phone, "VALUE_TYPE": "WORK"}]
        resp = await self._call("crm.lead.add", {"fields": fields})
        lead_id = str(resp.get("result", ""))
        logger.info("Bitrix create_lead lead=%s funnel=%s", lead_id, funnel)
        return lead_id

    async def find_lead_id_by_phone(self, phone: str) -> str:
        """Найти ID существующего лида по телефону (антидубли). "" если не найден."""
        phone = str(phone or "").strip()
        if not phone:
            return ""
        resp = await self._call(
            "crm.duplicate.findbycomm",
            {"type": "PHONE", "values": [phone], "entity_type": "LEAD"})
        leads = ((resp.get("result") or {}).get("LEAD")) or []
        return str(leads[0]) if leads else ""

    async def find_leads_by_phone(self, phone: str) -> list[dict[str, Any]]:
        """Все лиды с этим телефоном — с ID и SOURCE_ID, чтобы выбрать нужный.

        В отличие от `find_lead_id_by_phone` возвращает не первый попавшийся, а весь
        список: на одного клиента в портале живут и лид Открытой линии (его открывает
        менеджер), и наш. Поиск идёт через `crm.duplicate.findbycomm` — он нормализует
        номер, формат с `+` и без находится одинаково (проверено на живом портале).
        """
        phone = str(phone or "").strip()
        if not phone:
            return []
        resp = await self._call(
            "crm.duplicate.findbycomm",
            {"type": "PHONE", "values": [phone], "entity_type": "LEAD"})
        ids = ((resp.get("result") or {}).get("LEAD")) or []
        if not ids:
            return []
        detail = await self._call(
            "crm.lead.list",
            {"filter": {"@ID": [str(i) for i in ids]}, "select": ["ID", "SOURCE_ID"]})
        return list(detail.get("result") or [])

    async def list_converted_leads(self, since) -> list[dict[str, Any]]:
        """Лиды, отмеченные «Подписан» после `since`. Один список вместо тысячи запросов.

        Раньше обратное чтение опрашивало КАЖДУЮ нашу карточку через `crm.lead.get` и
        упиралось в потолок в 100 штук: при 1001 карточке в окне продажа на свежем лиде
        не находилась никогда (замер 18.08, лид 186245). Спрашивать надо портал о том,
        что изменилось, а не перебирать своё.

        Пагинация Битрикса — по 50 на страницу через `start`; идём, пока он отдаёт `next`.
        """
        collected: list[dict[str, Any]] = []
        start = 0
        while True:
            payload = {
                "filter": {"STATUS_ID": "CONVERTED", ">DATE_MODIFY": _bitrix_time(since)},
                # SOURCE_* нужны сделке: без них в карточке не видно, откуда пришёл
                # клиент. Просим их здесь, а не отдельным запросом на каждый лид.
                "select": ["ID", "TITLE", "ASSIGNED_BY_ID", "STATUS_ID",
                           "SOURCE_ID", "SOURCE_DESCRIPTION", "NAME"],
                "order": {"DATE_MODIFY": "DESC"},
                "start": start,
            }
            resp = await self._call("crm.lead.list", payload)
            collected.extend(resp.get("result") or [])
            nxt = resp.get("next")
            if not nxt or len(collected) >= 1000:   # предохранитель от бесконечной страницы
                return collected
            start = int(nxt)

    async def update_stage(self, deal_id: str, stage: str) -> None:
        """Обновить STATUS_ID лида (если стадия замаплена; иначе мягко пропустить)."""
        status_id = settings.bitrix_stage_map.get(stage)
        if not status_id:
            logger.warning("Bitrix update_stage: нет STATUS_ID для стадии '%s' — пропуск", stage)
            return
        await self._call("crm.lead.update", {"id": deal_id, "fields": {"STATUS_ID": status_id}})
        logger.info("Bitrix update_stage lead=%s -> %s (%s)", deal_id, stage, status_id)

    async def get_lead(self, lead_id: str) -> dict[str, Any]:
        """Прочитать поля лида, нужные конвейеру."""
        # Туровые поля портала читаем тем же запросом: писать в них можно только в пустое,
        # а узнать «пустое ли» без чтения нельзя.
        select = ["ID", "STATUS_ID", "COMMENTS", "ASSIGNED_BY_ID", "TITLE",
                  *TOUR_LEAD_FIELDS.values()]
        resp = await self._call("crm.lead.get", {"id": lead_id, "select": select})
        return dict(resp.get("result") or {})

    async def update_lead_fields(self, lead_id: str, fields: dict[str, str]) -> None:
        """Записать поля лида одним запросом (текст чистим так же, как COMMENTS)."""
        clean = {code: sanitize_lead_comments(value) for code, value in fields.items()}
        await self._call("crm.lead.update", {"id": lead_id, "fields": clean})

    async def update_stage_status(self, lead_id: str, status_id: str) -> None:
        """Поставить уже разрешённый STATUS_ID без повторного внутреннего маппинга."""
        await self._call("crm.lead.update", {"id": lead_id, "fields": {"STATUS_ID": status_id}})

    async def update_comments(self, lead_id: str, text: str) -> None:
        await self._call(
            "crm.lead.update",
            {"id": lead_id, "fields": {"COMMENTS": sanitize_lead_comments(text)}},
        )

    async def find_contact_id_by_phone(self, phone: str) -> str:
        """Контакт с этим телефоном, если он в портале уже есть. "" — если нет.

        Ищем тем же `crm.duplicate.findbycomm`, что и лиды: он нормализует номер, формат
        с `+` и без находится одинаково. Свой контакт заводить, когда чужой уже есть, —
        значит плодить дубли в CRM заказчика.
        """
        phone = str(phone or "").strip()
        if not phone:
            return ""
        resp = await self._call(
            "crm.duplicate.findbycomm",
            {"type": "PHONE", "values": [phone], "entity_type": "CONTACT"})
        ids = ((resp.get("result") or {}).get("CONTACT")) or []
        return str(ids[0]) if ids else ""

    async def create_contact(self, name: str, phone: str) -> str:
        """Завести контакт с именем и телефоном. Возвращает id."""
        resp = await self._call("crm.contact.add", {"fields": {
            "NAME": str(name or phone).strip(),
            "PHONE": [{"VALUE": str(phone).strip(), "VALUE_TYPE": "MOBILE"}],
            "OPENED": "Y",
        }})
        return str(resp.get("result") or "")

    async def find_deal_by_lead(self, lead_id: str) -> str:
        """ID сделки, заведённой из этого лида конвертацией в портале. "" — если нет."""
        resp = await self._call("crm.deal.list", {"filter": {"LEAD_ID": lead_id},
                                                  "select": ["ID"], "order": {"ID": "ASC"}})
        deals = resp.get("result") or []
        return str(deals[0].get("ID") or "") if deals else ""

    async def create_deal(self, fields: dict[str, Any]) -> str:
        resp = await self._call("crm.deal.add", {"fields": fields})
        return str(resp.get("result") or "")

    async def add_note(self, deal_id: str, text: str) -> None:
        """Комментарий в таймлайн ЛИДА."""
        entity_id: Any = int(deal_id) if str(deal_id).isdigit() else deal_id
        await self._call(
            "crm.timeline.comment.add",
            {"fields": {"ENTITY_ID": entity_id, "ENTITY_TYPE": "lead", "COMMENT": text}},
        )
        logger.info("Bitrix add_note lead=%s", deal_id)

    async def send_message(self, chat_id: str, text: str, bot_id: str | None = None) -> None:
        """Отправить сообщение клиенту в Открытую линию от имени чат-бота (если заведём линию)."""
        payload: dict[str, Any] = {"DIALOG_ID": chat_id, "MESSAGE": text}
        if bot_id:
            payload["BOT_ID"] = bot_id
        await self._call("imbot.message.add", payload)
        logger.info("Bitrix send_message dialog=%s bot=%s", chat_id, bot_id)


def _format_qualification(data: dict) -> str:
    """Свернуть собранные поля квалификации в текст комментария к лиду."""
    if not data:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in data.items())
