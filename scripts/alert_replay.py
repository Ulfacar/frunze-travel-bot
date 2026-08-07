#!/usr/bin/env python
"""Прогон сторожа тишины по реальной истории входящих — ДО выкатки.

Зачем этот скрипт существует. 06-07.08.2026 детектор, который пишет владельцу в Telegram,
выкатывался трижды, и трижды его пороги были взяты из рассуждения, а не из замера:

    порог 90/300 (выкатан 06.08)  — обещали «редко», на деле 5.3 ложных инцидента в сутки
    порог 180/420 (выкатан 07.08) — обещали «0-1 в сутки», на деле 2.5
    порог 720/720                 — 0.8, и все инциденты длиннее 12 часов

Проверкой каждый раз работал прод, то есть живой человек, которому это приходило.
Тесты были зелёные все три раза: они проверяли ЛОГИКУ («сработает ли на 12 часах»),
а не КАЛИБРОВКУ («как часто сработает на нашем трафике»). Разница между этими двумя
вопросами и есть весь сегодняшний разбор.

Ключевая деталь: скрипт зовёт НАСТОЯЩУЮ `channel_heartbeat.decide()`, а не свою копию
логики. Копия разошлась бы с кодом на второй правке и снова врала бы.

Про ошибку в первом замере — она стоила отдельной выкатки. Я считал паузы между
входящими и относил каждую к «дню» или «ночи» по часу прихода СЛЕДУЮЩЕГО сообщения.
Сторож так не судит: он проверяет на каждом тике, и длинная ночная пауза, кончающаяся
в 09:25, почти всю жизнь проверяется ДНЕВНЫМ порогом. Поэтому здесь — тик за тиком.

Использование:

    # выгрузить историю с прода (bot_id,unixtime)
    ssh root@<прод> "docker exec frunze-travel-db-1 psql -U postgres -d frunze -t -A -F, -c \\
      \\"select c.bot_id, extract(epoch from m.created_at)::bigint
         from messages m join conversations c on c.id=m.conversation_id
         where m.sender='client' and m.created_at > now() - interval '21 days'
         order by 2;\\"" > inbound.csv

    python scripts/alert_replay.py inbound.csv                  # текущие настройки
    python scripts/alert_replay.py inbound.csv --day 180 --night 420   # что было бы
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

BISHKEK_UTC_OFFSET = 6
TICK_SECONDS = 300


class ReplayCfg:
    """Настройки прогона: те же имена полей, что читает decide()."""

    def __init__(self, day, night, cooldown, quiet_from, quiet_to):
        self.channel_heartbeat_enabled = True
        self.channel_silence_minutes = day
        self.channel_silence_night_minutes = night
        self.channel_alert_cooldown_minutes = cooldown
        self.channel_heartbeat_quiet_from = quiet_from
        self.channel_heartbeat_quiet_to = quiet_to


def load(path: str) -> dict[str, list[int]]:
    rows: dict[str, list[int]] = collections.defaultdict(list)
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "," not in line:
            continue
        bot_id, stamp = line.rsplit(",", 1)
        try:
            rows[bot_id.strip()].append(int(stamp))
        except ValueError:
            continue
    return {bot_id: sorted(stamps) for bot_id, stamps in rows.items() if stamps}


def replay(history: dict[str, list[int]], cfg) -> dict[str, dict]:
    """Прокрутить историю тик за тиком через настоящую decide(). Один канал за раз:
    каналы независимы, а раздельный прогон не даёт защёлке одного влиять на другой."""
    from app.core.channel_heartbeat import decide

    out: dict[str, dict] = {}
    for bot_id, stamps in history.items():
        state: dict = {}
        messages, incidents = 0, 0
        firing = False
        idx, last_seen = 0, stamps[0]
        moment = stamps[0]
        while moment <= stamps[-1]:
            while idx < len(stamps) and stamps[idx] <= moment:
                last_seen = stamps[idx]
                idx += 1
            hour = ((moment + BISHKEK_UTC_OFFSET * 3600) // 3600) % 24
            alerts = decide(moment, {bot_id: last_seen}, state, cfg, bishkek_hour=hour)
            if alerts:
                messages += len(alerts)
                if not firing:
                    incidents += 1
                firing = True
            elif f"alerted:{bot_id}" not in state:
                firing = False
            moment += TICK_SECONDS
        days = max((stamps[-1] - stamps[0]) / 86400, 1e-9)
        out[bot_id] = {"messages": messages, "incidents": incidents, "days": days}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("history", help="CSV: bot_id,unixtime — по строке на входящее")
    ap.add_argument("--day", type=int, default=None, help="порог днём, минут")
    ap.add_argument("--night", type=int, default=None, help="порог ночью, минут")
    ap.add_argument("--cooldown", type=int, default=None, help="пауза между повторами, минут")
    args = ap.parse_args()

    from app.config import settings
    cfg = ReplayCfg(
        day=args.day if args.day is not None else settings.channel_silence_minutes,
        night=args.night if args.night is not None else settings.channel_silence_night_minutes,
        cooldown=(args.cooldown if args.cooldown is not None
                  else settings.channel_alert_cooldown_minutes),
        quiet_from=settings.channel_heartbeat_quiet_from,
        quiet_to=settings.channel_heartbeat_quiet_to,
    )

    history = load(args.history)
    if not history:
        print(f"в {args.history} не нашлось ни одной строки вида bot_id,unixtime")
        return 1

    result = replay(history, cfg)
    days = max(r["days"] for r in result.values())
    print(f"пороги: день {cfg.channel_silence_minutes} мин / ночь "
          f"{cfg.channel_silence_night_minutes} мин, повтор не чаще "
          f"{cfg.channel_alert_cooldown_minutes} мин")
    print(f"история: {days:.1f} суток, каналов {len(result)}\n")
    print(f"{'канал':<22} {'сообщений':>10} {'инцидентов':>11} {'сообщений/сут':>14}")
    print("-" * 62)
    total_messages = total_incidents = 0
    for bot_id in sorted(result):
        r = result[bot_id]
        total_messages += r["messages"]
        total_incidents += r["incidents"]
        print(f"{bot_id:<22} {r['messages']:>10} {r['incidents']:>11} "
              f"{r['messages'] / r['days']:>14.2f}")
    print("-" * 62)
    print(f"{'ИТОГО':<22} {total_messages:>10} {total_incidents:>11} "
          f"{total_messages / days:>14.2f}")
    print("\nСообщений в сутки — это сколько раз владелец получит уведомление. "
          "Больше одного-двух — сторожа отключат, и он станет хуже отсутствующего.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
