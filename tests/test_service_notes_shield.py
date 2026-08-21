"""Экран служебных заметок: бот не должен пересказывать клиенту свою кухню.

Дефект, ради которого всё это написано (замер по проду 11.07–21.08.2026, 9 реплик):
служебные заметки — дата, график, язык, реклама, квалификация — подмешиваются в ход
с ролью `user`, то есть выглядят для модели как сообщение клиента. Пока клиент пишет
по делу, его реплика содержательнее и перевешивает. Но на пустом ходе («Спасибо»,
«Хорошо», фото) самым осмысленным текстом в окне оказывается заметка — и модель
отвечает НА НЕЁ:

    Клиент:  Спасибо
    Бот:     Спасибо! Я учёл:
             Сегодня 21.08.2026, пятница
             Рабочие часы: 09:00–19:00
             ...
             Готов помогать клиентам! 👍
    Клиент:  Вы уже уходите?
    Бот:     Нет, я здесь! 😊 Это была служебная заметка для меня.
    Менеджер: Извините, подключили бота. 😅

Два рубежа, оба под флагом `service_notes_shield_enabled` (дефолт OFF):
  1. `runner._shielded_prefix` — заметки схлопнуты в один ход и закрыты ответом
     ассистента, так что ожидающей реакции остаётся только реплика клиента;
  2. `validator._strip_service_note_echo` — если модель всё же проговорилась, эхо
     не доходит до клиента.

Тексты в тестах — ДОСЛОВНЫЕ реплики с прода, а не выдуманные.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent import runner
from app.agent.validator import SAFE_SERVICE_NOTE_REPLY, validate_reply
from app.core import flags
from app.core.state import DialogState


# --- реальные реплики бота клиентам (прод) -------------------------------------------
LEAK_2108_THANKS = (
    "Спасибо! Я учёл:\n"
    "Сегодня 21.08.2026, пятница\n"
    "Рабочие часы: 09:00–19:00\n"
    "Выходной: воскресенье\n"
    "Доступные дни для визитов: 21.08 (пятница), 22.08 (суббота), 24.08 (понедельник)\n"
    "\n"
    "Готов помогать клиентам! 👍"
)
LEAK_2108_STILL_HERE = (
    "Нет, я здесь! 😊 Это была служебная заметка для меня. теперь я знаю текущую дату "
    "и часы работы офиса.\n"
    "\n"
    "Чем я могу вам помочь? Ищете тур, билеты или визу?"
)
LEAK_1107_DATE = (
    "Понял! 📝 Сегодня 11 июля 2026, суббота (время Бишкека). Буду отсчитывать все "
    "относительные даты от этого дня."
)
LEAK_1507_NOTE = (
    "Спасибо за служебную заметку! 👍\n"
    "\n"
    "Я готов помогать клиентам как Адеми, менеджер Frunze Travel (туры)."
)


# ---------------- рубеж 1: заметки перестают выглядеть репликой клиента --------------
def test_shielded_prefix_collapses_notes_and_closes_them_with_assistant():
    notes = [
        {"role": "user", "content": "[Служебная заметка: сегодня 21.08.2026, пятница.]"},
        {"role": "user", "content": "[Служебная заметка: часы приёма 09:00–19:00.]"},
    ]

    prefix = runner._shielded_prefix(notes)

    # Один ход вместо двух, и он закрыт ответом ассистента.
    assert len(prefix) == 2
    assert prefix[0]["role"] == "user"
    assert prefix[1]["role"] == "assistant"
    # Содержимое заметок не потеряно — бот по-прежнему знает дату и график.
    assert "21.08.2026" in prefix[0]["content"]
    assert "09:00–19:00" in prefix[0]["content"]
    # Рамка прямо говорит модели, что это не речь клиента.
    assert "НЕ СООБЩЕНИЕ КЛИЕНТА" in prefix[0]["content"]


def test_shielded_prefix_on_empty_notes_adds_nothing():
    assert runner._shielded_prefix([]) == []


# ---------------- рубеж 1 в живом ходе ------------------------------------------------
class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _Resp:
    def __init__(self, text):
        self.stop_reason = "end_turn"
        self.content = [_Block(text)]
        self.usage = None


def _patch_client(monkeypatch, text="Конечно, подскажу 🙂"):
    fake = AsyncMock()
    fake.messages.create = AsyncMock(return_value=_Resp(text))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


def _state():
    return DialogState(user_id="996771631771", funnel="tours", bot_id="frunze_tours_sezim")


def _sent_messages(fake):
    return fake.messages.create.await_args.kwargs["messages"]


def test_turn_with_shield_leaves_only_client_turn_awaiting_answer(monkeypatch):
    asyncio.run(flags.set_flag("service_notes_shield_enabled", True))
    fake = _patch_client(monkeypatch)

    asyncio.run(runner.run_tours_turn(_state(), "Спасибо"))

    messages = _sent_messages(fake)
    # Служебный блок ровно один и закрыт ассистентом...
    assert messages[0]["role"] == "user"
    assert "НЕ СООБЩЕНИЕ КЛИЕНТА" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
    # ...а последним — и единственным ждущим ответа — идёт реплика клиента.
    assert messages[-1] == {"role": "user", "content": "Спасибо"}
    # Ни одна заметка не осталась отдельным «сообщением клиента».
    loose = [m for m in messages[2:]
             if m["role"] == "user" and isinstance(m["content"], str)
             and m["content"].startswith("[Служебная заметка")]
    assert loose == []


def test_turn_without_shield_keeps_old_behaviour(monkeypatch):
    """Флаг OFF — ход собирается ровно как раньше: клиенту ничего не меняем."""
    asyncio.run(flags.set_flag("service_notes_shield_enabled", False))
    fake = _patch_client(monkeypatch)

    asyncio.run(runner.run_tours_turn(_state(), "Спасибо"))

    messages = _sent_messages(fake)
    assert all(m["role"] == "user" for m in messages[:-1])
    assert "НЕ СООБЩЕНИЕ КЛИЕНТА" not in messages[0]["content"]
    assert messages[0]["content"].startswith("[Служебная заметка")
    assert messages[-1] == {"role": "user", "content": "Спасибо"}


def test_shield_keeps_date_and_schedule_available_to_model(monkeypatch):
    """Экран прячет заметки от клиента, а не от модели — иначе вернём баг с датой."""
    asyncio.run(flags.set_flag("service_notes_shield_enabled", True))
    fake = _patch_client(monkeypatch)

    asyncio.run(runner.run_tours_turn(_state(), "когда можно подойти?"))

    served = _sent_messages(fake)[0]["content"]
    assert "сегодня" in served.lower()
    assert "Часы приёма" in served


# ---------------- рубеж 2: эхо не доходит до клиента ---------------------------------
@pytest.mark.parametrize("leak", [
    LEAK_2108_THANKS,
    LEAK_2108_STILL_HERE,
    LEAK_1107_DATE,
    LEAK_1507_NOTE,
])
def test_real_prod_leaks_are_stripped(leak):
    clean, violations = validate_reply(leak, "tours", shield_service_notes=True)

    assert "service_note_echo_stripped" in violations
    assert "служебн" not in clean.lower()
    assert "Я учёл:" not in clean
    assert "Готов помогать клиентам" not in clean


def test_leak_keeps_the_useful_half_of_the_reply():
    """21.08: первая строка была утечкой, вторая — нормальным вопросом клиенту."""
    clean, _ = validate_reply(LEAK_2108_STILL_HERE, "tours", shield_service_notes=True)

    assert "Чем я могу вам помочь?" in clean
    assert "Ищете тур, билеты или визу?" in clean


def test_leak_with_nothing_left_falls_back_to_safe_reply():
    clean, violations = validate_reply(LEAK_2108_THANKS, "tours", shield_service_notes=True)

    assert clean == SAFE_SERVICE_NOTE_REPLY
    assert "service_note_echo_stripped" in violations


@pytest.mark.parametrize("legit", [
    # Часы приёма и дату бот называет клиенту ЗАКОННО — резать их нельзя.
    "Мы работаем с 09:00 до 19:00, в воскресенье выходной. Когда вам удобно подойти?",
    "Сегодня пятница, 21 августа. Можем принять вас сегодня до 19:00.",
    "Подобрал варианты в Турцию на октябрь. Показать?",
    "Записал вас на субботу, 22 августа, в 15:00. Адрес пришлю отдельно.",
    "Я учёл ваши пожелания и подобрал варианты подешевле.",
])
def test_legit_replies_are_not_touched(legit):
    clean, violations = validate_reply(legit, "tours", shield_service_notes=True)

    assert clean == legit
    assert "service_note_echo_stripped" not in violations


def test_without_flag_validator_does_not_touch_the_leak():
    """Ремень ходит вместе с флагом: выключен — текст идёт как шёл."""
    clean, violations = validate_reply(LEAK_2108_THANKS, "tours")

    assert "service_note_echo_stripped" not in violations
    assert "Я учёл:" in clean
