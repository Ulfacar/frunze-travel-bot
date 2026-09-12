# -*- coding: utf-8 -*-
"""Дозаполнение истории дописывает только пустое и никогда не спорит с человеком.

`facts.merge` перезаписывает известное свежим — это правильно для живого разговора, где
клиент передумал. Для прогона по истории правило обратное: в карточке может стоять то,
что менеджер завёл руками, и наш разбор старой реплики не имеет права это трогать.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from app.agent import facts


def test_empty_fields_are_filled():
    got = facts.fill_gaps({"destination": "Турция"}, {"dates": "01.10.2026-08.10.2026"})
    assert got["destination"] == "Турция"
    assert got["dates"] == "01.10.2026-08.10.2026"


def test_known_field_is_never_overwritten():
    """Главное правило: в карточке может быть рука менеджера."""
    got = facts.fill_gaps({"destination": "ОАЭ"}, {"destination": "Турция"})
    assert got["destination"] == "ОАЭ"


def test_blank_value_counts_as_empty():
    got = facts.fill_gaps({"destination": ""}, {"destination": "Турция"})
    assert got["destination"] == "Турция"


def test_nothing_found_changes_nothing():
    known = {"destination": "Турция"}
    assert facts.fill_gaps(known, {}) == known


def test_empty_new_value_does_not_create_a_key():
    got = facts.fill_gaps({}, {"destination": ""})
    assert "destination" not in got


def test_merge_still_overwrites():
    """Живой разговор не трогаем: там свежее обязано побеждать."""
    assert facts.merge({"destination": "ОАЭ"}, {"destination": "Турция"})["destination"] == "Турция"
