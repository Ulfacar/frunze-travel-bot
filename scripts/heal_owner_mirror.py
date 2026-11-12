#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Привести владельца в переписке к владельцу в реестре — разовое лечение.

ПИШЕТ В БОЕВЫЕ ДАННЫЕ. По умолчанию ничего не меняет: нужен явный `--apply`.

Зачем. `app/admin/contracts.py:_owner` блокирует запись договора, когда доменный
владелец (`assignments`, история назначений с причинами) и панельный
(`conversations.assigned_to`, зеркало) оба заполнены и РАЗНЫЕ. Замер 12.11.2026
нашёл 25 таких клиентов, 10 из них писали в ноябре.

## Почему лечение разделено на две группы

Замер по журналу панели (12.11.2026) показал то, чего не видно из кода:

* реестровый владелец ни одного из этих 25 диалогов в панели не касался НИ РАЗУ;
  у Айсины, на которую записаны 17 туровых, за всё время ноль рабочих действий;
* панельный владелец касался — но последний раз в июне-июле;
* рабочих действий в панели в ноябре всего 10, все у Адеми, при 2530 сообщениях
  менеджеров за тот же месяц: люди работают клиентов в Битриксе и WhatsApp, а не
  в панели, поэтому журнал панели НЕ говорит, кто ведёт клиента сегодня.

Поэтому «реестр правильный» механически применять нельзя. Но часть случаев
однозначна, и они разделены флагом `--group`:

`departed` — в переписке стоит тот, кто клиента вести не может: `sezim` (уволилась
    29.07, в настройках её нет, войти не может) или служебный `admin` («Админ», не
    продающий человек). Тут лечение ничего ни у кого не отнимает. 7 карточек.
`contested` — в переписке живой менеджер (`ademi` 17, `eliza` 1), а в реестре другой
    живой менеджер. Это НЕ баг, а вопрос «чей клиент»: реестр хранит июльское решение
    («клиенты Сезим → Айсина»), переписка — того, кто их тогда трогал. Решает Алан,
    не скрипт. 18 карточек.
`all` — обе группы.

Чего скрипт НЕ делает: не чинит источник. Автоназначение продолжит делать новые пары
(≈6 за четыре месяца), пока не решено правило «кто главнее — человек в переписке или
очередь бота». Это отдельный вопрос, он в `ai/STATE.md`.

## Что меняется у людей

Видимость диалога идёт по боту (`_can_view_conversation`) — её лечение НЕ трогает.
Меняется владелец в карточке, листы по владельцу (утренний лист, «клиент ждёт»,
касания) и право открыть форму договора (`contracts._conversation`).

Известные ограничения (ревью 12.11.2026), скрипт их не закрывает:
* открытые задачи календаря остаются у прежнего владельца — после лечения свериться
  по `calendar_tasks` для этих user_id;
* `reply_alert_at` не сбрасывается: если пуш «клиент ждёт» ушёл прежнему владельцу,
  новый в этом эпизоде ожидания его не получит;
* при включённом зеркале Bitrix ответственный лида может поменяться на следующей
  синхронизации (`bitrix_mirror._assignee_for` читает `assigned_to`);
* смена владельца может открыть ВТОРОЙ блок формы договора, если новый владелец не
  имеет доступа к направлению (`can_open_case`) — скрипт это не проверяет.

`assigned_at` не трогаем намеренно: его никто не читает в запросах, а сохранённая
дата исходного закрепления делает откат полным (ревью 12.11.2026).

## Запуск

Кандидатов берём ровно из `owner_mirror_check.collect()` — тем же кодом, что считает
замер, чтобы лечение не могло разойтись с отчётом. Перед записью замер повторяется:
пара «было → станет» должна совпасть, иначе строка пропускается.

    docker cp scripts/owner_mirror_check.py frunze-travel-app-1:/tmp/owner_mirror_check.py
    docker cp scripts/heal_owner_mirror.py  frunze-travel-app-1:/tmp/heal_owner_mirror.py
    docker exec -e PYTHONPATH=/app:/tmp frunze-travel-app-1 \
        python /tmp/heal_owner_mirror.py --group departed
    docker exec -e PYTHONPATH=/app:/tmp frunze-travel-app-1 \
        python /tmp/heal_owner_mirror.py --group departed --apply --backup-dir /tmp

**Сразу после `--apply` забрать бэкап из контейнера** — он лежит в файловой системе
контейнера, и ближайший деплой её пересоздаст:

    docker cp frunze-travel-app-1:/tmp/owner-mirror-backup-<дата>.json /root/

Откат по этому файлу: `--restore /root/owner-mirror-backup-<дата>.json` (условный, по
новому значению — чужую правку поверх не затирает).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timezone

from sqlalchemy import text

from app.admin import router as ar

try:
    from owner_mirror_check import collect
except ImportError:  # pragma: no cover — запуск из корня репозитория
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from owner_mirror_check import collect

AUDIT_ACTOR = "system:heal_owner_mirror"

# Логины, которые настроены, но клиента вести не могут. `admin` — служебная учётка
# «Админ» (`admin=False`, то есть не полный администратор, а просто общий вход):
# карточка, записанная на него, не принадлежит никому из продающих.
IMPERSONAL = {"admin"}


def _group_of(panel_owner: str, panel_configured: bool) -> str:
    """`departed` — владельца в переписке по факту нет; `contested` — есть живой."""
    if not panel_configured or panel_owner in IMPERSONAL:
        return "departed"
    return "contested"


def _plan_from(found, group: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Разложить находки замера на план, отложенное и отказы."""
    plan, other_group, refused = [], [], []
    for last_at, direction, user_id, panel, panel_ok, domain, domain_ok, asg_at, reason in found:
        row = dict(user_id=user_id, direction=direction, before=panel, after=domain,
                   reason=reason, assigned_at=asg_at, last_message=last_at,
                   group=_group_of(panel, panel_ok))
        if not domain_ok:
            # Владелец из реестра обязан быть настроенным логином: иначе лечение
            # отдаёт карточку тому, кого в панели нет, и клиент исчезает из всех
            # листов по владельцу.
            refused.append(row)
        elif group in ("all", row["group"]):
            plan.append(row)
        else:
            other_group.append(row)
    return plan, other_group, refused


def _write_backup(path: pathlib.Path, rows: list[dict]) -> None:
    """Атомарная запись бэкапа: обрыв на середине не оставляет полуфайл.

    Тот же урок, что со `prod.env` (аудит 12.11.2026): файл, по которому потом
    откатываются, нельзя писать поверх себя и нельзя оставлять недописанным.
    """
    payload = json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "what": "conversations.assigned_to до лечения owner-mirror",
        "rows": rows,
    }, ensure_ascii=False, indent=2)
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
    # Перечитываем: бэкап, который не разбирается, бэкапом не является.
    back = json.loads(path.read_text(encoding="utf-8"))
    saved = back.get("rows") or []
    if len(saved) != len(rows) or any(
            s.get("before") != r["before"] or s.get("user_id") != r["user_id"]
            for s, r in zip(saved, rows)):
        raise RuntimeError("бэкап перечитался не тем, что писали — лечение не начинаю")


async def _apply_rows(rows: list[dict], *, field_from: str, field_to: str,
                      audit_note: str) -> tuple[int, list[dict]]:
    """Записать владельца и след в ОДНОЙ транзакции.

    Журнал пишется той же сессией и тем же commit (ревью 12.11.2026): иначе
    оставалось полусостояние «данные изменены, следа нет», а `add_audit` на
    не-postgres бэкенде молча писал бы в память процесса.
    """
    changed, skipped = 0, []
    async with ar._domain_sessionmaker()() as session:
        for r in rows:
            # Условный UPDATE, а не безусловная запись: если владельца прямо сейчас
            # поменял менеджер, его правку не затираем. Сравнение нормализованное —
            # в базе логин лежит как пришёл из формы, регистр и пробелы возможны.
            res = await session.execute(text(
                "UPDATE conversations SET assigned_to = :new "
                "WHERE user_id = :uid AND lower(trim(coalesce(assigned_to,''))) = :old"),
                {"new": r[field_to], "uid": r["user_id"], "old": r[field_from]})
            if res.rowcount != 1:
                skipped.append(r)
                continue
            changed += 1
            await session.execute(text(
                "INSERT INTO audit_log (manager, action, user_id, detail, created_at) "
                "VALUES (:m, 'reassign', :uid, :d, now())"),
                {"m": AUDIT_ACTOR, "uid": r["user_id"],
                 "d": f"{r[field_from]} → {r[field_to]} ({audit_note}, {r['reason']})"})
        await session.commit()
    return changed, skipped


async def _restore(path: pathlib.Path) -> int:
    """Откат по бэкапу: вернуть прежнего владельца, не затирая чужие правки."""
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    if not rows:
        print("в бэкапе нет строк")
        return 2
    print(f"бэкап от {data.get('created_at')}, строк {len(rows)}")
    for r in rows:
        print(f"   {r['user_id']} | вернуть {r['after']} → {r['before']}")
    changed, skipped = await _apply_rows(
        rows, field_from="after", field_to="before", audit_note="owner-mirror откат")
    print(f"возвращено: {changed}")
    if skipped:
        print(f"пропущено (владелец уже не тот, что записали мы): {len(skipped)}")
        for r in skipped:
            print(f"   {r['user_id']} | ожидал {r['after']}")
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="записать изменения; без этого только показывает")
    ap.add_argument("--group", choices=("departed", "contested", "all"), default="departed",
                    help="departed (по умолчанию): в переписке уволенный или служебный "
                         "владелец; contested: живой менеджер — решает Алан; all: обе")
    ap.add_argument("--max", type=int, default=50,
                    help="предохранитель: отказаться, если кандидатов больше (по умолчанию 50)")
    ap.add_argument("--backup-dir", default=str(pathlib.Path(__file__).resolve().parent),
                    help="куда положить бэкап (по умолчанию рядом со скриптом)")
    ap.add_argument("--restore", metavar="BACKUP.JSON",
                    help="откат: вернуть владельцев из этого бэкапа")
    args = ap.parse_args()

    if args.restore:
        return await _restore(pathlib.Path(args.restore).expanduser())

    found, _ = await collect()
    plan, other_group, refused = _plan_from(found, args.group)

    print(f"расхождений всего: {len(found)} | группа «{args.group}»: {len(plan)}")
    if other_group:
        print(f"другая группа (не трогаем этим запуском): {len(other_group)}")
    if refused:
        print(f"ОТКАЗАНО (владелец из реестра не настроен в панели): {len(refused)}")
        for r in refused:
            print(f"   {r['user_id']} | {r['before']} → {r['after']} | {r['reason']}")
    if not plan:
        print("в этой группе лечить нечего")
        return 0
    if len(plan) > args.max:
        print(f"ОТКАЗ: кандидатов {len(plan)} > предела {args.max}. "
              "Проверьте, что считается, прежде чем поднимать предел.")
        return 2

    print("\nпосл.сообщ | напр  | user_id | было → станет | причина назначения")
    for r in plan:
        print(f"{r['last_message']} | {r['direction']:5} | {r['user_id'][:28]:28} | "
              f"{r['before']} → {r['after']} | {r['reason']}")
    moves: dict[str, int] = {}
    for r in plan:
        key = f"{r['before']} → {r['after']}"
        moves[key] = moves.get(key, 0) + 1
    print("\nпереезды:", ", ".join(f"{k}: {v}" for k, v in sorted(moves.items())))

    if not args.apply:
        print("\nЭТО ПОКАЗ, НИЧЕГО НЕ ИЗМЕНЕНО. Для записи — тот же вызов с --apply.")
        return 0

    backup = (pathlib.Path(args.backup_dir).expanduser().resolve()
              / f"owner-mirror-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json")
    _write_backup(backup, plan)
    print(f"\nбэкап: {backup} (права 0600)")
    print(f"ЗАБРАТЬ ИЗ КОНТЕЙНЕРА СРАЗУ: docker cp frunze-travel-app-1:{backup} /root/")

    # Повторный замер перед записью: между первым чтением и UPDATE менеджер мог
    # переназначить клиента, и реестр уже говорит другое (ревью 12.11.2026).
    fresh, _ = await collect()
    now = {(r[2], r[3], r[5]) for r in fresh}
    stale = [r for r in plan if (r["user_id"], r["before"], r["after"]) not in now]
    if stale:
        print(f"ПРОПУСКАЮ, изменилось пока считали: {len(stale)}")
        for r in stale:
            print(f"   {r['user_id']} | ожидал {r['before']} → {r['after']}")
        plan = [r for r in plan if r not in stale]
    if not plan:
        print("после перепроверки лечить нечего")
        return 0

    changed, skipped = await _apply_rows(
        plan, field_from="before", field_to="after", audit_note="owner-mirror")
    # След в журнале идёт тем же commit, что и смена владельца: отдельного
    # счёта не держим — он не может расходиться с `changed`, и проверять в нём нечего.
    print(f"изменено: {changed}")
    if skipped:
        print(f"пропущено (строка изменилась под нами): {len(skipped)}")
        for r in skipped:
            print(f"   {r['user_id']} | ожидал {r['before']}")

    rest, _ = await collect()
    print(f"\nрасхождений осталось всего: {len(rest)}")
    for last_at, direction, user_id, panel, panel_ok, domain, _dok, _at, reason in rest:
        print(f"   {user_id} | {panel} ↔ {domain} | "
              f"{_group_of(panel, panel_ok)} | {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
