# -*- coding: utf-8 -*-
"""«Спасибо 🌸🌸🌸» — это не ожидание ответа, а конец разговора.

Живой прогон 11.09 перед включением: в первом же тике 3 из 8 напоминаний были
ложными — «Удачи вам», «Спасибо 🌸🌸🌸» и автоответ чужой фирмы («Здравствуйте,
спасибо за обращение в Bilet Standart!»). Дёрнуть менеджера «клиент ждёт вас
40 минут» на прощание — ровно то, что владельцы назвали «лишь бы их это не
доставало». 38% ложных на первом же тике — фича, которую выключат в тот же день.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core import awaiting

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def conv(last_text, **kw):
    base = dict(user_id="996700000001", phone="996700000001", funnel="tours",
                stage="manager", intercepted=True, archived=False, outcome=None,
                last_sender="client", last_message_at=NOW - timedelta(minutes=40),
                assigned_to="aisina", qualification={}, last_text=last_text)
    base.update(kw)
    return SimpleNamespace(**base)


def cfg():
    return SimpleNamespace(alert_awaiting_minutes=10, alert_cooldown_minutes=60,
                           awaiting_telegram_enabled=True, awaiting_max_age_hours=24)


def picked(text):
    return [c.user_id for c in awaiting.select_telegram_targets([conv(text)], NOW, cfg())]


# --- то, на чём нельзя дёргать человека -------------------------------------------
def test_gratitude_alone_is_not_waiting():
    assert picked("Спасибо 🌸🌸🌸") == []


def test_goodbye_is_not_waiting():
    assert picked("Удачи вам") == []


def test_foreign_autoreply_is_not_waiting():
    assert picked("Здравствуйте, спасибо за обращение в Bilet Standart! Чем могу помочь ?") == []


def test_ok_alone_is_not_waiting():
    assert picked("хорошо") == []


# --- то, на чём дёрнуть ОБЯЗАНЫ (ложное срабатывание фильтра дороже) --------------
def test_thanks_with_a_question_is_waiting():
    assert picked("Спасибо, а на 5 ночей есть?") != []


def test_short_answer_to_the_bot_is_waiting():
    """«На 2» — это ответ на вопрос анкеты, разговор живой."""
    assert picked("На 2") != []


def test_plain_request_is_waiting():
    assert picked("разрешенные транзитные пункты в китае") != []


def test_empty_text_is_still_waiting():
    """Голосовое или картинка без текста — молчать об этом нельзя."""
    assert picked("") != []
