"""ГЕЙТ задачи «клиент прислал скриншот — не отвечать ему про голосовые».

Написан ДО реализации и исполнителем НЕ редактируется.

## Зачем (со встречи с менеджерами, 06.08)

Дословно Адеми про скриншоты: «Иногда скриншоты отправляют… можете найти этот билет…
Сегодня мне на центр пик отправляли. **Но я его сразу уже отключила**».

Клиент присылает скрин билета — бот отвечает «Голосовые сообщения пока не распознаём,
напишите словами». Про картинку. Менеджер видит бессмыслицу и вырубает бота руками.
Это единственный измеримый сигнал «бот мешает», и он повторяется.

Замер по `media_capture` за сутки на проде: **image 14, document 8**, ptt 19,
sticker 2, vcard 1. То есть 22 раза в день бот говорит клиенту не то.

## Что делаем

* картинка/документ → честно сказать, что бот файл не откроет, и СРАЗУ передать
  менеджеру. Адеми и так делает это руками — просто перестаём заставлять её выключать
  бота;
* стикер/визитка → отвечаем как раньше и менеджера НЕ дёргаем: 2 стикера в сутки
  превратились бы в 2 лишних пуша, а дёрганый сторож перестают читать;
* голосовое → прежний путь без изменений (STT + guard).

## Требуется от реализации

    Message.media_type: str          # "" | image | document | sticker | vcard | ptt…
    WappiAdapter.parse проставляет его из `type` события
    Orchestrator._handle_non_text различает файл и голос
"""
from __future__ import annotations

import asyncio

import pytest

from app.channels.base import Message
from app.config import BotConfig, settings


def run(coro):
    return asyncio.run(coro)


def _orch(monkeypatch):
    from app.core import orchestrator as module
    from app.core.orchestrator import Orchestrator

    panel: list[str] = []
    replies: list[str] = []
    handoffs: list[str] = []
    orch = Orchestrator(channel=object(),
                        bot=BotConfig(id="getvisa", scenario="visa", wappi_profile_id="p"))

    async def expire(key): return None
    async def log_in(msg, text): panel.append(text)
    async def reply(msg, text): replies.append(text)
    async def bots_on(): return True
    async def sync(msg, state): return None
    async def push(msg, state, text): handoffs.append(text)

    monkeypatch.setattr(module, "expire_auto_intercept", expire)
    monkeypatch.setattr(orch, "_log_in", log_in)
    monkeypatch.setattr(orch, "_reply", reply)
    monkeypatch.setattr(orch, "_bots_on", bots_on)
    monkeypatch.setattr(orch, "_sync_card", sync)
    monkeypatch.setattr(orch, "_maybe_instant_handoff", push)
    monkeypatch.setattr(settings, "debounce_seconds", 0, raising=False)
    return orch, panel, replies, handoffs


def _media(media_type: str, user: str = "") -> Message:
    """Пользователь по умолчанию РАЗНЫЙ на каждый тип вложения.

    Состояние диалога живёт в общем сторе на весь модуль: один и тот же номер во всех
    кейсах означал бы, что перехват из предыдущего теста глушит следующий. Ловушка
    поймана этим же гейтом.
    """
    user = user or f"u-{media_type or 'none'}"
    return Message(channel="whatsapp", user_id=user, chat_id=user, text="",
                   kind="non_text", media_type=media_type)


# --- главный кейс ---------------------------------------------------------------

@pytest.mark.parametrize("media_type", ["image", "document"])
def test_file_is_handed_to_manager_not_answered_about_voice(monkeypatch, media_type):
    """Скрин билета — не голосовое. Ответ про голосовые здесь бессмыслица."""
    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(_media(media_type)))

    assert replies, "клиент обязан получить ответ, а не тишину"
    answer = replies[0].lower()
    assert "голосов" not in answer, "про голосовые в ответ на файл — то, из-за чего бота выключают"
    assert handoffs, "менеджер должен узнать о файле — он и так открывает его руками"


@pytest.mark.parametrize("media_type", ["image", "document"])
def test_file_marked_in_panel_by_its_kind(monkeypatch, media_type):
    """Менеджер должен видеть, ЧТО пришло, а не безликое «[медиа/голос]»."""
    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(_media(media_type)))
    assert len(panel) == 1
    assert panel[0] != "[медиа/голос]"


# --- чего делать нельзя ---------------------------------------------------------

@pytest.mark.parametrize("media_type", ["sticker", "vcard"])
def test_sticker_does_not_wake_the_manager(monkeypatch, media_type):
    """Стикеров 2 в сутки. Пуш на каждый = шум, а шумный сторож перестают читать."""
    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(_media(media_type)))
    assert handoffs == [], "стикер — не повод дёргать менеджера"


def test_voice_path_unchanged(monkeypatch):
    """Голосовое идёт прежним путём: фолбэк про голосовые, менеджера зовём только
    на ВТОРОЕ подряд. Эту логику задача не трогает."""
    from app.core.orchestrator import NON_TEXT_FALLBACK

    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(Message(channel="whatsapp", user_id="u-voice", chat_id="u-voice",
                            text="", kind="non_text", media_type="ptt")))
    assert replies == [NON_TEXT_FALLBACK]
    assert handoffs == []


def test_failed_transcription_still_reads_as_voice(monkeypatch):
    """Распознавание пробовали и не вышло — это по-прежнему голосовое, не файл."""
    from app.core.orchestrator import NON_TEXT_VOICE_FAILED

    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(Message(channel="whatsapp", user_id="u-vf", chat_id="u-vf", text="",
                            kind="non_text", media_type="ptt", voice_failed=True)))
    assert panel == [NON_TEXT_VOICE_FAILED]


def test_unknown_media_type_behaves_as_before(monkeypatch):
    """Тип не пришёл (синтетические события, другой канал) — прежнее поведение."""
    from app.core.orchestrator import NON_TEXT_FALLBACK

    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(_media("")))
    assert replies == [NON_TEXT_FALLBACK]
    assert handoffs == []


def test_exactly_one_panel_entry(monkeypatch):
    """Инвариант проекта: одно входящее — одна запись в логе диалога."""
    orch, panel, replies, handoffs = _orch(monkeypatch)
    run(orch.handle(_media("image")))
    assert len(panel) == 1


def test_intercepted_dialog_is_left_alone(monkeypatch):
    """Менеджер уже ведёт диалог — бот молчит и не пушит повторно."""
    from app.core.orchestrator import Orchestrator  # noqa: F401
    from app.core.state import get_state_store

    orch, panel, replies, handoffs = _orch(monkeypatch)
    key = "getvisa:u-int"
    st = run(get_state_store().load(key))
    st.intercepted = True
    run(get_state_store().save(st))

    run(orch.handle(_media("image", user="u-int")))
    assert replies == [] and handoffs == []
    assert len(panel) == 1, "реплику клиента менеджер всё равно должен видеть"


# --- разбор типа из события Wappi ------------------------------------------------

@pytest.mark.parametrize("raw_type", ["image", "document", "sticker", "vcard", "ptt"])
def test_wappi_parse_fills_media_type(raw_type):
    """Тип обязан доехать из события до оркестратора — иначе различать нечего."""
    from app.channels.wappi import WappiAdapter

    bot = BotConfig(id="getvisa", scenario="visa", wappi_profile_id="p")
    msg = run(WappiAdapter(bot).parse(
        {"wh_type": "incoming_message", "type": raw_type, "from": "996700111222@c.us",
         "chatId": "996700111222@c.us", "body": ""}))
    assert msg.kind == "non_text"
    assert msg.media_type == raw_type


def test_wappi_text_has_no_media_type():
    from app.channels.wappi import WappiAdapter

    bot = BotConfig(id="getvisa", scenario="visa", wappi_profile_id="p")
    msg = run(WappiAdapter(bot).parse(
        {"wh_type": "incoming_message", "type": "chat", "from": "996700111222@c.us",
         "chatId": "996700111222@c.us", "body": "привет"}))
    assert msg.kind == "text" and msg.media_type == ""
