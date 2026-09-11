# -*- coding: utf-8 -*-
"""Один человек в двух брендах — это не общая карточка.

Фильтр общих карточек считал ДИАЛОГИ на лиде. Но клиент, написавший и в туры
(frunze_tours:996...), и в визы (getvisa:996...), даёт два диалога на одной
карточке Битрикса — и фильтр объявлял её общей, молча отказываясь проводить
оплату.

Замер 11.09 на боевой базе: таких карточек 78 (160 диалогов, из них 135
туровых), а настоящих общих — где на карточке РАЗНЫЕ телефоны — всего 17.
То есть фильтр ошибался чаще, чем срабатывал по делу.

Считать надо уникальные номера, а не строки диалогов.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from types import SimpleNamespace

from app.core import sale_check


def conv(user_id, lead):
    return SimpleNamespace(user_id=user_id, bitrix_lead_id=lead)


def test_same_person_in_two_brands_is_not_shared():
    """Живой случай: лид 181771, туры и визы одного номера."""
    convs = [conv("frunze_tours:996500494009", "181771"),
             conv("getvisa:996500494009", "181771")]
    assert sale_check._shared_leads(convs) == set()


def test_different_people_on_one_card_is_still_shared():
    """Контейнерная карточка Открытой линии — ради неё фильтр и писался."""
    convs = [conv("frunze_tours:996700111111", "203581"),
             conv("frunze_tours:996700222222", "203581"),
             conv("frunze_tours:996700333333", "203581")]
    assert sale_check._shared_leads(convs) == {"203581"}


def test_same_person_three_brands_is_not_shared():
    convs = [conv("frunze_tours:996555000111", "900"),
             conv("getvisa:996555000111", "900"),
             conv("frunze_tours_sezim:996555000111", "900")]
    assert sale_check._shared_leads(convs) == set()


def test_mixed_card_is_shared():
    """Свой номер плюс чужой на одной карточке — трогать нельзя."""
    convs = [conv("frunze_tours:996555000111", "901"),
             conv("getvisa:996555000111", "901"),
             conv("frunze_tours:996555999888", "901")]
    assert sale_check._shared_leads(convs) == {"901"}


def test_single_dialog_card_is_not_shared():
    assert sale_check._shared_leads([conv("frunze_tours:996700000001", "555")]) == set()


def test_empty_lead_is_ignored():
    convs = [conv("frunze_tours:996700000001", ""),
             conv("frunze_tours:996700000002", "")]
    assert sale_check._shared_leads(convs) == set()
