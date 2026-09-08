#!/usr/bin/env python
"""Срез туровой воронки в Битриксе — чем мерить «карточки не двигаются».

Зачем существует. Жалоба «карточки по турам не двигаются» приходила от заказчика не раз,
и каждый раз её разбирали руками, на ощупь. 07.09.2026 замер показал: 340 из 426 туровых
лидов за месяц стоят в «Новом лиде», при том что механизм бота исправен — просто он
двигал стадию только по полной квалификации, а её проходят 11% диалогов.

Скрипт отвечает на три вопроса, которые до него приходилось выяснять пятью запросами:
  1. как туровые карточки разложены по стадиям портала и кто их туда поставил;
  2. сколько карточек стоит в «Новом лиде», хотя переписка с клиентом идёт;
  3. сколько стадий бот двинул за период и застревает ли догоняющий проход.

Он же — инструмент замера ДО и ПОСЛЕ включения тумблера
`bitrix_stage_dialog_started_enabled`: снять срез, включить, снять снова.

ТОЛЬКО ЧТЕНИЕ. Ни одной записи в портал и в базу — запускать по проду безопасно:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml --env-file prod.env \
        exec -T app python scripts/tour_funnel_report.py --days 30
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

TOURS = ("frunze_tours", "frunze_tours_sezim")
# Люди в портале: без имён отчёт читается как набор идентификаторов.
PEOPLE = {"155313": "Адеми", "155267": "Айсина", "96451": "Медина",
          "110841": "Элиза", "155383": "служебный аккаунт", "1": "админ портала"}


def _fmt(name: str, value, width: int = 34) -> str:
    return f"  {name:<{width}} {value}"


async def _portal_slice(days: int) -> tuple[Counter, dict[str, Counter], dict[str, str]]:
    """Стадии туровых лидов в портале + кто менял карточку последним."""
    from app.integrations.crm.bitrix24 import Bitrix24Crm

    client = Bitrix24Crm()
    names: dict[str, str] = {}
    try:
        status = await client._call("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}})
        for item in (status.get("result") or []):
            names[str(item.get("STATUS_ID"))] = str(item.get("NAME") or "")
    except Exception as exc:  # noqa: BLE001 — отчёт полезен и без названий стадий
        print(f"  (названия стадий не прочитаны: {exc})")

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    stages: Counter = Counter()
    movers: dict[str, Counter] = {}
    start = 0
    while True:
        page = await client._call("crm.lead.list", {
            "filter": {">DATE_CREATE": since},
            "select": ["ID", "STATUS_ID", "ASSIGNED_BY_ID", "MODIFY_BY_ID"],
            "start": start,
        })
        items = page.get("result") or []
        for lead in items:
            owner = str(lead.get("ASSIGNED_BY_ID") or "?")
            # Туровые лиды отделяем по ответственному: визовые в этот отчёт не входят.
            if PEOPLE.get(owner) not in ("Адеми", "Айсина", "служебный аккаунт"):
                continue
            status_id = str(lead.get("STATUS_ID") or "?")
            stages[status_id] += 1
            movers.setdefault(status_id, Counter())[str(lead.get("MODIFY_BY_ID") or "?")] += 1
        nxt = page.get("next")
        if nxt is None or not items:
            break
        start = nxt
        if start > 5000:            # предохранитель: портал не листаем бесконечно
            break
    return stages, movers, names


async def _dialog_slice(days: int) -> dict:
    """Что о тех же карточках знает наша база: работа с клиентом и застрявшие в NEW."""
    from app.config import settings
    from app.integrations.crm.bitrix_pipeline import _catchup_stage, _stage_reached, _work_started
    from app.integrations.panel.store import get_conversation_store

    store = get_conversation_store()
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stage_map = settings.bitrix_stage_map or {}
    out = {"dialogs": 0, "with_lead": 0, "qualified": 0, "work_started": 0,
           "moved_by_bot": 0, "stuck_in_new": 0, "waiting": 0, "already_further": 0}
    for conv in await store.all_conversations_light():
        bot_id = (getattr(conv, "bot_id", "") or str(conv.user_id).partition(":")[0])
        if bot_id not in TOURS:
            continue
        last = getattr(conv, "last_message_at", None)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is not None and last < since:
            continue
        out["dialogs"] += 1
        if not (getattr(conv, "bitrix_lead_id", "") or ""):
            continue
        out["with_lead"] += 1
        by_bot = getattr(conv, "bitrix_stage_by_bot", "") or ""
        if by_bot:
            out["moved_by_bot"] += 1
        if _catchup_stage(conv) == "qualified":
            out["qualified"] += 1
        if _work_started(conv):
            out["work_started"] += 1
            if not by_bot:
                out["stuck_in_new"] += 1
        # Что увидел бы догоняющий проход при включённом тумблере.
        stage = _catchup_stage(conv, dialog_started=True)
        if stage:
            if _stage_reached(by_bot, stage_map.get(stage, "")):
                out["already_further"] += 1
            else:
                out["waiting"] += 1
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="Срез туровой воронки в Битриксе")
    parser.add_argument("--days", type=int, default=30, help="окно, дней (по умолчанию 30)")
    parser.add_argument("--no-portal", action="store_true",
                        help="не ходить в портал, показать только данные из базы")
    args = parser.parse_args()

    print(f"\n=== ТУРОВАЯ ВОРОНКА, окно {args.days} дн. "
          f"({datetime.now():%d.%m.%Y %H:%M}) ===\n")

    if not args.no_portal:
        stages, movers, names = await _portal_slice(args.days)
        total = sum(stages.values())
        print(f"КАРТОЧКИ В ПОРТАЛЕ: {total}")
        for status_id, count in stages.most_common():
            share = f"{count * 100 // total}%" if total else "-"
            title = names.get(status_id, status_id)
            who = ", ".join(f"{PEOPLE.get(uid, 'id ' + uid)}:{n}"
                            for uid, n in movers.get(status_id, Counter()).most_common(3))
            print(_fmt(f"{title} ({status_id})", f"{count:4}  {share:>4}   двигали: {who}", 38))
        print()

    data = await _dialog_slice(args.days)
    print("ЧТО ЗНАЕТ БОТ О ТЕХ ЖЕ ДИАЛОГАХ:")
    print(_fmt("туровых диалогов", data["dialogs"]))
    print(_fmt("карточка заведена", data["with_lead"]))
    print(_fmt("с клиентом начали работать", data["work_started"]))
    print(_fmt("квалифицированы (полные факты)", data["qualified"]))
    # Не «двигал бот»: в поле лежит и стадия, увиденная в портале (её мог поставить
    # человек). Реальные движения бота считает метрика `moved` контроллера.
    print(_fmt("стадия карточки известна", data["moved_by_bot"]))
    print()
    print("ГЛАВНОЕ ЧИСЛО — карточки, где работа идёт, а стадия не двинута:")
    print(_fmt("застряли в «Новом лиде»", data["stuck_in_new"]))
    print()
    print("ДОГОНЯЮЩИЙ ПРОХОД (что он увидит при включённом тумблере):")
    print(_fmt("ждут движения", data["waiting"]))
    print(_fmt("уже дальше цели (не берём в работу)", data["already_further"]))
    print()


if __name__ == "__main__":
    asyncio.run(main())
