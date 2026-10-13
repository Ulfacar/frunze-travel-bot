# -*- coding: utf-8 -*-
"""Сверка списка продаж с диалогами: места, где цифра «продал бот» могла бы соврать.

* один человек под разными записями номера — одна продажа, один диалог;
* неразборчивый номер не выпадает из знаменателя молча;
* диалог ПОСЛЕ покупки — не заслуга бота;
* дубль строки в списке не удваивает продажу;
* «дошёл до менеджера» не выводится из автоназначения владельца.
"""
from datetime import date, datetime, timedelta, timezone

from scripts.sales_reconcile import (
    Dialog,
    Sale,
    load_sales,
    norm_phone,
    parse_day,
    read_rows,
    reconcile,
    render,
    summarize,
)

BISHKEK = timezone(timedelta(hours=6))


def _dialog(conv_id=1, phone="996555123456", when=datetime(2026, 8, 1, 12, tzinfo=BISHKEK),
            **kw) -> Dialog:
    return Dialog(conv_id=conv_id, phone=phone, bot_id="frunze_tours", created_at=when, **kw)


def _sale(phone="996555123456", day=date(2026, 8, 10), row=2, amount="") -> Sale:
    return Sale(row=row, raw_phone=phone, phone=norm_phone(phone), day=day, amount=amount)


# ---------------- номера и даты -------------------------------------------------------
def test_all_local_forms_of_a_kg_number_collapse_to_one():
    forms = ["0555 123 456", "+996 (555) 12-34-56", "996555123456", "555123456",
             "996555123456.0"]
    assert {norm_phone(f) for f in forms} == {"996555123456"}


def test_garbage_phone_is_empty_not_exception():
    assert norm_phone("звонил сам") == ""
    assert norm_phone("12345") == ""


def test_foreign_whatsapp_number_is_kept():
    assert norm_phone("905078174386") == "905078174386"


def test_dates_in_manager_formats():
    for text in ("10.08.2026", "2026-08-10", "10/08/2026", "10.08.26", "10.08.2026 14:00"):
        assert parse_day(text) == date(2026, 8, 10), text
    assert parse_day(datetime(2026, 8, 10, 9)) == date(2026, 8, 10)
    assert parse_day("вчера") is None


# ---------------- сопоставление -------------------------------------------------------
def test_dialog_before_sale_counts_as_via_bot():
    [m] = reconcile([_sale()], [_dialog()])
    assert m.status == "bot" and m.dialog.conv_id == 1


def test_dialog_only_after_sale_is_not_bots_merit():
    later = _dialog(when=datetime(2026, 8, 20, 12, tzinfo=BISHKEK))
    [m] = reconcile([_sale()], [later])
    assert m.status == "after_sale" and m.dialog is None


def test_same_day_dialog_counts_even_late_evening_utc():
    """Список без времени: диалог в 23:30 Бишкека того же дня — до продажи (это 17:30 UTC)."""
    evening = datetime(2026, 8, 10, 17, 30, tzinfo=timezone.utc)
    [m] = reconcile([_sale()], [_dialog(when=evening)])
    assert m.status == "bot"


def test_dialog_older_than_window_is_ignored():
    old = _dialog(when=datetime(2026, 1, 1, tzinfo=BISHKEK))
    [m] = reconcile([_sale()], [old], window_days=120)
    assert m.status == "no_dialog"


def test_bad_phone_stays_in_denominator():
    matches = reconcile([_sale(), _sale(phone="нет номера", row=3)], [_dialog()])
    s = summarize(matches)
    assert s["sales"] == 2 and s["bad_phone"] == 1 and s["via_bot"] == 1
    assert "номер не разобран               1" in render(s)


def test_duplicate_row_counted_once():
    matches = reconcile([_sale(row=2), _sale(phone="0555123456", row=3)], [_dialog()])
    s = summarize(matches)
    assert s["rows"] == 2 and s["duplicates"] == 1 and s["sales"] == 1 and s["via_bot"] == 1


def test_prefers_dialog_that_reached_manager():
    plain = _dialog(conv_id=1, when=datetime(2026, 8, 5, tzinfo=BISHKEK))
    handed = _dialog(conv_id=2, when=datetime(2026, 8, 1, tzinfo=BISHKEK), stage="manager_handoff")
    [m] = reconcile([_sale()], [plain, handed])
    assert m.dialog.conv_id == 2 and m.reached_manager


def test_reached_manager_needs_handoff_or_intercept():
    [m] = reconcile([_sale()], [_dialog(stage="greeting")])
    assert not m.reached_manager
    [m] = reconcile([_sale()], [_dialog(intercepted=True)])
    assert m.reached_manager


def test_amounts_with_thousand_separators():
    matches = reconcile([_sale(amount="1 250 000 сом"), _sale(phone="0700111222", row=3,
                                                              amount="1.000.000")],
                        [_dialog()])
    s = summarize(matches)
    assert s["amount_total"] == 2_250_000
    assert s["amount_via_bot"] == 1_250_000


# ---------------- чтение файла --------------------------------------------------------
def test_reads_cp1251_semicolon_csv_and_guesses_columns(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_bytes("Дата;Телефон клиента;Сумма;Страна\n"
                     "10.08.2026;0555 123 456;150000;Турция\n"
                     ";;;\n".encode("cp1251"))
    sales = load_sales(read_rows(path))
    assert len(sales) == 1
    assert sales[0].phone == "996555123456" and sales[0].day == date(2026, 8, 10)
    assert sales[0].amount == "150000" and sales[0].dest == "Турция"
