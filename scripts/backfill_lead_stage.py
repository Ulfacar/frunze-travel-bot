#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Разовый перенос старых карточек «Новый лид» → «В работе».

ПИШЕТ В БОЕВЫЕ ДАННЫЕ. По умолчанию только показывает: нужен явный `--apply`.

Зачем. Правка Медины 12.11.2026 («комбинированный вариант») работает ВПЕРЁД: новая
реплика менеджера двигает карточку сама. Но на проде уже лежат карточки, по которым
менеджер давно пишет, а стадия так и осталась «Новый лид» — автоматики тогда не было.
Пока их не перенести, доска показывает неправду: в «Новом лиде» висят клиенты, с
которыми работа идёт месяцами. Её прямая просьба — «удобно отслеживать, на каком
этапе находится каждый клиент».

Замер 12.11.2026: визовых в «Новый лид» 2239, из них менеджер уже писал 1279.
Активных за последние 30 дней среди них — 220.

## Почему по умолчанию только свежие

`--days 30` (по умолчанию) переносит только карточки с активностью за последние 30 дней.
Тащить все 1279 сразу — это разом переложить больше половины колонки, в том числе
клиентов, которым никто не писал с лета: они формально «в работе», а по факту мертвы,
и их место не здесь, а в касаниях или в закрытии. `--days 0` снимает ограничение,
если владелец решит иначе.

## Чего скрипт НЕ делает

Не трогает карточки на любой другой стадии: правка Медины только про «Новый лид»,
остальное менеджер двигает сам. Не трогает туры. Не ставит исходы и не пишет
владельца.

Запуск в боевом контейнере:

    docker cp scripts/backfill_lead_stage.py frunze-travel-app-1:/tmp/bls.py
    docker exec -e PYTHONPATH=/app frunze-travel-app-1 python /tmp/bls.py
    docker exec -e PYTHONPATH=/app frunze-travel-app-1 python /tmp/bls.py --apply

Бэкап пишется рядом со скриптом; забрать из контейнера сразу после записи:

    docker cp frunze-travel-app-1:/tmp/lead-stage-backup-<дата>.json /root/

Откат: `--restore <файл>` — вернёт прежнюю стадию тем карточкам, которые мы двигали
и которых с тех пор никто не трогал.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import tempfile
from datetime import datetime, timezone

from sqlalchemy import text

from app.admin import router as ar
try:
    from app.core.lead_stage import STAGE_IN_WORK, STAGE_NEW_LEAD
except ImportError:
    # Показ должен работать и ДО выката модуля: иначе нельзя посмотреть, что переедет,
    # пока правка не на проде. Значения продублированы осознанно и совпадают с
    # `app/core/lead_stage.py`; расхождение ловит тест в `tests/test_lead_stage.py`.
    STAGE_NEW_LEAD, STAGE_IN_WORK = "greeting", "qualification"

SELECT = """
SELECT c.user_id, c.stage, c.last_message_at,
       (SELECT count(*) FROM messages m
         WHERE m.conversation_id = c.id AND m.sender = 'manager') AS manager_msgs
FROM conversations c
WHERE c.funnel = :funnel AND NOT c.archived AND c.stage = :stage
  AND EXISTS (SELECT 1 FROM messages m
              WHERE m.conversation_id = c.id AND m.sender = 'manager')
"""


def _write_backup(path: pathlib.Path, rows: list[dict]) -> None:
    """Атомарная запись: обрыв не оставляет полуфайла, по которому потом откатываться."""
    payload = json.dumps({"created_at": datetime.now(timezone.utc).isoformat(),
                          "what": "conversations.stage до переноса «Новый лид» → «В работе»",
                          "rows": rows}, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    back = json.loads(path.read_text(encoding="utf-8"))
    saved = back.get("rows") or []
    if len(saved) != len(rows) or any(a.get("user_id") != b["user_id"]
                                      for a, b in zip(saved, rows)):
        raise RuntimeError("бэкап перечитался не тем, что писали — перенос не начинаю")


async def _apply(rows: list[dict], *, field_from: str, field_to: str, note: str) -> tuple[int, list]:
    """Условный UPDATE в одной транзакции вместе со следом в журнале."""
    changed, skipped = 0, []
    async with ar._domain_sessionmaker()() as session:
        for r in rows:
            res = await session.execute(text(
                "UPDATE conversations SET stage = :new "
                "WHERE user_id = :uid AND stage = :old"),
                {"new": r[field_to], "uid": r["user_id"], "old": r[field_from]})
            if res.rowcount != 1:
                skipped.append(r)
                continue
            changed += 1
            await session.execute(text(
                "INSERT INTO audit_log (manager, action, user_id, detail, created_at) "
                "VALUES ('system:backfill_lead_stage', 'stage', :uid, :d, now())"),
                {"uid": r["user_id"], "d": f"{r[field_from]} → {r[field_to]} ({note})"})
        await session.commit()
    return changed, skipped


async def restore(path: pathlib.Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if not rows:
        print("в бэкапе нет строк")
        return 2
    print(f"бэкап от {data.get('created_at')}, строк {len(rows)}")
    changed, skipped = await _apply(rows, field_from="after", field_to="before",
                                    note="откат переноса")
    print(f"возвращено: {changed}")
    if skipped:
        print(f"пропущено (стадия уже другая): {len(skipped)}")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="записать; без этого только показ")
    ap.add_argument("--funnel", default="visa", help="воронка (по умолчанию visa)")
    ap.add_argument("--days", type=int, default=30,
                    help="только карточки с активностью за N дней; 0 — все")
    ap.add_argument("--backup-dir", default=str(pathlib.Path(__file__).resolve().parent))
    ap.add_argument("--restore", metavar="BACKUP.JSON")
    args = ap.parse_args()

    if args.restore:
        return await restore(pathlib.Path(args.restore).expanduser())

    async with ar._domain_sessionmaker()() as s:
        found = (await s.execute(text(SELECT),
                                 {"funnel": args.funnel, "stage": STAGE_NEW_LEAD})).all()

    now = datetime.now(timezone.utc)
    plan = []
    skipped_old = 0
    for user_id, stage, last_at, msgs in found:
        if args.days:
            last = last_at.replace(tzinfo=timezone.utc) if last_at and last_at.tzinfo is None else last_at
            if last is None or (now - last).days > args.days:
                skipped_old += 1
                continue
        plan.append({"user_id": user_id, "before": stage, "after": STAGE_IN_WORK,
                     "last_message": str(last_at)[:10], "manager_msgs": int(msgs or 0)})

    print(f"кандидатов всего (менеджер писал, стадия «Новый лид»): {len(found)}")
    if args.days:
        print(f"из них активных за {args.days} дней: {len(plan)}; "
              f"старее — {skipped_old}, их не трогаем (--days 0 снимает ограничение)")
    if not plan:
        print("переносить нечего")
        return 0

    plan.sort(key=lambda r: r["last_message"], reverse=True)
    print("\nпосл.сообщ | реплик менеджера | диалог")
    for r in plan[:15]:
        print(f"{r['last_message']} | {r['manager_msgs']:4} | {r['user_id']}")
    if len(plan) > 15:
        print(f"... и ещё {len(plan) - 15}")

    if not args.apply:
        print("\nЭТО ПОКАЗ, НИЧЕГО НЕ ИЗМЕНЕНО. Для записи — тот же вызов с --apply.")
        return 0

    backup = (pathlib.Path(args.backup_dir).expanduser().resolve()
              / f"lead-stage-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json")
    _write_backup(backup, plan)
    print(f"\nбэкап: {backup}")
    print(f"ЗАБРАТЬ СРАЗУ: docker cp frunze-travel-app-1:{backup} /root/")

    changed, skipped = await _apply(plan, field_from="before", field_to="after",
                                    note="правка Медины 12.11: менеджер уже писал")
    print(f"перенесено: {changed}")
    if skipped:
        print(f"пропущено (стадия изменилась под нами): {len(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
