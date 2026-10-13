#!/usr/bin/env python
"""Сверка списка продаж с диалогами бота — первая честная цифра «сколько продал бот».

Зачем существует. Продажи в CRM не заносятся с 13.06 (у таргетологов 158 продаж, в портале
7 сделок), а признак оплаты есть лишь в 7 туровых чатах из 133: продажа идёт в офисе и по
телефону, переписка о ней не знает. Значит источник продаж — только список от людей
(менеджеры, Даулет, таргетологи): телефон, дата, сумма, направление. Скрипт берёт этот
список и для каждой продажи отвечает: писал ли клиент боту до покупки, дошёл ли до
менеджера, получил ли подборку, есть ли у него сделка в Битриксе.

Правила, без которых цифра врёт:
  1. Номер нормализуется тем же `normalize_phone`, что и контакты (0555…, +996 555…,
     996555… — один человек). Неразборчивый номер НЕ выбрасывается молча, а идёт отдельной
     строкой «номер не разобран»: иначе доля бота считается от меньшего знаменателя.
  2. Диалог засчитывается, только если он начался ДО продажи (с запасом в сутки: дата в
     списке без времени) и не раньше окна `--window-days`. Диалог, начавшийся после
     продажи, — это турист после покупки, а не заслуга бота; он печатается отдельно.
  3. Одна и та же продажа дважды (тот же номер и дата) считается один раз, дубль виден.

ТОЛЬКО ЧТЕНИЕ. Ни одной записи в базу и в портал. Запуск на проде (файл положить в /root,
он виден контейнеру только после копирования):

    docker cp /root/sales.csv frunze-travel-app-1:/tmp/sales.csv
    docker exec -w /app frunze-travel-app-1 python scripts/sales_reconcile.py /tmp/sales.csv
    ... --phone-col "Телефон" --date-col "Дата" --amount-col "Сумма" --dest-col "Страна"
    ... --out /tmp/sales_matched.csv      # построчный результат

CSV — в любой из кодировок utf-8 / utf-8-sig / cp1251, разделитель «;», «,» или таб.
XLSX читается, если в окружении есть openpyxl; иначе сохранить лист как CSV.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app")

BISHKEK = timezone(timedelta(hours=6))
_HANDOFF_STAGES = {"manager", "manager_handoff", "office", "office_consultation"}
# Колонки, которые угадываем сами, если имя не передали аргументом.
_GUESS = {
    "phone": ("телефон", "номер", "phone", "тел"),
    "date": ("дата", "date", "день"),
    "amount": ("сумма", "amount", "чек", "стоимость"),
    "dest": ("направление", "страна", "destination", "country", "тур"),
}


@dataclass
class Sale:
    row: int
    raw_phone: str
    phone: str                 # нормализованный; "" — не разобран
    day: date | None
    amount: str = ""
    dest: str = ""


@dataclass
class Dialog:
    conv_id: int
    phone: str
    bot_id: str
    created_at: datetime
    stage: str = ""
    intercepted: bool = False
    outcome: str = ""
    bitrix_lead_id: str = ""
    bitrix_deal_id: str = ""
    offers: int = 0


@dataclass
class Match:
    sale: Sale
    dialog: Dialog | None = None
    later_dialog: Dialog | None = None      # писал только ПОСЛЕ продажи
    duplicate: bool = False
    status: str = ""                        # bot | no_dialog | after_sale | bad_phone | bad_date

    @property
    def reached_manager(self) -> bool:
        d = self.dialog
        # `assigned_to` не признак: автоназначение ставит владельца на первом же сообщении.
        return bool(d and (d.stage in _HANDOFF_STAGES or d.intercepted))


# ------------------------------------------------------------------ разбор входа
def norm_phone(raw: str) -> str:
    """Тот же нормализатор, что у контактов; неразборчивое → "" (а не исключение)."""
    from app.domain.models import DomainError
    from app.domain.phones import normalize_phone

    raw = str(raw or "").strip()
    if raw.endswith(".0"):              # Excel хранит номер числом: 996555123456.0
        raw = raw[:-2]
    try:
        return normalize_phone(raw, assume_e164=True)
    except DomainError:
        return ""


def parse_day(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split(" ")[0].split("T")[0]
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _pick(headers: list[str], wanted: str | None, kind: str) -> str | None:
    if wanted:
        if wanted not in headers:
            raise SystemExit(f"нет колонки {wanted!r}; есть: {headers}")
        return wanted
    for h in headers:
        low = h.strip().lower()
        if any(key in low for key in _GUESS[kind]):
            return h
    return None


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        try:
            import openpyxl
        except ImportError:
            raise SystemExit("openpyxl не установлен — сохраните лист как CSV") from None
        sheet = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h or "").strip() for h in rows[0]]
        return [{h: ("" if v is None else v) for h, v in zip(headers, r)} for r in rows[1:]]
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("не удалось прочитать CSV ни в utf-8, ни в cp1251")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def load_sales(rows: list[dict], *, phone_col=None, date_col=None, amount_col=None,
               dest_col=None) -> list[Sale]:
    if not rows:
        return []
    headers = [h for h in rows[0].keys() if h is not None]
    pc = _pick(headers, phone_col, "phone")
    dc = _pick(headers, date_col, "date")
    if not pc or not dc:
        raise SystemExit(f"не нашёл колонку телефона или даты; есть: {headers}. "
                         "Укажите --phone-col и --date-col")
    ac = _pick(headers, amount_col, "amount")
    xc = _pick(headers, dest_col, "dest")
    sales = []
    for i, r in enumerate(rows, start=2):           # 1-я строка — заголовок
        raw = str(r.get(pc) or "").strip()
        if not raw and not str(r.get(dc) or "").strip():
            continue                                 # пустая строка в конце листа
        sales.append(Sale(row=i, raw_phone=raw, phone=norm_phone(raw), day=parse_day(r.get(dc)),
                          amount=str(r.get(ac) or "").strip() if ac else "",
                          dest=str(r.get(xc) or "").strip() if xc else ""))
    return sales


# ------------------------------------------------------------------ сопоставление
def _local_day(dt: datetime) -> date:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BISHKEK).date()


def reconcile(sales: list[Sale], dialogs: list[Dialog], *, window_days: int = 120) -> list[Match]:
    by_phone: dict[str, list[Dialog]] = {}
    for d in dialogs:
        if d.phone:
            by_phone.setdefault(d.phone, []).append(d)
    seen: set[tuple[str, date | None]] = set()
    out: list[Match] = []
    for s in sales:
        m = Match(sale=s)
        out.append(m)
        if not s.phone:
            m.status = "bad_phone"
            continue
        if s.day is None:
            m.status = "bad_date"
            continue
        key = (s.phone, s.day)
        m.duplicate = key in seen
        seen.add(key)
        # Дата в списке без времени: диалог того же дня (и следующего — поправка на
        # часовой пояс и опоздавшую запись) ещё считается «до продажи».
        latest_ok = s.day + timedelta(days=1)
        earliest_ok = s.day - timedelta(days=window_days)
        before, after = [], []
        for d in by_phone.get(s.phone, []):
            day = _local_day(d.created_at)
            if earliest_ok <= day <= latest_ok:
                before.append(d)
            elif day > latest_ok:
                after.append(d)
        if before:
            # Если у клиента несколько диалогов (два бота) — берём тот, что ближе к
            # продаже и дальше всех прошёл: он и есть путь к покупке.
            before.sort(key=lambda d: (d.stage in _HANDOFF_STAGES or d.intercepted,
                                       d.offers > 0, d.created_at))
            m.dialog = before[-1]
            m.status = "bot"
        elif after:
            m.later_dialog = min(after, key=lambda d: d.created_at)
            m.status = "after_sale"
        else:
            m.status = "no_dialog"
    return out


def _amount(text: str) -> float | None:
    cleaned = "".join(ch for ch in str(text) if ch.isdigit() or ch in ".,").replace(",", ".")
    if cleaned.count(".") > 1:              # 1.250.000 — точки как разделители тысяч
        cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def summarize(matches: list[Match]) -> dict:
    unique = [m for m in matches if not m.duplicate]
    s = {
        "rows": len(matches),
        "duplicates": sum(m.duplicate for m in matches),
        "sales": len(unique),
        "bad_phone": sum(m.status == "bad_phone" for m in unique),
        "bad_date": sum(m.status == "bad_date" for m in unique),
        "via_bot": sum(m.status == "bot" for m in unique),
        "after_sale": sum(m.status == "after_sale" for m in unique),
        "no_dialog": sum(m.status == "no_dialog" for m in unique),
        "reached_manager": sum(m.reached_manager for m in unique),
        "got_offer": sum(bool(m.dialog and m.dialog.offers) for m in unique),
        "bitrix_lead": sum(bool(m.dialog and m.dialog.bitrix_lead_id) for m in unique),
        "bitrix_deal": sum(bool(m.dialog and m.dialog.bitrix_deal_id) for m in unique),
        "marked_won": sum(bool(m.dialog and m.dialog.outcome == "won") for m in unique),
    }
    amounts = [(_amount(m.sale.amount), m.status) for m in unique]
    s["amount_total"] = sum(a for a, _ in amounts if a)
    s["amount_via_bot"] = sum(a for a, st in amounts if a and st == "bot")
    return s


def render(summary: dict) -> str:
    n = summary["sales"]
    checkable = n - summary["bad_phone"] - summary["bad_date"]

    def pct(x: int, base: int) -> str:
        return f"{x} ({x * 100 / base:.0f}%)" if base else str(x)

    lines = [
        "Сверка продаж с диалогами бота",
        f"  строк в списке                    {summary['rows']}"
        + (f" (дублей {summary['duplicates']}, посчитаны один раз)" if summary["duplicates"] else ""),
        f"  продаж                            {n}",
        f"    номер не разобран               {summary['bad_phone']}",
        f"    дата не разобрана               {summary['bad_date']}",
        f"  проверяемых                       {checkable}",
        f"    писали боту ДО покупки          {pct(summary['via_bot'], checkable)}",
        f"      из них дошли до менеджера     {summary['reached_manager']}",
        f"      получили подборку /t/         {summary['got_offer']}",
        f"      есть лид в Битриксе           {summary['bitrix_lead']}",
        f"      есть сделка в Битриксе        {summary['bitrix_deal']}",
        f"      отмечены у нас «продано»      {summary['marked_won']}",
        f"    писали только ПОСЛЕ покупки     {summary['after_sale']}",
        f"    с ботом не писали               {summary['no_dialog']}",
    ]
    if summary["amount_total"]:
        lines.append(f"  сумма продаж                      {summary['amount_total']:,.0f}".replace(",", " "))
        lines.append(f"    из них через бота               {summary['amount_via_bot']:,.0f}".replace(",", " "))
    lines.append("")
    lines.append("«Писали боту до покупки» — это касание, а не доказательство, что продал бот:")
    lines.append("клиент мог прийти и без него. Честное утверждение — «прошли через бота».")
    return "\n".join(lines)


def write_rows(matches: list[Match], path: Path) -> None:
    cols = ["row", "phone_raw", "phone", "date", "amount", "dest", "status", "duplicate",
            "conv_id", "bot_id", "first_contact", "days_to_sale", "reached_manager", "offers",
            "bitrix_lead_id", "bitrix_deal_id", "outcome"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(cols)
        for m in matches:
            d = m.dialog or m.later_dialog
            first = _local_day(d.created_at) if d else None
            w.writerow([m.sale.row, m.sale.raw_phone, m.sale.phone, m.sale.day or "",
                        m.sale.amount, m.sale.dest, m.status, int(m.duplicate),
                        d.conv_id if d else "", d.bot_id if d else "", first or "",
                        (m.sale.day - first).days if (first and m.sale.day) else "",
                        int(m.reached_manager), d.offers if d else "",
                        d.bitrix_lead_id if d else "", d.bitrix_deal_id if d else "",
                        d.outcome if d else ""])


# ------------------------------------------------------------------ наша база
async def load_dialogs(phones: set[str]) -> list[Dialog]:
    """Диалоги только по номерам из списка. Номер берём из `phone`, а если он пуст —
    из хвоста `user_id` (`bot_id:номер`), как ключ состояния."""
    from sqlalchemy import func, select

    from app.integrations.crm.db import Conversation, TourOffer, get_sessionmaker

    out: list[Dialog] = []
    async with get_sessionmaker()() as session:
        convs = (await session.execute(select(Conversation))).scalars().all()
        offers = dict((await session.execute(
            select(TourOffer.user_id, func.count()).group_by(TourOffer.user_id))).all())
        for c in convs:
            raw = c.phone or (c.user_id.split(":", 1)[-1] if c.user_id else "")
            phone = norm_phone(raw)
            if phone not in phones:
                continue
            out.append(Dialog(
                conv_id=c.id, phone=phone, bot_id=c.bot_id or "",
                created_at=c.created_at, stage=str(c.stage or ""),
                intercepted=bool(c.intercepted),
                outcome=str(c.outcome or ""), bitrix_lead_id=str(c.bitrix_lead_id or ""),
                bitrix_deal_id=str(c.bitrix_deal_id or ""),
                offers=int(offers.get(c.user_id, 0))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", type=Path)
    ap.add_argument("--phone-col")
    ap.add_argument("--date-col")
    ap.add_argument("--amount-col")
    ap.add_argument("--dest-col")
    ap.add_argument("--window-days", type=int, default=120,
                    help="насколько раньше продажи ещё засчитываем диалог (дней)")
    ap.add_argument("--out", type=Path, help="построчный результат в CSV")
    args = ap.parse_args()

    sales = load_sales(read_rows(args.file), phone_col=args.phone_col, date_col=args.date_col,
                       amount_col=args.amount_col, dest_col=args.dest_col)
    dialogs = asyncio.run(load_dialogs({s.phone for s in sales if s.phone}))
    matches = reconcile(sales, dialogs, window_days=args.window_days)
    print(render(summarize(matches)))
    if args.out:
        write_rows(matches, args.out)
        print(f"\nпострочно: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
