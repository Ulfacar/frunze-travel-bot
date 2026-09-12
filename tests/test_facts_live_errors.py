# -*- coding: utf-8 -*-
"""Шесть классов ошибок разбора, найденных холостым прогоном по боевой переписке.

Фразы взяты из базы дословно, не придуманы. Каждая сегодня даёт неверное поле, а неверное
поле в карточке дороже пустого: бюджет уезжает в сумму сделки, состав — в расчёт тура.
Поэтому проверяем не «извлеки правильно», а «не соври»: пусто — приемлемо, неправда — нет.

Замер: 1200 сообщений по двум боевым каналам, ошибки воспроизводятся на обоих.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from app.agent import facts

# Реальная реплика клиента целиком (лид по Swissôtel Al Murooj Dubai).
NIGHTS = ("Спасибо! Нам всё-таки достаточно 4 ночей, чтобы получилось 3 полноценных дня. "
          "Можете, пожалуйста, пересчитать Swissôtel Al Murooj Dubai именно на 4 ночи, "
          "с размещением в двух отдельных Classic Room: 2 взрослых в одном номере "
          "и 2 взрослых + ребёнок 1,5 года во втором?")


# --- (а) ночи — не люди ---------------------------------------------------------------

def test_nights_are_not_tourists():
    """«достаточно 4 ночей» давало состав 4. В комнате при этом 4 взрослых и ребёнок."""
    got = facts.extract(NIGHTS)
    assert str(got.get("tourists", "")) != "4", "четыре ночи — это не четыре туриста"


def test_decimal_child_age_is_not_two_children():
    """«ребёнок 1,5 года» давало возрасты «1, 5» — то есть двоих детей вместо одного."""
    ages = str(facts.extract(NIGHTS).get("children_ages", ""))
    assert ages != "1, 5", "полтора года — это один ребёнок, а не дети 1 и 5 лет"


# --- (б) чужая валюта ------------------------------------------------------------------

def test_korean_won_is_not_som():
    """«968 тыс вонн» давало бюджет 968 000 сом. Курса вон мы не знаем и знать не хотим."""
    assert not facts.extract("Цена 968 тыс вонн").get("budget")


# --- (в) деньги, которые не бюджет клиента ---------------------------------------------

def test_complaint_about_refund_is_not_a_budget():
    assert not facts.extract("жалко им 200 долл невернут").get("budget")


def test_exchange_fee_is_not_a_budget():
    assert not facts.extract("За обмен 185$").get("budget")


# --- (г) город прилёта — не город вылета ------------------------------------------------

def test_arrival_city_is_not_departure():
    """«рейс из Дубая в Бишкек» давало вылет из Бишкека — ровно наоборот."""
    got = facts.extract("Нам места надо поменять желательно именно на рейс из Дубая в Бишкек.")
    assert got.get("departure_city", "") != "Бишкек"


# --- (д) десятичная запятая -------------------------------------------------------------

def test_decimal_in_party_is_refused():
    assert str(facts.extract("2,5 человек").get("tourists", "")) != "5"


# --- КОНТРОЛЬНАЯ ГРУППА: это ломать нельзя ---------------------------------------------

def test_still_reads_a_plain_request():
    got = facts.extract("Хотели тур на двоих в Турцию с 7 по 14 октября")
    assert got.get("destination") == "Турция"
    assert str(got.get("tourists")) == "2"
    assert got.get("dates")


def test_still_reads_the_resort():
    got = facts.extract("Нячанг 20.10 до 10.11 на 10-12 дней")
    assert got.get("destination") == "Вьетнам"
    assert got.get("region") == "Нячанг"


def test_still_reads_departure_city():
    got = facts.extract("Хочу в Турцию вылет с алматы желательно")
    assert got.get("departure_city") == "Алматы"


def test_still_reads_a_real_budget():
    got = facts.extract("А где лучше всего у меня бюджет 3000 долларов")
    assert got.get("budget") == "3000 USD"


def test_still_reads_som_budget():
    got = facts.extract("бюджет до 150 тысяч")
    assert got.get("budget") == "150000 KGS"


def test_still_reads_children_ages():
    got = facts.extract("Едем вчетвером с ребенком 5 лет")
    assert str(got.get("tourists")) == "4"
    assert got.get("children_ages") == "5"
