#!/usr/bin/env python
"""Калибровка сторожа «клиент ждёт» на реальной истории — ДО включения флага.

Зачем. Ответ заказчика 2.5 (05.11.2026) перевёл счёт ожидания в рабочие минуты
направления. Это **детектор с порогом**, то есть класс C, и по `docs/protocol.md`
такое включается только после калибровки на истории. Калибровать было нечем:
`scripts/alert_replay.py` прогоняет `channel_heartbeat.decide()` — сторож ТИШИНЫ
КАНАЛА, совсем другой детектор. Ревью 09.11.2026 на это и указало.

Что считает. Два прогона одной и той же истории: с календарным счётом (как на проде
сейчас) и с рабочим окном (как будет при `awaiting_working_hours_enabled`). Разница
между ними — это и есть цена включения флага, в штуках и по часам суток.

Ключевая деталь, та же что в `alert_replay.py`: скрипт зовёт **настоящие**
`awaiting.select_awaiting_targets` и `awaiting.select_telegram_targets`. Своя копия
логики разошлась бы с кодом на второй правке и снова врала бы.

Моделируется тик за тиком, как в рантайме: cooldown (`_pinged_recently`) и бюджет
напоминаний (`_ping_budget_left`) ведутся по ходу прогона, иначе «сколько пушей в
сутки» завышается в разы.

ОГРАНИЧЕНИЕ, которое нельзя забывать при чтении вывода: `stage`, `intercepted`,
`outcome` и `archived` берутся ТЕКУЩИЕ — историю этих полей таблица не хранит.
Восстанавливается по-настоящему только то, что определяется сообщениями:
`last_message_at`, `last_sender`, `last_text`. Поэтому диалог, который менеджер
перехватил вчера, в прогоне выглядит перехваченным всю историю. Числа ниже — оценка
сверху по числу срабатываний, а не точный повтор прошлого.

Только ЧТЕНИЕ: ни одного UPDATE/INSERT. Персональные данные не покидают сервер —
печатаются только агрегаты, поэтому запускать на проде, внутри контейнера:

    ssh frunze 'docker exec frunze-travel-app-1 python scripts/awaiting_replay.py --days 21'
    ssh frunze 'docker exec frunze-travel-app-1 python scripts/awaiting_replay.py --days 21 --threshold 20'
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BISHKEK = timedelta(hours=6)
TICK_SECONDS = 300          # как в рантайме: тик сторожа раз в 5 минут


class ReplayCfg:
    """Настройки прогона: имена полей те же, что читает сторож."""

    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


async def load(days: int) -> tuple[list[dict], datetime, datetime]:
    """История диалогов за N дней: метаданные + таймлайн сообщений. Только SELECT."""
    from sqlalchemy import select
    from app.integrations.crm.db import ConvMessage, Conversation, get_sessionmaker

    since = datetime.now(timezone.utc) - timedelta(days=days)
    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            select(ConvMessage.conversation_id, ConvMessage.sender,
                   ConvMessage.text, ConvMessage.created_at)
            .where(ConvMessage.created_at >= since)
            .order_by(ConvMessage.created_at))).all()
        convs = (await session.execute(
            select(Conversation.id, Conversation.user_id, Conversation.phone,
                   Conversation.bot_id, Conversation.funnel, Conversation.stage,
                   Conversation.intercepted, Conversation.archived,
                   Conversation.outcome, Conversation.assigned_to))).all()

    meta = {c[0]: c for c in convs}
    timeline: dict[int, list[tuple[datetime, str, str]]] = collections.defaultdict(list)
    for conv_id, sender, text, created_at in rows:
        if conv_id in meta:
            stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
            timeline[conv_id].append((stamp, sender or "", text or ""))

    dialogs = []
    for conv_id, events in timeline.items():
        if not events:
            continue
        c = meta[conv_id]
        dialogs.append({
            "events": events,
            "base": dict(user_id=c[1], phone=c[2] or c[1], bot_id=c[3] or "",
                         funnel=c[4] or "", stage=c[5] or "", intercepted=bool(c[6]),
                         archived=bool(c[7]), outcome=c[8] or "",
                         assigned_to=c[9] or "", qualification={}),
        })
    if not dialogs:
        return [], since, datetime.now(timezone.utc)
    first = min(d["events"][0][0] for d in dialogs)
    last = max(d["events"][-1][0] for d in dialogs)
    return dialogs, first, last


def replay(dialogs: list[dict], cfg, *, working_hours: bool) -> dict:
    """Прогон тик за тиком через НАСТОЯЩИЕ функции сторожа."""
    from app.core import awaiting

    if not dialogs:
        return {"team": 0, "personal": 0, "by_hour": {}, "pinged": set()}
    start = min(d["events"][0][0] for d in dialogs)
    end = max(d["events"][-1][0] for d in dialogs)

    # Изменяемое состояние пингов на каждый диалог — так же, как его ведёт рантайм.
    state = {i: {"count": 0, "pinged_at": None} for i, _ in enumerate(dialogs)}
    team_alerts, personal_pushes = 0, 0
    by_hour: collections.Counter[int] = collections.Counter()
    pinged: set[str] = set()
    cursor = [0] * len(dialogs)
    snapshot: list[SimpleNamespace | None] = [None] * len(dialogs)

    moment = start
    while moment <= end:
        live = []
        for i, dialog in enumerate(dialogs):
            events = dialog["events"]
            while cursor[i] < len(events) and events[cursor[i]][0] <= moment:
                stamp, sender, text = events[cursor[i]]
                snapshot[i] = SimpleNamespace(
                    **dialog["base"], last_message_at=stamp, last_sender=sender,
                    last_text=text[:200], awaiting_ping_count=state[i]["count"],
                    awaiting_pinged_at=state[i]["pinged_at"])
                cursor[i] += 1
            if snapshot[i] is None:
                continue
            snapshot[i].awaiting_ping_count = state[i]["count"]
            snapshot[i].awaiting_pinged_at = state[i]["pinged_at"]
            live.append((i, snapshot[i]))

        convs = [c for _, c in live]
        team = awaiting.select_awaiting_targets(convs, moment, cfg,
                                                working_hours=working_hours)
        team_alerts += len(team)
        personal = awaiting.select_telegram_targets(convs, moment, cfg,
                                                    working_hours=working_hours)
        for conv in personal:
            index = next(i for i, c in live if c is conv)
            state[index]["count"] += 1
            state[index]["pinged_at"] = moment
            personal_pushes += 1
            pinged.add(conv.user_id)
            by_hour[((moment + BISHKEK).hour)] += 1
        moment += timedelta(seconds=TICK_SECONDS)

    # Снимок на конец окна — чтобы объяснить, ПОЧЕМУ диалог остался без пуша.
    tail = {}
    for i, dialog in enumerate(dialogs):
        conv = snapshot[i]
        if conv is None:
            continue
        tail[conv.user_id] = {
            "bot": conv.bot_id,
            "last": conv.last_message_at,
            "calendar_min": (end - conv.last_message_at).total_seconds() / 60,
            "work_min": awaiting.waited_minutes(conv, end, working_hours=True),
        }
    return {"team": team_alerts, "personal": personal_pushes,
            "by_hour": dict(by_hour), "pinged": pinged, "tail": tail,
            "window_end": end}


def explain(dialogs: list[dict], user_id: str, cfg) -> None:
    """Разбор одного диалога по тикам: где он был целью и что его отсекло.

    Нужен потому, что агрегаты говорят «пуша нет», но не говорят почему: порог,
    потолок свежести, cooldown, бюджет напоминаний и лимит на тик отсекают в разных
    местах, и лечатся они по-разному. Печатает только канал и время — без номера.
    """
    from app.core import awaiting

    dialog = next((d for d in dialogs if d["base"]["user_id"] == user_id), None)
    if dialog is None:
        return
    events = dialog["events"]
    end = max(d["events"][-1][0] for d in dialogs)
    base = dialog["base"]
    print(f"\nРАЗБОР ОДНОГО ПОТЕРЯННОГО ({base['bot_id']}, "
          f"stage={base['stage']}, intercepted={base['intercepted']}, "
          f"outcome={base['outcome'] or 'пусто'})")
    print(f"  последнее сообщение: {(events[-1][0] + BISHKEK):%a %d.%m %H:%M} "
          f"(время Бишкека), отправитель {events[-1][1]}")

    state = {"count": 0, "pinged_at": None}
    conv = SimpleNamespace(**base, last_message_at=events[-1][0],
                           last_sender=events[-1][1], last_text=events[-1][2][:200],
                           awaiting_ping_count=0, awaiting_pinged_at=None)
    moment = events[-1][0]
    shown, first_target = 0, None
    while moment <= end and shown < 12:
        conv.awaiting_ping_count = state["count"]
        conv.awaiting_pinged_at = state["pinged_at"]
        work = awaiting.waited_minutes(conv, moment, working_hours=True)
        team = bool(awaiting.select_awaiting_targets([conv], moment, cfg,
                                                     working_hours=True))
        personal = bool(awaiting.select_telegram_targets([conv], moment, cfg,
                                                         working_hours=True))
        if team and first_target is None:
            first_target = moment
        if team or personal or shown == 0:
            local = moment + BISHKEK
            if personal:
                reason = "цель и пуш"
            elif team:
                # Разбираем ровно те предикаты, что стоят в select_telegram_targets.
                blockers = []
                cap_min = float(getattr(cfg, "awaiting_max_age_working_hours", 12)) * 60
                if work > cap_min:
                    blockers.append(f"потолок свежести ({work:.0f} > {cap_min:.0f} раб. мин)")
                if awaiting._is_closing(getattr(conv, "last_text", "")):
                    blockers.append("последняя реплика выглядит закрывающей")
                if awaiting._pinged_recently(conv, moment, cfg):
                    blockers.append("cooldown после прошлого напоминания")
                if not awaiting._ping_budget_left(conv, cfg):
                    blockers.append("бюджет напоминаний исчерпан")
                reason = "цель команде, личный пуш отсечён: " + (
                    ", ".join(blockers) or "причина не в этих предикатах")
            else:
                reason = "не цель"
            print(f"    {local:%a %H:%M}  рабочих {work:7.0f} мин  → {reason}")
            shown += 1
        if personal:
            state["count"] += 1
            state["pinged_at"] = moment
        moment += timedelta(seconds=TICK_SECONDS)
    if first_target is None:
        print("    ни на одном тике не стал целью даже для команды")

    # Второй проход — календарно, как сейчас на проде: когда ушёл пуш и по какому
    # ожиданию. Если раньше последнего сообщения, значит «потеря» мнимая: диалог
    # получил напоминание по ДРУГОМУ, более раннему ожиданию клиента.
    print("  как было бы календарно (как сейчас на проде):")
    state = {"count": 0, "pinged_at": None}
    cursor, pushes = 0, []
    conv = None
    moment = events[0][0]
    while moment <= end:
        while cursor < len(events) and events[cursor][0] <= moment:
            stamp, sender, text = events[cursor]
            conv = SimpleNamespace(**base, last_message_at=stamp, last_sender=sender,
                                   last_text=text[:200], awaiting_ping_count=0,
                                   awaiting_pinged_at=None)
            cursor += 1
        if conv is not None:
            conv.awaiting_ping_count = state["count"]
            conv.awaiting_pinged_at = state["pinged_at"]
            if awaiting.select_telegram_targets([conv], moment, cfg, working_hours=False):
                state["count"] += 1
                state["pinged_at"] = moment
                pushes.append((moment, conv.last_message_at))
        moment += timedelta(seconds=TICK_SECONDS)
    for when, about in pushes[:4]:
        same = "по ПОСЛЕДНЕМУ сообщению" if about == events[-1][0] else "по более раннему ожиданию"
        print(f"    пуш {(when + BISHKEK):%a %d.%m %H:%M} — {same} "
              f"(реплика {(about + BISHKEK):%a %d.%m %H:%M})")
    if not pushes:
        print("    календарно пушей тоже не было")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=21, help="сколько суток истории брать")
    ap.add_argument("--threshold", type=int, default=None,
                    help="порог ожидания, минут (по умолчанию из настроек)")
    ap.add_argument("--max-age-hours", type=int, default=None,
                    help="календарный потолок свежести личного пуша, часов")
    ap.add_argument("--max-age-working-hours", type=int, default=None,
                    help="рабочий потолок свежести, часов (при включённом окне)")
    ap.add_argument("--explain-lost", action="store_true",
                    help="разобрать по тикам первый диалог, потерявший напоминание: "
                         "где он проходил порог и где его отсекло")
    ap.add_argument("--no-cap", action="store_true",
                    help="снять лимит TELEGRAM_CAP на тик — проверка, не вытесняет ли "
                         "очередь дольше всех ждущих (сортировка идёт по свежести)")
    args = ap.parse_args()

    if args.no_cap:
        from app.core import awaiting as _awaiting
        _awaiting.TELEGRAM_CAP = 10 ** 6
        print("ВНИМАНИЕ: лимит пушей на тик снят — это диагностический прогон\n")

    from app.config import settings
    cfg = ReplayCfg(
        alert_awaiting_minutes=(args.threshold if args.threshold is not None
                                else settings.alert_awaiting_minutes),
        alert_cooldown_minutes=settings.alert_cooldown_minutes,
        awaiting_max_age_hours=(args.max_age_hours if args.max_age_hours is not None
                                else settings.awaiting_max_age_hours),
        awaiting_max_age_working_hours=(
            args.max_age_working_hours if args.max_age_working_hours is not None
            else settings.awaiting_max_age_working_hours),
        awaiting_max_pings=settings.awaiting_max_pings,
        awaiting_telegram_enabled=True,
    )

    dialogs, first, last = asyncio.run(load(args.days))
    if not dialogs:
        print(f"за {args.days} суток истории сообщений не нашлось")
        return 1
    span = max((last - first).total_seconds() / 86400, 1e-9)

    print(f"история: {span:.1f} суток, диалогов с сообщениями {len(dialogs)}")
    print(f"порог {cfg.alert_awaiting_minutes} мин, cooldown {cfg.alert_cooldown_minutes} мин, "
          f"бюджет {cfg.awaiting_max_pings} напоминаний")
    print(f"потолок: календарный {cfg.awaiting_max_age_hours} ч / "
          f"рабочий {cfg.awaiting_max_age_working_hours} ч\n")

    off = replay(dialogs, cfg, working_hours=False)
    on = replay(dialogs, cfg, working_hours=True)

    print(f"{'':28} {'календарно (как сейчас)':>24} {'рабочее окно (флаг ON)':>24}")
    for label, key in (("алертов команде, всего", "team"),
                       ("личных пушей, всего", "personal")):
        print(f"{label:28} {off[key]:>24} {on[key]:>24}")
    print(f"{'личных пушей в сутки':28} {off['personal']/span:>24.1f} "
          f"{on['personal']/span:>24.1f}")
    print(f"{'диалогов с пушем':28} {len(off['pinged']):>24} {len(on['pinged']):>24}")

    # Главный вопрос калибровки: кого включение флага лишает напоминания совсем.
    lost = off["pinged"] - on["pinged"]
    gained = on["pinged"] - off["pinged"]
    print(f"\nперестанут получать напоминание вовсе: {len(lost)} диалогов")
    print(f"начнут получать (сейчас теряются):     {len(gained)} диалогов")

    # Разбор потерь: «не хватило рабочего времени до конца окна» — это артефакт
    # границы прогона (в жизни пуш уйдёт в рабочие часы), а «рабочих минут много, а
    # пуша нет» — настоящая потеря, и её надо объяснять порогом или потолком.
    if lost:
        edge, real = [], []
        for user_id in lost:
            info = on["tail"].get(user_id)
            if info is None:
                continue
            (edge if info["work_min"] < cfg.alert_awaiting_minutes else real).append(info)
        print(f"  из них упёрлись в границу окна (рабочих минут < порога): {len(edge)}")
        print(f"  настоящие потери (рабочих минут хватало, пуша нет):      {len(real)}")
        for info in sorted(edge + real, key=lambda x: x["work_min"])[:10]:
            local = info["last"] + BISHKEK
            print(f"    канал {info['bot']:<16} последнее {local:%a %H:%M} "
                  f"календарно {info['calendar_min']:7.0f} мин, рабочих {info['work_min']:6.0f}")

    if args.explain_lost and lost:
        explain(dialogs, sorted(lost)[0], cfg)

    night = {h: n for h, n in sorted(off["by_hour"].items()) if h < 9 or h >= 19}
    night_on = {h: n for h, n in sorted(on["by_hour"].items()) if h < 9 or h >= 19}
    print(f"\nпушей вне окна 9–19 (время Бишкека): календарно {sum(night.values())}, "
          f"с флагом {sum(night_on.values())}")
    if night_on:
        print(f"  остаток по часам с флагом: {night_on}")
        print("  (визы открываются в 10:00 — пуши в 9:xx по визовым каналам тоже вне приёма)")
    print("\nНАПОМИНАНИЕ ОБ ОГРАНИЧЕНИИ: stage/intercepted/outcome взяты текущие, "
          "их истории в базе нет — это оценка сверху, а не точный повтор прошлого.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
