"""Досье читается человеком без расшифровки — оно нужно менеджеру у стойки.

## Что было (живой прогон `render_dossier` на лиде 186261, прод, 21.08.2026)

```
Досье бота:
Направление: ОАЭ · Дубай
Вылет: Ош
Бюджет: 2500 USD
Даты: 05.09.2026-11.09.2026
Состав: 4 · 7, 10
```

`Состав: 4 · 7, 10` — это четверо туристов и дети семи и десяти лет. Менеджер, сверяющий
заказ с пришедшим клиентом, обязан догадаться об этом сам: метки склеены разделителем
без подписей. Сводка, которую надо расшифровывать, свою работу не делает — а вся ценность
досье именно в том, чтобы менеджер прочёл его вслух и спросил «всё верно?».

Правило: числа сопровождаются словами, склонение по числу настоящее.
Нечисловое значение («мы вдвоём») отдаём как есть — склонять чужую формулировку опаснее,
чем оставить её нетронутой.
"""
from __future__ import annotations

import types
from datetime import datetime, timezone

import pytest

from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.crm.bitrix24 import sanitize_lead_comments


def _conv():
    return types.SimpleNamespace(
        user_id="frunze_tours:996700000093", bot_id="frunze_tours",
        messages=[], last_message_at=datetime(2026, 8, 21, 18, 30, tzinfo=timezone.utc))


def _render(**facts):
    return bp.render_dossier(_conv(), dict(facts))


def _compose(text):
    for line in text.splitlines():
        if line.startswith("Состав:"):
            return line
    return ""


# ---------------- состав читается как фраза -----------------------------------------
def test_composition_reads_as_sentence():
    line = _compose(_render(tourists="4", children_ages="7, 10"))
    assert "4 туриста" in line
    assert "дети 7 и 10 лет" in line
    assert "4 · 7, 10" not in line


def test_single_tourist_singular():
    assert "1 турист" in _compose(_render(tourists="1"))
    assert "1 туристов" not in _compose(_render(tourists="1"))


@pytest.mark.parametrize("count,expected", [
    ("2", "2 туриста"), ("5", "5 туристов"), ("21", "21 турист"), ("22", "22 туриста"),
])
def test_tourists_declension(count, expected):
    assert expected in _compose(_render(tourists=count))


def test_one_child_singular():
    assert "ребёнок 5 лет" in _compose(_render(children_ages="5"))


def test_three_children_listed():
    line = _compose(_render(children_ages="4, 7, 12"))
    assert "дети 4, 7 и 12 лет" in line


def test_non_numeric_tourists_kept_as_is():
    """Клиент написал словами — не склоняем чужую формулировку, отдаём как есть."""
    line = _compose(_render(tourists="мы вдвоём"))
    assert "мы вдвоём" in line


# ---------------- направление — одна сущность ---------------------------------------
def test_destination_and_region_kept_together():
    text = _render(destination="Турция", region="Анталья")
    assert "Направление: Турция, Анталья" in text


# ---------------- портал ------------------------------------------------------------
def test_dossier_fits_portal():
    """Портал молча съедает эмодзи и BBCode — досье обязано пережить санитайзер целиком."""
    text = _render(destination="ОАЭ", region="Дубай", departure_city="Ош",
                   budget="2500 USD", dates="05.09.2026-11.09.2026",
                   tourists="4", children_ages="7, 10")
    assert sanitize_lead_comments(text) == text
    assert len(text) <= 2000
