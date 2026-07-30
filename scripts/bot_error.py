"""Журнал ошибок бота из командной строки (P1.4).

Канал жалоб — владелец: «перешли кривой диалог в наш чат». Категорию ставим мы, отсюда и
CLI, а не кнопка в панели.

    # записать
    python scripts/bot_error.py add --category price \
        --user-id "frunze_tours_sezim:996700000001" \
        --quote "Сделаем скидку 15%" --expected "вилка без обещания скидки"

    # что открыто
    python scripts/bot_error.py list

    # закрыть — ТОЛЬКО с регрессионным тестом
    python scripts/bot_error.py fix 3 \
        --test tests/test_validator.py::test_no_discount_promise --ref abc1234

    # прогресс по категориям (чем меряем «опытный к сентябрю»)
    python scripts/bot_error.py stats
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import bot_errors  # noqa: E402


def _print_rows(rows) -> None:
    if not rows:
        print("открытых ошибок нет ✅")
        return
    for r in rows:
        when = r.created_at.strftime("%d.%m %H:%M") if r.created_at else "—"
        print(f"#{r.id} [{r.category}] {when} {r.bot_id or '—'}/{r.funnel or '—'}")
        if r.quote:
            print(f"    бот: {r.quote[:160]}")
        if r.expected:
            print(f"    надо: {r.expected[:160]}")
        if r.user_id:
            print(f"    диалог: {r.user_id}")


async def _main(args) -> int:
    if args.cmd == "add":
        error_id = await bot_errors.report(
            category=args.category, quote=args.quote or "", expected=args.expected or "",
            user_id=args.user_id or "", source=args.source, note=args.note or "")
        print(f"записано #{error_id}")
        return 0
    if args.cmd == "list":
        _print_rows(await bot_errors.open_errors(limit=args.limit))
        return 0
    if args.cmd == "fix":
        ok = await bot_errors.mark_fixed(args.id, covered_by_test=args.test,
                                         fix_ref=args.ref or "")
        print(f"#{args.id} закрыта тестом {args.test}" if ok
              else f"#{args.id} не найдена или уже закрыта")
        return 0 if ok else 1
    if args.cmd == "wontfix":
        ok = await bot_errors.mark_wontfix(args.id, note=args.note)
        print(f"#{args.id} закрыта как wontfix" if ok else f"#{args.id} не найдена")
        return 0 if ok else 1
    if args.cmd == "stats":
        data = await bot_errors.counts()
        if not data:
            print("журнал пуст")
        for category in sorted(data):
            row = data[category]
            print(f"{category:14} открыто {row.get('open', 0):3}  "
                  f"починено {row.get('fixed', 0):3}  wontfix {row.get('wontfix', 0):3}")
        leaky = await bot_errors.untested_fixes()
        if leaky:
            print(f"\n⚠ закрыто без регрессионного теста: {[r.id for r in leaky]} — "
                  "петля протекает, такие ошибки вернутся")
        return 0
    return 2


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="записать ошибку")
    add.add_argument("--category", required=True, choices=sorted(bot_errors.CATEGORIES))
    add.add_argument("--quote", help="что бот сказал не так")
    add.add_argument("--expected", help="как должно было быть")
    add.add_argument("--user-id", help="ключ диалога (bot_id:номер)")
    add.add_argument("--source", default="owner", choices=["owner", "manager", "auto"])
    add.add_argument("--note")

    lst = sub.add_parser("list", help="открытые ошибки")
    lst.add_argument("--limit", type=int, default=50)

    fix = sub.add_parser("fix", help="закрыть (нужен регрессионный тест)")
    fix.add_argument("id", type=int)
    fix.add_argument("--test", required=True, help="напр. tests/test_x.py::test_y")
    fix.add_argument("--ref", help="коммит/PR")

    wf = sub.add_parser("wontfix", help="закрыть без исправления (с объяснением)")
    wf.add_argument("id", type=int)
    wf.add_argument("--note", required=True)

    sub.add_parser("stats", help="прогресс по категориям")

    args = p.parse_args()
    try:
        raise SystemExit(asyncio.run(_main(args)))
    except bot_errors.BotErrorInput as exc:
        print(f"ошибка: {exc}")
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
