"""Разовый: снять свежие карточки со служебного аккаунта и отдать их живому менеджеру.

Из чего проблема. Наш бот заводил лиды под аккаунтом вебхука (155383). В Битриксе менеджер
видит только СВОИ лиды — значит вся переписка бота для него не существует. Там, где Wappi
завёл свою карточку Открытой линии, диалог перевешивается на неё (`relink_bitrix_cards.py`).
Но примерно у 60% диалогов такой карточки нет вовсе: клиент писал только боту. Переносить
некуда — зато можно отдать нашу же карточку тому, кто с клиентом работает.

Границы намеренно узкие (решение владельца 11.08):

* только ВИЗОВЫЕ: карта `BITRIX_ASSIGNEE_BY_MANAGER` знает точные ID людей (Медина 96451,
  Элиза 110841). Туровым Битрикс не нужен, а `BITRIX_ASSIGNEE_BY_BOT` для них указывает на
  профили линий, а не на людей — назначать на них живые карточки нельзя;
* только свежие (`--days`, по умолчанию 14): переназначить все 604 значит вывалить менеджеру
  сотни мёртвых карточек в статусе NEW и утопить в них живых клиентов;
* только там, где у диалога ЕСТЬ владелец в панели: иначе непонятно, кому отдавать.

По умолчанию ничего не меняет — печатает план. Запись включается флагом `--apply`.
Идемпотентен: после переназначения ответственный уже не 155383, и повтор такую карточку
не выберет.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.integrations.crm.bitrix24 import Bitrix24Crm  # noqa: E402
from app.integrations.crm.db import Conversation, get_sessionmaker  # noqa: E402

SERVICE_ACCOUNT = "155383"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    by_manager = {k.lower(): v for k, v in (settings.bitrix_assignee_by_manager or {}).items()}
    if not by_manager:
        print("BITRIX_ASSIGNEE_BY_MANAGER пуст — некому отдавать, выходим")
        return 2
    print(f"карта менеджеров: {by_manager}")

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    sm = get_sessionmaker()
    async with sm() as session:
        convs = (await session.execute(
            select(Conversation)
            .where(Conversation.bitrix_lead_id.is_not(None),
                   Conversation.bitrix_lead_id != "",
                   Conversation.assigned_to.is_not(None),
                   Conversation.assigned_to != "",
                   Conversation.last_message_at >= since)
            .order_by(Conversation.last_message_at.desc()))).scalars().all()

    targets = [(c, by_manager.get((c.assigned_to or "").strip().lower(), ""))
               for c in convs]
    targets = [(c, uid) for c, uid in targets if uid]
    print(f"диалогов за {args.days} дн. с владельцем из карты: {len(targets)}")
    if not targets:
        return 0

    adapter = Bitrix24Crm()
    ids = sorted({str(c.bitrix_lead_id) for c, _ in targets})
    leads: dict[str, dict] = {}
    for chunk in (ids[i:i + 50] for i in range(0, len(ids), 50)):
        resp = await adapter._call("crm.lead.list", {
            "filter": {"@ID": chunk},
            "select": ["ID", "SOURCE_ID", "ASSIGNED_BY_ID"]})
        for row in resp.get("result") or []:
            leads[str(row.get("ID"))] = row

    stats: Counter = Counter()
    changed = 0
    for conv, target_uid in targets:
        lead = leads.get(str(conv.bitrix_lead_id))
        if not lead:
            stats["карточка не найдена"] += 1
            continue
        if str(lead.get("ASSIGNED_BY_ID") or "") != SERVICE_ACCOUNT:
            stats["уже у живого менеджера"] += 1
            continue
        print(f"  {conv.user_id}: лид {conv.bitrix_lead_id} → {conv.assigned_to} "
              f"({target_uid}){'' if args.apply else '  [ВХОЛОСТУЮ]'}")
        stats["переназначено"] += 1
        changed += 1
        if args.apply:
            await adapter._call("crm.lead.update", {
                "id": str(conv.bitrix_lead_id),
                "fields": {"ASSIGNED_BY_ID": str(target_uid)}})

    print(f"\nитог: {dict(stats)}"
          f"{'' if args.apply else '  (вхолостую, ничего не изменено)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
