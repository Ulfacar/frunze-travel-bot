#!/usr/bin/env python3
"""Дозаполнить карточки по уже состоявшейся переписке.

Замер 13.09: из 739 перехваченных туровых диалогов анкета пуста у 591. Причина была в
том, что при перехвате бот переставал читать; она починена, но новые сообщения придут не
во все эти диалоги — часть клиентов уже замолчала. Этот скрипт перечитывает историю и
дописывает то, что клиент говорил прямым текстом.

ПРАВИЛА, каждое проверяемо кодом:

1. По умолчанию — СУХОЙ режим: печатает таблицу и не пишет ни байта.
2. Разбираем только реплики клиента (`sender='client'`). Менеджер присылает прайсы, и
   его «Анталья 1200$» уехала бы в бюджет клиента.
3. Дописываем только ПУСТЫЕ поля (`facts.fill_gaps`): в карточке может стоять рука
   менеджера, и спорить с ней нельзя.
4. Бюджет подчиняется тому же тумблеру, что и живой путь (`facts.allowed`): по умолчанию
   в карточку он не идёт.
5. Только туры. Визы и билеты не трогаем.
6. `--write-panel` пишет в нашу базу. Досье в Битрикс доносит штатный конвейер
   (`bitrix_pipeline`), своей записи в портал у скрипта нет.

Запуск:
    docker exec -w /app frunze-travel-app-1 python scripts/facts_backfill.py --limit 50
    docker exec -w /app frunze-travel-app-1 python scripts/facts_backfill.py --write-panel
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import facts  # noqa: E402

MIN_CLIENT_MESSAGES = 3


async def _candidates(limit: int, bot_prefix: str, days: int) -> list[dict]:
    """Туровые диалоги с разговором и неполной анкетой, новые сверху."""
    from sqlalchemy import text as sql

    from app.integrations.crm.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        rows = (await session.execute(sql(
            "select c.id, c.user_id, c.qualification, c.bitrix_lead_id,"
            "       coalesce(c.assigned_to,'') as owner,"
            "       (select count(*) from messages m where m.conversation_id = c.id"
            "          and m.sender = 'client') as msgs"
            "  from conversations c"
            " where c.funnel = 'tours'"
            "   and c.bot_id like :prefix"
            "   and c.archived is not true"
            "   and c.created_at >= now() - (:days || ' days')::interval"
            " order by c.last_message_at desc nulls last"
        ), {"prefix": f"{bot_prefix}%", "days": str(days)})).mappings().all()

    # Общие карточки Открытой линии: на одном лиде сидят разные клиенты. Сухой прогон
    # 13.09 показал такой диалог на 194 реплики, куда стеклись факты нескольких человек —
    # даты из пересланного прайса, состав из чужого номера телефона. Дозаполнять такое
    # нельзя: мы впишем одному клиенту чужую поездку.
    shared = await _shared_leads()

    out = []
    for row in rows:
        if int(row["msgs"] or 0) < MIN_CLIENT_MESSAGES:
            continue
        if str(row["bitrix_lead_id"] or "") in shared:
            continue
        out.append(dict(row))
        if len(out) >= limit:
            break
    return out


async def _shared_leads() -> set[str]:
    """Карточки, на которых больше одного телефона."""
    from sqlalchemy import text as sql

    from app.integrations.crm.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        rows = (await session.execute(sql(
            "select bitrix_lead_id from conversations"
            " where coalesce(bitrix_lead_id,'') <> ''"
            " group by bitrix_lead_id"
            " having count(distinct split_part(user_id, ':', 2)) > 1"))).scalars().all()
    return {str(r) for r in rows}


async def _client_messages(conv_id: int) -> list[str]:
    from sqlalchemy import text as sql

    from app.integrations.crm.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        rows = (await session.execute(sql(
            "select text from messages where conversation_id = :i and sender = 'client'"
            " order by created_at"), {"i": conv_id})).scalars().all()
    return [t for t in rows if (t or "").strip()]


async def _replay(conv: dict, bot_id: str) -> tuple[dict, dict[str, str]]:
    """(что дописали, откуда взяли). Порядок хронологический — как в живом разговоре."""
    known = dict(conv.get("qualification") or {})
    before = dict(known)
    sources: dict[str, str] = {}
    for message in await _client_messages(conv["id"]):
        found = await facts.allowed(facts.extract(message), bot_id=bot_id)
        if not found:
            continue
        filled = facts.fill_gaps(known, found)
        for key, value in filled.items():
            if before.get(key) in (None, "", [], {}) and key not in sources and value:
                sources[key] = message.replace("\n", " ")[:70]
        known = filled
    added = {k: v for k, v in known.items() if before.get(k) in (None, "", [], {})}
    # Курорт и страна обязаны сходиться. Клиент передумал по ходу разговора, а поля
    # брались из разных сообщений: сухой прогон дал «направление Египет, курорт Дубай».
    # Курорт снимаем — он уточнение, а страна важнее.
    resort = added.get("region") or known.get("region")
    country = added.get("destination") or known.get("destination")
    if resort and country and facts.resort_country(resort) not in ("", country):
        added.pop("region", None)
        sources.pop("region", None)
    return added, sources


async def main(limit: int, bot_prefix: str, days: int, write: bool) -> int:
    convs = await _candidates(limit, bot_prefix, days)
    print(f"=== туровых диалогов в разборе: {len(convs)}  (канал {bot_prefix}*, {days} дней)")
    print(f"=== режим: {'ЗАПИСЬ В ПАНЕЛЬ' if write else 'сухой прогон, ничего не пишем'}\n")

    touched = fields_total = 0
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()

    for conv in convs:
        bot_id = str(conv["user_id"]).split(":", 1)[0]
        added, sources = await _replay(conv, bot_id)
        if not added:
            continue
        touched += 1
        fields_total += len(added)
        head = f"{str(conv['user_id'])[-4:]}  лид {conv['bitrix_lead_id'] or '—'}"
        print(f"--- ...{head}  ({conv['msgs']} реплик, менеджер {conv['owner'] or '—'})")
        for key, value in added.items():
            print(f"      {key:16} = {str(value)[:34]:36} ← {sources.get(key, '')}")
        if write:
            merged = facts.fill_gaps(conv.get("qualification") or {}, added)
            await store.update_meta(conv["user_id"], qualification=merged)
        print()

    print(f"=== диалогов дозаполнено: {touched} из {len(convs)}")
    print(f"=== полей дописано:       {fields_total}")
    if not write:
        print("\nСухой прогон. Каждая строка «поле = значение ← реплика» должна быть правдой.")
        print("Если всё верно — тот же запуск с `--write-panel`.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--bot", default="frunze_tours")
    ap.add_argument("--days", type=int, default=75)
    ap.add_argument("--write-panel", action="store_true",
                    help="записать дописанное в нашу базу (в портал не пишем)")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.limit, args.bot, args.days, args.write_panel)))
