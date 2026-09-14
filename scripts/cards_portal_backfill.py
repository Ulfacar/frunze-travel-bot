#!/usr/bin/env python3
"""Донести в карточки Битрикса то, что бот уже знает о клиенте.

Замер 14.09: у 28 из 52 туровых клиентов, чьё направление бот знал, в карточке его не
было, а поля «Какая страна ?», «Даты поездки ?», «Количество туристов» пусты во всех 165
свежих карточках. Живой путь это чинит для новых сообщений; этот скрипт — для истории.

ПРАВИЛА:
1. По умолчанию СУХОЙ режим: читает портал, печатает числа, не пишет ни байта.
2. Пишет штатной `bitrix_pipeline.sync_dossier` — те же защиты, что в живом пути: только
   туры, только пустые поля, ручной текст менеджера не трогаем, закрытые карточки и общие
   карточки Открытой линии пропускаем.
3. `--apply` работает, только если на проде включены `dossier_refresh_enabled` и
   `bitrix_lead_fields_enabled`: скрипт не обходит тумблеры.

Запуск:
    docker exec -w /app frunze-travel-app-1 python scripts/cards_portal_backfill.py
    docker exec -w /app frunze-travel-app-1 python scripts/cards_portal_backfill.py --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def main(days: int, apply: bool, pause: float) -> int:
    from app.core.sale_check import _shared_leads
    from app.integrations.crm import bitrix_pipeline as bp
    from app.integrations.panel.store import get_conversation_store

    if apply and not (await bp._dossier_refresh_enabled() and await bp._lead_fields_enabled()):
        print("СТОП: включите dossier_refresh_enabled и bitrix_lead_fields_enabled в админке")
        return 2

    convs = await get_conversation_store().all_conversations_light()
    shared = _shared_leads(convs)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    candidates = [c for c in convs
                  if bp._is_tour(c) and (c.bitrix_lead_id or "")
                  and c.bitrix_lead_id not in shared
                  and _aware(c.last_message_at) and _aware(c.last_message_at) >= since
                  and bp.lead_field_values(c.qualification or {})]
    client = bp._adapter()
    stats = {"кандидатов": len(candidates), "закрыта": 0, "полей_пустых": 0,
             "карточек_с_пустыми_полями": 0, "досье_без_фактов": 0,
             "досье_чужое": 0, "записано": 0, "ошибок": 0}
    codes = bp.TOUR_LEAD_FIELDS
    for conv in candidates:
        try:
            lead = await client.get_lead(conv.bitrix_lead_id)
        except Exception:  # noqa: BLE001
            stats["ошибок"] += 1
            continue
        if str(lead.get("STATUS_ID") or "") in bp.TERMINAL_STATUSES:
            stats["закрыта"] += 1
            continue
        values = bp.lead_field_values(conv.qualification or {})
        empty = [k for k in values if codes.get(k) and not str(lead.get(codes[k]) or "").strip()]
        stats["полей_пустых"] += len(empty)
        stats["карточек_с_пустыми_полями"] += bool(empty)
        comments = str(lead.get("COMMENTS") or "")
        mine = (bp._dossier_ours(comments) or bp._legacy_ours(comments)
                or (conv.bitrix_dossier_by_bot and bp._no_human_lines(comments)))
        if comments and not mine:
            stats["досье_чужое"] += 1
        elif "Направление:" not in comments and "Состав:" not in comments:
            stats["досье_без_фактов"] += 1
        if apply and (empty or (mine and "Направление:" not in comments)):
            if await bp.sync_dossier(conv.user_id, adapter=client, _conv=conv, _lead=lead) or empty:
                stats["записано"] += 1
            await asyncio.sleep(pause)
    print(("ЗАПИСЬ" if apply else "СУХОЙ ПРОГОН") + f" за {days} дн.")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--pause", type=float, default=0.5, help="секунд между записями")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.days, args.apply, args.pause)))
