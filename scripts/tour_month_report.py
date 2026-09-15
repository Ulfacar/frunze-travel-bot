#!/usr/bin/env python
"""Месячный отчёт по турам — то, что можно показать заказчику.

Зачем существует. Продажи в CRM не заносятся с 13.06: у таргетологов 158 продаж, в
портале 7 сделок. Значит отчёт обязан стоять на том, что мы меряем САМИ и не зависим от
того, нажал ли менеджер кнопку: сколько пришло лидов, как быстро им ответили, сколько
пришло ночью, сколько подборок отправлено и открыто, куда доехали карточки.

Три правила, без которых отчёт врёт:
  1. «Продано» — только ручная отметка `outcome == "won"`. Догадка ИИ (`outcome_inferred`)
     печатается отдельной строкой и словом «оценка», её нельзя складывать с фактом.
  2. Месяц — КАЛЕНДАРНЫЙ и по Бишкеку (UTC+6), а не «последние 30 дней». Все остальные
     сводки в проекте считают скользящее окно, и сравнивать их с этим отчётом нельзя.
  3. Лид месяца — по `conversations.created_at` (когда пришёл), а не по `last_message_at`
     (когда писал в последний раз): иначе июльский диалог, ответивший в сентябре, попадёт
     в оба месяца.

ТОЛЬКО ЧТЕНИЕ. Ни одной записи в базу и в портал — по проду запускать безопасно:

    docker exec -w /app frunze-travel-app-1 python scripts/tour_month_report.py
    docker exec -w /app frunze-travel-app-1 python scripts/tour_month_report.py --month 2026-08
    docker exec -w /app frunze-travel-app-1 python scripts/tour_month_report.py --no-portal
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

TOURS = ("frunze_tours", "frunze_tours_sezim", "frunze_tours_tg")
_OFFICE_STAGES = {"office", "office_consultation"}
BISHKEK = timezone(timedelta(hours=6))
# Ответственные в портале, по которым отделяем туровые карточки от визовых.
TOUR_OWNERS = {"155313": "Адеми", "155267": "Айсина", "155383": "служебный аккаунт"}
PEOPLE = dict(TOUR_OWNERS, **{"96451": "Медина", "110841": "Элиза", "1": "админ портала"})


def _month_bounds(label: str) -> tuple[datetime, datetime, str]:
    """Границы календарного месяца по Бишкеку, отданные в UTC.

    Месяц считается местным: сентябрь начинается 01.09 в 00:00 Бишкека, то есть 31.08 в
    18:00 UTC. Иначе шесть вечерних часов каждого 31-го числа уезжали бы в соседний месяц.
    """
    year, month = (int(part) for part in label.split("-"))
    start_local = datetime(year, month, 1, tzinfo=BISHKEK)
    end_local = (datetime(year + (month == 12), (month % 12) + 1, 1, tzinfo=BISHKEK))
    return (start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc),
            f"{start_local:%m.%Y}")


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def _percentile(values: list[float], q: float) -> float | None:
    """Хвост распределения. Медиана без него врёт: замер 15.09 по августу дал у менеджеров
    p50 = 3 мин при p90 = 14.6 часа — то есть каждый десятый клиент ждал больше полусуток."""
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(len(ordered) * q))], 1)


# Позже этого ответ уже не ответ: клиент ушёл, а пара «вопрос → реплика через неделю»
# только портит статистику. Замер 15.09: у бота такие выбросы дотягивались до 27 суток.
REPLY_DEADLINE_MIN = 48 * 60


def _fmt(name: str, value, width: int = 36) -> str:
    return f"  {name:<{width}} {value}"


def _delta(now: float | int | None, was: float | int | None, *, less_is_better=False) -> str:
    """Изменение к прошлому месяцу. Без прошлого месяца — пусто, а не выдуманный ноль."""
    if now is None or was is None:
        return ""
    if was == 0:
        return "  (в прошлом месяце 0)"
    diff = (now - was) / was * 100
    if round(diff) == 0:
        return "  = как в прошлом месяце"
    # Без псевдографики: отчёт читают и в Windows-консоли, где cp1251 роняет «▲» с
    # UnicodeEncodeError — вместо цифр заказчик увидел бы traceback.
    good = (diff < 0) if less_is_better else (diff > 0)
    sign = "+" if diff > 0 else "-"
    return f"  {sign}{abs(diff):.0f}% к прошлому ({'лучше' if good else 'хуже'})"


# ---------------------------------------------------------------- наша база: диалоги
async def _dialog_metrics(start: datetime, end: datetime) -> dict:
    """Лиды месяца и их исходы. Считаем по дате ПОЯВЛЕНИЯ диалога.

    Читаем таблицу напрямую, а не через `all_conversations_light`: вью диалога
    (`ConversationView`) вообще не несёт `created_at`, и когорта месяца по ней собирается
    пустой — первый прогон 15.09 дал 0 лидов там, где их 460.

    Про офис. Считаем по СТАДИИ (`office`/`office_consultation`), а не по `outcome`:
    `orchestrator._auto_outcome` пишет `outcome="office"` сам на каждом ходу из стадии, а
    ручная продажа (`won`) его затирает навсегда. То есть счётчик по `outcome` одновременно
    завышает (пишет бот, а не человек) и занижает (купивший клиент из него исчезает).
    Стадию же ставит только `runner.escalate_to_office`, и он отказывается это делать, пока
    не собраны имя клиента и время визита, — то есть это проверяемый факт из переписки.
    И всё равно это «договорились о визите», а не «пришёл»: дошёл ли человек до офиса,
    наша система не знает.
    """
    from sqlalchemy import select

    from app.integrations.crm.bitrix_pipeline import lead_field_values
    from app.integrations.crm.db import Conversation, get_sessionmaker

    out = {"leads": 0, "with_lead_card": 0, "qualified": 0, "office_agreed": 0,
           "office_invited": 0, "won": 0, "lost": 0, "unmarked": 0, "ai_won_guess": 0,
           "destinations": Counter(), "by_manager": Counter(), "unassigned": 0}
    async with get_sessionmaker()() as session:
        rows = (await session.execute(
            select(Conversation).where(Conversation.bot_id.in_(TOURS),
                                       Conversation.created_at >= start,
                                       Conversation.created_at < end))).scalars().all()
        for conv in rows:
            out["leads"] += 1
            if conv.bitrix_lead_id or "":
                out["with_lead_card"] += 1
            facts = conv.qualification or {}
            if lead_field_values(facts):
                out["qualified"] += 1
            place = str(facts.get("destination") or facts.get("country") or "").strip()
            if place:
                out["destinations"][place.title()] += 1
            if str(conv.stage or "") in _OFFICE_STAGES:
                visit = str(facts.get("visit_time") or facts.get("office_visit") or "").strip()
                out["office_agreed" if visit else "office_invited"] += 1
            outcome = str(conv.outcome or "")
            if outcome == "won":
                out["won"] += 1
            elif outcome == "lost":
                out["lost"] += 1
            else:
                out["unmarked"] += 1
            # Догадка ИИ живёт отдельно от факта и в «продано» не входит НИКОГДА.
            if str(conv.outcome_inferred or "") == "won" and outcome != "won":
                out["ai_won_guess"] += 1
            owner = str(conv.assigned_to or "").strip()
            if owner:
                out["by_manager"][owner] += 1
            else:
                out["unassigned"] += 1
    return out


# ------------------------------------------------------------- наша база: сообщения
async def _message_metrics(start: datetime, end: datetime) -> dict:
    """Скорость ответа и ночной поток — по сообщениям месяца, одним запросом.

    Медиану считаем по паре «сообщение клиента → первый ответ после него». Отдельно для
    бота и для менеджера: у заказчика вопрос всегда один — «а живой человек быстрее?».
    """
    from sqlalchemy import select

    from app.integrations.crm.db import Conversation, ConvMessage, get_sessionmaker

    rows = []
    async with get_sessionmaker()() as session:
        result = await session.execute(
            select(ConvMessage.conversation_id, ConvMessage.sender, ConvMessage.created_at,
                   ConvMessage.status)
            .join(Conversation, Conversation.id == ConvMessage.conversation_id)
            .where(Conversation.bot_id.in_(TOURS),
                   ConvMessage.created_at >= start, ConvMessage.created_at < end)
            .order_by(ConvMessage.conversation_id, ConvMessage.created_at))
        rows = result.all()

    night = total_client = 0
    bot_gaps: list[float] = []
    manager_gaps: list[float] = []
    # Очередь ожидания у бота и у менеджера — РАЗДЕЛЬНАЯ, и это принципиально. С одной
    # общей очередью ответ бота (он почти всегда первый) закрывал бы ожидание клиента, и
    # в медиану менеджера попадали бы только те редкие случаи, где человек успел раньше
    # бота. Первый прогон 15.09 так и показал «менеджер отвечает за 2 минуты» при том,
    # что живой замер медианы до бота давал 3 часа.
    pending_bot: dict[int, datetime] = {}
    pending_manager: dict[int, datetime] = {}
    dialogs_with_client: set[int] = set()
    dialogs_with_manager: set[int] = set()
    stale_manager = 0
    for conv_id, sender, created, status in rows:
        created = _aware(created)
        if sender == "client":
            total_client += 1
            dialogs_with_client.add(conv_id)
            local_hour = (created.astimezone(BISHKEK)).hour
            if local_hour >= 22 or local_hour < 8:
                night += 1
            pending_bot.setdefault(conv_id, created)
            pending_manager.setdefault(conv_id, created)
            continue
        if sender == "manager":
            dialogs_with_manager.add(conv_id)
        if status == "failed":
            continue                      # не доставлено — это не ответ клиенту
        queue = pending_bot if sender == "bot" else pending_manager
        asked = queue.pop(conv_id, None)
        if asked is None:
            continue                      # ответ без вопроса (рассылка, дожим) — не пауза
        minutes = (created - asked).total_seconds() / 60
        if minutes < 0:
            continue
        if minutes > REPLY_DEADLINE_MIN:
            if sender == "manager":
                stale_manager += 1        # ответили, но через двое суток — это не ответ
            continue
        (bot_gaps if sender == "bot" else manager_gaps).append(minutes)
    # Покрытие обязательно: менеджеры отвечают и с личного телефона, мимо нас (замер по
    # визам: 385 из 681 диалога без единой нашей реплики менеджера). Без этой строки
    # «медиана ответа 2 минуты» описывает не команду, а те диалоги, что видит система.
    seen = len(dialogs_with_client)

    def _fast_share(values: list[float]) -> float:
        return round(sum(1 for v in values if v <= 15) * 100 / len(values), 1) if values else 0.0

    return {"client_messages": total_client, "night": night,
            "night_pct": round(night * 100 / total_client, 1) if total_client else 0.0,
            "bot_median_min": _median(bot_gaps), "bot_answers": len(bot_gaps),
            "bot_p90_min": _percentile(bot_gaps, 0.9), "bot_fast_pct": _fast_share(bot_gaps),
            "manager_median_min": _median(manager_gaps), "manager_answers": len(manager_gaps),
            "manager_p90_min": _percentile(manager_gaps, 0.9),
            "manager_fast_pct": _fast_share(manager_gaps),
            "manager_stale": stale_manager,
            "dialogs_seen": seen, "dialogs_with_manager": len(dialogs_with_manager),
            "manager_coverage_pct": (round(len(dialogs_with_manager) * 100 / seen, 1)
                                     if seen else 0.0)}


# ------------------------------------------------------------------ подборки туров
async def _offer_metrics(start: datetime, end: datetime) -> dict:
    """Сколько подборок отправлено и сколько открыто. Считает СУБД, не память."""
    from sqlalchemy import func, select

    from app.integrations.crm.db import TourOffer, get_sessionmaker

    async with get_sessionmaker()() as session:
        row = (await session.execute(
            select(func.count(TourOffer.slug), func.coalesce(func.sum(TourOffer.views), 0))
            .where(TourOffer.created_at >= start, TourOffer.created_at < end))).one()
        opened = (await session.execute(
            select(func.count(TourOffer.slug))
            .where(TourOffer.created_at >= start, TourOffer.created_at < end,
                   TourOffer.views > 0))).scalar_one()
    sent, views = int(row[0]), int(row[1])
    return {"sent": sent, "views": views, "opened": opened,
            "opened_pct": round(opened * 100 / sent, 1) if sent else 0.0}


# ------------------------------------------------------------------------- портал
async def _portal_metrics(start: datetime, end: datetime) -> dict:
    """Куда доехали карточки месяца по стадиям портала. Только чтение."""
    from app.integrations.crm.bitrix24 import Bitrix24Crm

    client = Bitrix24Crm()
    names: dict[str, str] = {}
    try:
        status = await client._call("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}})
        for item in (status.get("result") or []):
            names[str(item.get("STATUS_ID"))] = str(item.get("NAME") or "")
    except Exception as exc:  # noqa: BLE001 — отчёт полезен и без названий стадий
        print(f"  (названия стадий не прочитаны: {exc})")

    stages: Counter = Counter()
    page_start = 0
    fmt = "%Y-%m-%dT%H:%M:%S"
    while True:
        page = await client._call("crm.lead.list", {
            "filter": {">=DATE_CREATE": start.astimezone(BISHKEK).strftime(fmt),
                       "<DATE_CREATE": end.astimezone(BISHKEK).strftime(fmt)},
            "select": ["ID", "STATUS_ID", "ASSIGNED_BY_ID"],
            "start": page_start,
        })
        items = page.get("result") or []
        for lead in items:
            if str(lead.get("ASSIGNED_BY_ID") or "?") not in TOUR_OWNERS:
                continue                  # визовые карточки в туровый отчёт не входят
            stages[str(lead.get("STATUS_ID") or "?")] += 1
        nxt = page.get("next")
        if nxt is None or not items:
            break
        page_start = nxt
        if page_start > 5000:             # предохранитель: портал не листаем бесконечно
            break
    return {"stages": stages, "names": names, "total": sum(stages.values())}


async def collect(label: str, *, with_portal: bool) -> dict:
    start, end, title = _month_bounds(label)
    data = {"label": label, "title": title, "start": start, "end": end}
    data["dialogs"] = await _dialog_metrics(start, end)
    data["messages"] = await _message_metrics(start, end)
    data["offers"] = await _offer_metrics(start, end)
    data["portal"] = await _portal_metrics(start, end) if with_portal else None
    return data


def _minutes(value: float | None) -> str:
    if value is None:
        return "нет данных"
    if value < 1:
        return f"{value * 60:.0f} сек"     # «0 мин» выглядит как отсутствие данных
    if value < 60:
        return f"{value:.0f} мин"
    return f"{value / 60:.1f} ч"


def render(cur: dict, prev: dict | None) -> None:
    d, m, o = cur["dialogs"], cur["messages"], cur["offers"]
    pd = prev["dialogs"] if prev else {}
    pm = prev["messages"] if prev else {}
    po = prev["offers"] if prev else {}

    print(f"\n=== ТУРЫ ЗА {cur['title']} ===")
    print(f"    снято {datetime.now(BISHKEK):%d.%m.%Y %H:%M} по Бишкеку"
          + (f", сравнение с {prev['title']}" if prev else ""))

    print("\nСКОЛЬКО ПРИШЛО")
    print(_fmt("новых обращений", f"{d['leads']}{_delta(d['leads'], pd.get('leads'))}"))
    print(_fmt("карточка в Битриксе заведена", d["with_lead_card"]))
    print(_fmt("рассказали, куда и когда хотят", f"{d['qualified']}"
               f"{_delta(d['qualified'], pd.get('qualified'))}"))
    print(_fmt("писали ночью (22:00–08:00)",
               f"{m['night']} сообщений клиентов = {m['night_pct']}% потока"
               f"{_delta(m['night_pct'], pm.get('night_pct'))}"))

    print("\nКАК БЫСТРО ОТВЕЧАЛИ")
    print(_fmt("бот: обычно / каждый 10-й ждал",
               f"{_minutes(m['bot_median_min'])} / {_minutes(m['bot_p90_min'])}"
               f"   ответил за 15 мин: {m['bot_fast_pct']}%"))
    print(_fmt("менеджер: обычно / каждый 10-й ждал",
               f"{_minutes(m['manager_median_min'])} / {_minutes(m['manager_p90_min'])}"
               f"   ответил за 15 мин: {m['manager_fast_pct']}%"
               + _delta(m["manager_fast_pct"], pm.get("manager_fast_pct"))))
    if m["manager_stale"]:
        print(_fmt("ответ пришёл позже двух суток",
                   f"{m['manager_stale']} раз — в среднее время не считали"))
    print(_fmt("считано по диалогам",
               f"{m['dialogs_with_manager']} из {m['dialogs_seen']} "
               f"({m['manager_coverage_pct']}%) — в остальных менеджер писал мимо системы"))

    print("\nПОДБОРКИ ТУРОВ")
    print(_fmt("отправлено клиентам", f"{o['sent']}{_delta(o['sent'], po.get('sent'))}"))
    print(_fmt("клиент открыл", f"{o['opened']} ({o['opened_pct']}%)"
               + _delta(o["opened_pct"], po.get("opened_pct"))))
    print(_fmt("всего просмотров", o["views"]))

    print("\nЗАПИСИ В ОФИС")
    print(_fmt("договорились о визите (имя и время)",
               f"{d['office_agreed']}{_delta(d['office_agreed'], pd.get('office_agreed'))}"))
    print(_fmt("приглашены, время не подтвердили", d["office_invited"]))
    print("  ! «договорились» — это не «пришёл»: дошёл ли клиент до офиса, система не знает.")

    print("\nЧЕМ ЗАКОНЧИЛОСЬ (ручные отметки менеджеров)")
    print(_fmt("продано", f"{d['won']}{_delta(d['won'], pd.get('won'))}"))
    print(_fmt("не сложилось", d["lost"]))
    print(_fmt("без отметки", f"{d['unmarked']} из {d['leads']}"))
    print("  ! отметку ставит менеджер вручную; «без отметки» — это не «не купили»,")
    print("    а «мы не знаем». Продажи в CRM не заносятся с 13.06, сверить их нечем.")
    if d["ai_won_guess"]:
        print(_fmt("оценка ИИ «похоже на продажу»",
                   f"{d['ai_won_guess']} — НЕ подтверждено, в «продано» не входит"))

    if d["destinations"]:
        top = ", ".join(f"{name} {count}" for name, count in d["destinations"].most_common(5))
        print("\nКУДА ХОТЯТ")
        print(f"  {top}")

    if d["by_manager"]:
        print("\nНАГРУЗКА ПО МЕНЕДЖЕРАМ")
        for login, count in d["by_manager"].most_common():
            print(_fmt(login, count))
        if d["unassigned"]:
            print(_fmt("без владельца", d["unassigned"]))

    portal = cur.get("portal")
    if portal and portal["total"]:
        print(f"\nКАРТОЧКИ В ПОРТАЛЕ: {portal['total']}")
        for status_id, count in portal["stages"].most_common():
            title = portal["names"].get(status_id, status_id)
            share = f"{count * 100 // portal['total']}%"
            print(_fmt(f"{title}", f"{count:4}  {share:>4}", 38))
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Месячный отчёт по турам (только чтение)")
    parser.add_argument("--month", default=datetime.now(BISHKEK).strftime("%Y-%m"),
                        help="месяц в виде 2026-09 (по умолчанию текущий)")
    parser.add_argument("--no-compare", action="store_true",
                        help="не считать предыдущий месяц")
    parser.add_argument("--no-portal", action="store_true",
                        help="не ходить в Битрикс, считать только по нашей базе")
    args = parser.parse_args()

    cur = await collect(args.month, with_portal=not args.no_portal)
    prev = None
    if not args.no_compare:
        year, month = (int(p) for p in args.month.split("-"))
        prev_label = f"{year - (month == 1)}-{12 if month == 1 else month - 1:02d}"
        prev = await collect(prev_label, with_portal=False)
    render(cur, prev)


if __name__ == "__main__":
    asyncio.run(main())
