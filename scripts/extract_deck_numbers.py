"""Экстрактор РЕАЛЬНЫХ чисел для презентации «Дырявое ведро».

Запускать НА ПРОДЕ (там Postgres с боевыми диалогами). Переиспользует движок
`compute_analytics` из админки + добивает метрики, которых там нет для деки:
ночная доля, мёртвые лиды, реальный поток лидов/день, ad-vs-organic, конверсия
по каждой воронке. Ничего не пишет — только читает и печатает сводку.

Как запускать на VPS (в каталоге проекта /root/frunze-travel):
    docker compose -f docker-compose.vps.yml --env-file prod.env \
        run --rm bot python -m scripts.extract_deck_numbers

(или `exec bot ...`, если контейнер уже поднят). Вывод — скопировать и прислать.
"""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.integrations.panel.analytics import (
    _conversation_created_at,
    _effective_outcome,
    compute_analytics,
)
from app.integrations.panel.store import get_conversation_store

BISHKEK = timezone(timedelta(hours=6))          # UTC+6, без перехода на летнее
NIGHT_START, NIGHT_END = 22, 8                  # ночь: 22:00–08:00 по Бишкеку
GO_LIVE = datetime(2026, 7, 1, tzinfo=timezone.utc)  # бой с 01.07 (диалоги до — обкатка)
DEAD_STALE_HOURS = 48                           # «мёртвый» = без движения дольше 48 ч


def _aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _is_night(dt) -> bool:
    h = _aware(dt).astimezone(BISHKEK).hour
    return h >= NIGHT_START or h < NIGHT_END


def _first_client_at(conv):
    times = [_aware(m.created_at) for m in conv.messages
             if getattr(m, "sender", "") == "client" and _aware(m.created_at)]
    return min(times) if times else None


def _has_human(conv) -> bool:
    return (any(m.sender == "manager" for m in conv.messages)
            or getattr(conv, "intercepted", False)
            or bool(getattr(conv, "assigned_to", "")))


def _fmt(n, d):
    return f"{round(100 * n / d)}%" if d else "—"


async def main() -> None:
    store = get_conversation_store()
    convs = await store.all_conversations()
    now = datetime.now(timezone.utc)

    # только боевой период (с 01.07) — до этого выключения/обкатка завышают
    live = [c for c in convs if (_conversation_created_at(c) or now) >= GO_LIVE]

    print("=" * 62)
    print("  РЕАЛЬНЫЕ ЧИСЛА ДЛЯ ДЕКИ «ДЫРЯВОЕ ВЕДРО»")
    print(f"  всего диалогов в базе: {len(convs)} | боевых (с 01.07): {len(live)}")
    print(f"  снято: {now.astimezone(BISHKEK):%Y-%m-%d %H:%M} Бишкек")
    print("=" * 62)

    # --- 1. Реальный поток лидов/день (по дате создания) ---
    per_day: Counter = Counter()
    for c in live:
        ca = _conversation_created_at(c)
        if ca:
            per_day[ca.astimezone(BISHKEK).date()] += 1
    if per_day:
        vals = sorted(per_day.values())
        med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
        print("\n[1] ПОТОК ЛИДОВ/ДЕНЬ (новые диалоги, боевой период)")
        print(f"    дней с активностью: {len(per_day)}")
        print(f"    медиана: {med:.0f}/день | пик: {max(vals)} | минимум: {min(vals)}")
        print(f"    среднее: {sum(vals)/len(vals):.1f}/день")

    # --- 2. Источник: реклама vs органика (CTWA-захват) ---
    src = Counter(("ad" if c.source == "ad" else "post" if c.source == "post"
                   else "organic/unknown") for c in live)
    print("\n[2] ИСТОЧНИК ЛИДА (Click-to-WhatsApp Ads capture)")
    for k, v in src.most_common():
        print(f"    {k:20s}: {v}  ({_fmt(v, len(live))})")

    # --- 3. Воронки: конверсия по каждой (funnel × исход) ---
    funnel_out: dict[str, Counter] = defaultdict(Counter)
    for c in live:
        funnel_out[c.funnel or "—"][_effective_outcome(c)] += 1
    print("\n[3] КОНВЕРСИЯ ПО ВОРОНКАМ (won / всего, исход = ручной+ИИ)")
    for f, cnt in sorted(funnel_out.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(cnt.values())
        won = cnt.get("won", 0)
        print(f"    {f:10s}: всего {tot:4d} | won {won:3d} ({_fmt(won, tot)}) | "
              f"lost {cnt.get('lost',0)} | in_progress {cnt.get('in_progress',0)}")

    # --- 4. Ночная доля (обоснование «ночного диспетчера») ---
    night_first = sum(1 for c in live if (t := _first_client_at(c)) and _is_night(t))
    night_msgs = sum(1 for c in live for m in c.messages
                     if getattr(m, "sender", "") == "client" and _aware(m.created_at) and _is_night(m.created_at))
    total_client_msgs = sum(1 for c in live for m in c.messages if getattr(m, "sender", "") == "client")
    print("\n[4] НОЧЬ (22:00–08:00 Бишкек)")
    print(f"    диалогов, начатых НОЧЬЮ: {night_first} ({_fmt(night_first, len(live))})")
    print(f"    сообщений клиентов ночью: {night_msgs} ({_fmt(night_msgs, total_client_msgs)})")

    # --- 5. Мёртвые лиды (ждут нас, без человека, застой) ---
    dead = [c for c in live
            if not c.archived and not _has_human(c)
            and _effective_outcome(c) == "in_progress"
            and _aware(c.last_message_at)
            and (now - _aware(c.last_message_at)) >= timedelta(hours=DEAD_STALE_HOURS)]
    print(f"\n[5] МЁРТВЫЕ ЛИДЫ (без человека, застой >{DEAD_STALE_HOURS}ч, не архив)")
    print(f"    всего: {len(dead)}")
    dead_funnel = Counter(c.funnel or "—" for c in dead)
    for f, v in dead_funnel.most_common():
        print(f"      {f:10s}: {v}")

    # --- 6. Готовность «Покупатели сегодня» (readiness-тиры) ---
    tiers = Counter(c.readiness_tier or "не считался" for c in live)
    print("\n[6] READINESS-ТИРЫ (мотор «Покупатели сегодня»)")
    for k in ("green", "warm", "noise", "insufficient", "не считался"):
        if tiers.get(k):
            print(f"    {k:14s}: {tiers[k]}  ({_fmt(tiers[k], len(live))})")

    # --- 7. Движок админки: containment, медиана ответа, разрез по менеджерам ---
    a = compute_analytics(live, period="all", now=now)
    print("\n[7] ОБРАБОТКА (из compute_analytics, боевой период)")
    print(f"    containment (бот сам, без человека): {a['containment_rate']}%  ({a['contained']}/{a['total']})")
    print(f"    медиана времени ответа менеджера: {a['median_response_min']} мин")
    print(f"    медиана времени до перехвата: {a['median_handoff_min']} мин")
    print(f"    исходы всего: {a['outcomes']}")
    print("    по менеджерам (диалогов | win-rate | доля | медиана ответа):")
    for mgr, row in a["by_manager"].items():
        print(f"      {mgr:14s}: {row['handled']:4d} | {row['won_rate']:3d}% | "
              f"{row['share']:3d}% | {row['median_response_min']} мин")
    print("    причины хендоффа:", a["handoff_reasons"])

    print("\n" + "=" * 62)
    print("  Скопируй ВЕСЬ вывод и пришли — подставлю в деку.")
    print("=" * 62)


if __name__ == "__main__":
    asyncio.run(main())
