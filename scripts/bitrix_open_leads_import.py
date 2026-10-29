#!/usr/bin/env python3
"""B4: перенос ОТКРЫТЫХ лидов из архива Битрикса в панель — CRITICAL, перенос данных.

По умолчанию — СУХОЙ ПРОГОН: читает JSONL архива и (если задана база) только читает
её, печатает план «создам контакт / свяжу с существующим / уже перенесён / конфликт».
Ничего не пишет. Правила склейки — `app/domain/bitrix_lead_import.py`.

    # план без базы (все номера — «создам»)
    python scripts/bitrix_open_leads_import.py --archive /root/bitrix-archive
    # план против копии базы бота (только чтение)
    python scripts/bitrix_open_leads_import.py --archive /root/bitrix-archive --dsn "$DSN" \\
        --assignee visa=96451,110841 --assignee tours=155313,155267
    # запись — ТОЛЬКО по слову Алана, сначала на копии; имя базы повторить явно
    python scripts/bitrix_open_leads_import.py ... --dsn "$DSN" --yes --confirm-db 127.0.0.1:5432/frunze_copy

Телефоны в отчёте маскируются (PII). `--json PATH` — полный план для сверки.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain import bitrix_lead_import as imp            # noqa: E402
from app.integrations.crm.bitrix_archive import _jsonl      # noqa: E402


def mask(value: str) -> str:
    """Не больше последних 4 цифр, как `wappi.mask_phone` (ревью pdf, 1.4)."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 10:
        return "***"
    return f"***{digits[-4:]}"


def _assignees(pairs: list[str]) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        direction, _, ids = pair.partition("=")
        if direction not in imp.KNOWN_DIRECTIONS or not ids:
            raise SystemExit(f"--assignee ожидает visa=ID,ID или tours=ID: {pair!r}")
        for raw in ids.split(","):
            if raw.strip():
                out[raw.strip()] = direction
    return out


def _db_target(dsn: str) -> str:
    """Что подтверждает `--confirm-db`: хост:порт/база (SQLite — полный путь к файлу).

    Одного имени базы мало: копия под тем же именем на другом хосте и прод выглядели
    одинаково (ревью pdf, 1.2). Пароль и пользователь сюда не входят."""
    from sqlalchemy.engine import make_url
    url = make_url(dsn)
    backend = url.get_backend_name()
    if backend == "sqlite":
        return "sqlite:" + str(Path(url.database or "").resolve())
    port = url.port or {"postgresql": 5432, "mysql": 3306}.get(backend, "")
    return f"{url.host or 'localhost'}:{port}/{url.database or ''}"


def render(plan: imp.Plan, *, limit: int = 40) -> str:
    lines = ["План переноса открытых лидов (ничего не записано):"]
    for key, value in sorted(plan.summary.items()):
        lines.append(f"  {key}: {value}")
    problems = [i for i in plan.items if i.action in imp.PROBLEMS]
    if problems:
        lines.append(f"Реестр — решает человек ({len(problems)}):")
        for item in problems[:limit]:
            lines.append(f"  лид {item.lead_id}: {item.action} {mask(item.phone) if item.phone else ''} "
                         f"{item.detail}".rstrip())
        if len(problems) > limit:
            lines.append(f"  … ещё {len(problems) - limit}, полный список — --json")
    return "\n".join(lines)


async def run(argv=None, *, stdout=None) -> int:
    p = argparse.ArgumentParser(description="Перенос открытых лидов из архива Битрикса (B4)")
    p.add_argument("--archive", required=True)
    p.add_argument("--dsn", default="", help="async-DSN базы бота; без него — план без сверки")
    p.add_argument("--assignee", action="append", default=[],
                   help="направление по ответственному: visa=96451,110841 (можно несколько раз)")
    p.add_argument("--json", default="", help="куда сохранить полный план (с номерами!)")
    p.add_argument("--yes", action="store_true", help="записать (только с --dsn и --confirm-db)")
    p.add_argument("--confirm-db", default="",
                   help="хост:порт/база из DSN (SQLite — sqlite:/полный/путь) — защита от не той базы")
    args = p.parse_args(argv)
    say = (lambda m: print(m, file=stdout)) if stdout is not None else print
    archive = Path(args.archive)
    if not (archive / "leads.jsonl").is_file():
        say(f"Нет {archive / 'leads.jsonl'} — сначала scripts/bitrix_archive_export.py")
        return 2
    if args.yes and (not args.dsn or args.confirm_db != _db_target(args.dsn)):
        say("Запись отклонена: нужны --dsn и --confirm-db с ТОЧНЫМИ хостом, портом и базой "
            "из DSN — в виде хост:порт/база (для SQLite — sqlite:/полный/путь).")
        return 2
    contacts = {str(c.get("ID")): imp._raw_phones(c) for c in _jsonl(archive / "contacts.jsonl")}
    engine = sm = None
    existing: imp.Existing = imp.Existing()
    if args.dsn:
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        engine = create_async_engine(args.dsn)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        existing = imp.DbExisting(sm)
    try:
        plan = await imp.build_plan(_jsonl(archive / "leads.jsonl"), contacts, existing,
                                    assignee_direction=_assignees(args.assignee))
        say(render(plan))
        if args.json:
            fd = os.open(args.json, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"summary": plan.summary, "items": [i.__dict__ for i in plan.items]},
                          fh, ensure_ascii=False, indent=1)
        if args.yes:
            changes = await imp.apply_plan(sm, plan)
            failed = changes.pop("failed", [])
            say("ЗАПИСАНО: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
            for lead_id, kind in failed[:200]:
                say(f"  ошибка записи: лид {lead_id}: {kind}")
            if len(failed) > 200:
                say(f"  … ещё {len(failed) - 200} ошибок")
        return 0
    finally:
        if engine is not None:
            await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
