#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Найти клиентов, по которым оформление услуги заблокировано расхождением владельца.

ТОЛЬКО ЧТЕНИЕ. Ничего не пишет, ничего не создаёт — запускать на проде можно.

Зачем. `app/admin/contracts.py:_owner` блокирует запись договора, если доменный
владелец (таблица `assignments`, история назначений с причинами) и панельный
(`conversations.assigned_to`, зеркало) оба заполнены и РАЗНЫЕ. Менеджер при этом
видит дело, но на сохранении получает «назначения в переписке и реестре
расходятся» — и в панели это не разруливается.

Причина появления таких пар закрыта 12.11.2026 (bb650dd): зеркало теперь пишет
сторож, сразу после того как домен подтвердил назначение. Прежде его писал
`takeover` безусловно и ПОСЛЕ сторожа, так что при одновременном взятии зеркало
оставалось за проигравшим гонку. Старые расхождения правка не лечит — их надо
находить и чинить отдельно, и первым делом знать, сколько их.

Первый прогон на проде 12.11.2026: 3553 диалога с панельным владельцем, 3409
сравнимых, **25 расхождений** (в основном след ухода Сезим: в переписке остался
один человек, в реестре другой).

Запуск в боевом контейнере:

    docker cp scripts/owner_mirror_check.py frunze-travel-app-1:/tmp/omc.py
    docker exec -e PYTHONPATH=/app frunze-travel-app-1 python /tmp/omc.py

`PYTHONPATH=/app` обязателен: скрипт лежит в /tmp, и без него `app` не импортируется.
"""
from __future__ import annotations

import asyncio
from collections import Counter

from sqlalchemy import text

from app.admin import router as ar
from app.admin.contracts import _find_contact, _identity
from app.config import settings
from app.domain import live_assign
from app.domain.models import DomainError


async def collect() -> tuple[list[tuple], dict[str, int]]:
    logins = {m.login.strip().lower() for m in settings.manager_list()}
    skipped = Counter()
    found: list[tuple] = []
    compared = 0
    async with ar._domain_sessionmaker()() as session:
        rows = (await session.execute(text(
            "SELECT user_id, bot_id, phone, channel, funnel, assigned_to, last_message_at "
            "FROM conversations WHERE COALESCE(assigned_to,'') <> ''"))).all()
        total = len(rows)
        for user_id, bot_id, phone, channel, funnel, assigned_to, last_at in rows:
            conv = type("Conv", (), dict(
                user_id=user_id, bot_id=bot_id, phone=phone or "", channel=channel or "",
                funnel=funnel or "", assigned_to=assigned_to))()
            direction = (funnel if funnel in ("tours", "visa", "tickets")
                         else ar._authz_direction(conv))
            if not direction:
                skipped["направление не определено"] += 1
                continue
            try:
                identity = _identity(conv)
            except DomainError:
                # Тот же отказ увидит и оформление услуги — это отдельная проблема,
                # не расхождение владельца.
                skipped["идентичность не разобрана"] += 1
                continue
            contact = await _find_contact(session, identity)
            if contact is None:
                skipped["контакта в реестре нет"] += 1
                continue
            asg = await live_assign.active_assignment(session, contact.id, direction)
            domain_owner = (asg.manager_id or "").strip().lower() if asg else ""
            panel_owner = (assigned_to or "").strip().lower()
            if not domain_owner:
                skipped["доменного владельца нет"] += 1
                continue
            compared += 1
            if domain_owner != panel_owner:
                found.append((
                    str(last_at)[:10], direction, user_id,
                    panel_owner, panel_owner in logins,
                    domain_owner, domain_owner in logins,
                    str(asg.assigned_at)[:10], (asg.reason or "")[:24]))
    skipped["ВСЕГО диалогов с панельным владельцем"] = total
    skipped["сравнимо (есть оба владельца)"] = compared
    return found, dict(skipped)


async def main() -> int:
    found, stats = await collect()
    for key in ("ВСЕГО диалогов с панельным владельцем", "сравнимо (есть оба владельца)"):
        print(f"{key}: {stats.pop(key, 0)}")
    print(f"РАСХОЖДЕНИЙ (оформление услуги заблокировано): {len(found)}")
    if found:
        found.sort(reverse=True)
        print("\nпосл.сообщ  | напр  | user_id | панель | реестр | закреплён | причина")
        for r in found:
            pan = f"{r[3]}{'' if r[4] else ' (НЕ НАСТРОЕН)'}"
            dom = f"{r[5]}{'' if r[6] else ' (НЕ НАСТРОЕН)'}"
            print(f"{r[0]}  | {r[1]:5} | {r[2][:26]:26} | {pan} | {dom} | {r[7]} | {r[8]}")
        print("\nпо месяцу последнего сообщения:",
              Counter(r[0][:7] for r in found).most_common())
    print("\nпропущено:", ", ".join(f"{k} {v}" for k, v in sorted(stats.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
