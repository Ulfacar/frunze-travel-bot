#!/usr/bin/env python3
"""E1-04 — репетиция сопоставления старых обращений (ТОЛЬКО ЧТЕНИЕ).

Читает legacy `conversations`, строит план сопоставления и печатает отчёт.
В базу не пишет ничего: по ТЗ реальный перенос выполняется в E4, а здесь нужна
идемпотентная репетиция и реестр спорного.

Телефоны в отчёте маскируются: это PII, а отчёт уходит в переписку и в логи.
Запуск дважды обязан дать одинаковый отчёт — это и проверяется ключом `--twice`.

    python scripts/legacy_match_rehearsal.py --dsn "$DSN" --twice
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text                                      # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine           # noqa: E402

from app.domain.legacy_match import LegacyDialog, plan_links      # noqa: E402

QUERY = text("""
    SELECT user_id, phone, bot_id, funnel, outcome,
           bitrix_lead_id, sale_amount, sale_currency
    FROM conversations
""")


def mask(value: str) -> str:
    """Идентификатор для отчёта: видно страну и хвост, середина скрыта.

    Короткие значения скрываются целиком. Прежний вариант при 7 цифрах печатал
    их все, а telegram-id из 9 цифр показывал 7 из 9 — то есть «маска» выдавала
    идентификатор полностью. Отчёт уходит в переписку и в логи.
    """
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 10:
        return "***"
    keep = len(digits) // 3
    return f"{digits[:keep]}***{digits[-keep:]}"


async def load(dsn: str) -> list[LegacyDialog]:
    engine = create_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(QUERY)).mappings().all()
    finally:
        await engine.dispose()
    return [LegacyDialog(
        user_id=str(r["user_id"] or ""), phone=str(r["phone"] or ""),
        bot_id=str(r["bot_id"] or ""), funnel=r["funnel"],
        outcome=str(r["outcome"] or ""),
        bitrix_lead_id=str(r["bitrix_lead_id"] or ""),
        sale_amount=r["sale_amount"], sale_currency=str(r["sale_currency"] or ""),
    ) for r in rows]


def report(plan, *, limit: int) -> str:
    lines = [f"обращений сопоставлено в связи: {len(plan.links)}"]
    by_direction: dict[str, int] = {}
    for link in plan.links:
        by_direction[link.direction] = by_direction.get(link.direction, 0) + 1
    for direction, count in sorted(by_direction.items()):
        lines.append(f"  {direction}: {count}")
    lines.append("")
    lines.append("реестр спорного:")
    kinds: dict[str, int] = {}
    for problem in plan.problems:
        kinds[problem.kind] = kinds.get(problem.kind, 0) + 1
    if not kinds:
        lines.append("  пусто")
    for kind, count in sorted(kinds.items()):
        lines.append(f"  {kind}: {count}")
        shown = [p for p in plan.problems if p.kind == kind][:limit]
        for problem in shown:
            ids = ", ".join(mask(uid.split(":", 1)[-1]) for uid in problem.user_ids[:3])
            lines.append(f"    {ids} — {problem.detail}")
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser()
    # По умолчанию берём адрес оттуда же, откуда его берёт приложение: на проде
    # переменной DATABASE_URL в окружении нет, он собирается в настройках.
    parser.add_argument("--dsn", default="")
    parser.add_argument("--use-app-settings", action="store_true",
                        help="взять адрес базы из настроек приложения (в контейнере)")
    parser.add_argument("--twice", action="store_true",
                        help="прогнать дважды и сверить отчёты (идемпотентность)")
    parser.add_argument("--limit", type=int, default=3,
                        help="сколько примеров печатать на каждую причину")
    args = parser.parse_args()
    dsn = args.dsn or os.environ.get("DATABASE_URL", "")
    if not dsn and args.use_app_settings:
        from app.config import settings
        dsn = settings.database_url
    if not dsn:
        # Молча брать адрес из настроек нельзя: по умолчанию там localhost с
        # дефолтными учётными данными, и репетиция «успешно» прошла бы по пустой
        # чужой базе, не сказав об этом.
        print("нужен --dsn, DATABASE_URL или явный --use-app-settings",
              file=sys.stderr)
        return 2

    dialogs = await load(dsn)
    print(f"прочитано обращений: {len(dialogs)}")
    first = report(plan_links(dialogs), limit=args.limit)
    print(first)
    if args.twice:
        # Второй прогон идёт на ПЕРЕМЕШАННОМ входе и сравнивает планы целиком,
        # а не усечённые отчёты. Повтор на том же списке ничего не доказывал:
        # он не ловил зависимость от порядка, которая в первой версии была.
        import random
        shuffled = list(dialogs)
        random.Random(20261005).shuffle(shuffled)
        same = plan_links(dialogs) == plan_links(shuffled)
        second = report(plan_links(shuffled), limit=args.limit)
        print()
        print("повторный прогон на перемешанном входе совпал: "
              + ("ДА" if same and first == second else "НЕТ"))
        return 0 if same and first == second else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
