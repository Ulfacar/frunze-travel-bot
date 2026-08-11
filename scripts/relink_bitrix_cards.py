"""Перелинк старых диалогов на ту карточку Битрикса, которую менеджер реально открывает.

Замер 11.08: у диалогов, начатых до починки, `bitrix_lead_id` указывает либо на наш лид на
служебном аккаунте 155383 (его не видит ни один менеджер), либо на карточку мёртвой
интеграции i2crm 2024 года, висящую на уволенных сотрудниках. Переписка бота там есть — но
менеджер её не найдёт, потому что видит только свои лиды.

Скрипт находит для такого диалога карточку Открытой линии по телефону, перевешивает диалог
на неё и заливает туда всю переписку комментариями — ровно тем же способом, каким это делает
зеркало при первом касании.

Идемпотентен: после перелинка `bitrix_lead_id` указывает на правильную карточку, и повторный
прогон этот диалог уже не выберет. Поэтому дублей истории не будет.

По умолчанию НИЧЕГО не меняет — только печатает план. Запись включается флагом `--apply`.

    docker exec frunze-travel-app-1 python /tmp/relink.py --limit 3
    docker exec frunze-travel-app-1 python /tmp/relink.py --limit 3 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select, update  # noqa: E402

from app.integrations.crm.bitrix24 import Bitrix24Crm  # noqa: E402
from app.integrations.crm.bitrix_mirror import _is_openline, _pick_lead  # noqa: E402
from app.integrations.crm.db import Conversation, ConvMessage, get_sessionmaker  # noqa: E402

_LABEL = {"client": "Клиент", "bot": "Бот", "manager": "Менеджер"}
SERVICE_ACCOUNT = "155383"


async def _lead_info(adapter: Bitrix24Crm, lead_id: str) -> dict:
    resp = await adapter._call("crm.lead.list", {
        "filter": {"@ID": [str(lead_id)]},
        "select": ["ID", "SOURCE_ID", "ASSIGNED_BY_ID"]})
    rows = resp.get("result") or []
    return rows[0] if rows else {}


def _is_invisible(lead: dict) -> str:
    """Почему карточка не годится: '' — годится."""
    if not lead:
        return "карточка не найдена в портале"
    if str(lead.get("ASSIGNED_BY_ID") or "") == SERVICE_ACCOUNT:
        return f"наш лид на служебном {SERVICE_ACCOUNT}"
    source = str(lead.get("SOURCE_ID") or "")
    if "I2CRM" in source.upper():
        return f"архив i2crm ({source}), ответственный {lead.get('ASSIGNED_BY_ID')}"
    return ""


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    adapter = Bitrix24Crm()
    sm = get_sessionmaker()
    async with sm() as session:
        convs = (await session.execute(
            select(Conversation)
            .where(Conversation.bitrix_lead_id.is_not(None),
                   Conversation.bitrix_lead_id != "")
            .order_by(Conversation.last_message_at.desc()))).scalars().all()

    print(f"диалогов с привязанной карточкой: {len(convs)}")
    moved = checked = 0
    for conv in convs:
        if moved >= args.limit:
            break
        checked += 1
        current = await _lead_info(adapter, conv.bitrix_lead_id)
        reason = _is_invisible(current)
        if not reason:
            continue
        phone = (conv.phone or conv.user_id or "").split(":")[-1]
        candidates = await adapter.find_leads_by_phone(phone) if phone else []
        target = _pick_lead([c for c in candidates
                             if str(c.get("ID")) != str(conv.bitrix_lead_id)
                             and _is_openline(c)])
        if not target:
            print(f"  [{conv.user_id}] {conv.bitrix_lead_id}: {reason} → замены НЕТ, оставляем")
            continue

        async with sm() as session:
            messages = (await session.execute(
                select(ConvMessage).where(ConvMessage.conversation_id == conv.id)
                .order_by(ConvMessage.created_at))).scalars().all()
        lines = [f"[{_LABEL.get(m.sender, m.sender)}] {m.text}"
                 for m in messages if (m.text or "").strip()]
        print(f"  [{conv.user_id}] {conv.bitrix_lead_id} ({reason}) → {target}, "
              f"перенести реплик: {len(lines)}"
              f"{'' if args.apply else '  [ВХОЛОСТУЮ]'}")
        moved += 1
        if not args.apply:
            continue

        for line in lines:
            await adapter.add_note(str(target), line)
        async with sm() as session:
            await session.execute(update(Conversation)
                                  .where(Conversation.user_id == conv.user_id)
                                  .values(bitrix_lead_id=str(target)))
            await session.commit()

    print(f"\nпроверено карточек: {checked}, перелинковано: {moved}"
          f"{'' if args.apply else ' (вхолостую, ничего не изменено)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
