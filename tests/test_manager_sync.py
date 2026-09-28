"""Подтягивание ответов менеджера с телефона (вопрос Гриши «почему ждёт ответа?»).

Ключевое, что проверяем — правило отбора. Оно должно быть таким, чтобы сообщение бота
физически не могло попасть в «ответы менеджера»: берём только исходящие новее последнего
сообщения диалога, и только те, чьих id у нас ещё нет.
"""
from datetime import datetime, timezone

import httpx

from app.channels.wappi import is_manager_reply, message_time
from app.core.manager_sync import (looks_like_access_failure, permanent_rejection_code,
                                   select_missing_replies)

AFTER = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
TS = int(AFTER.timestamp())


def _msg(id, *, out=True, t=TS + 60, body="ответ менеджера", type="chat"):
    return {"id": id, "fromMe": out, "time": t, "type": type, "body": body}


def test_picks_outgoing_written_after_client_message():
    got = select_missing_replies([_msg("m1")], after=AFTER, known_ids=set())

    assert [m["id"] for m in got] == ["m1"]


def test_ignores_incoming_client_messages():
    assert select_missing_replies([_msg("m1", out=False)], after=AFTER, known_ids=set()) == []


def test_ignores_anything_older_than_last_client_message():
    """Старое исходящее — это история бота, а не пропущенный ответ. Путать нельзя."""
    old = _msg("m0", t=TS - 3600)

    assert select_missing_replies([old], after=AFTER, known_ids=set()) == []


def test_skips_messages_we_already_have():
    """id уже записан — это наша же отправка бота либо подтянутое ранее."""
    assert select_missing_replies([_msg("bot-1")], after=AFTER, known_ids={"bot-1"}) == []


def test_ignores_reactions_and_empty_bodies():
    reaction = _msg("r1", type="reaction")
    empty = _msg("e1", body="   ")

    assert select_missing_replies([reaction, empty], after=AFTER, known_ids=set()) == []


def test_returns_oldest_first():
    got = select_missing_replies(
        [_msg("late", t=TS + 300), _msg("early", t=TS + 60)], after=AFTER, known_ids=set()
    )

    assert [m["id"] for m in got] == ["early", "late"]


def test_is_manager_reply_accepts_alternative_outgoing_flags():
    assert is_manager_reply({"from_me": True, "type": "chat", "body": "ок"})
    assert is_manager_reply({"is_me": True, "type": "chat", "body": "ок"})
    assert not is_manager_reply({"fromMe": False, "type": "chat", "body": "ок"})


def test_message_time_survives_garbage():
    assert message_time({"time": "не число"}) == 0
    assert message_time({}) == 0
    assert message_time({"timestamp": 123}) == 123


def _http_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://wappi.pro/api/sync/messages/get")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_permanent_rejection_catches_client_refusal():
    """400/404 по чату — ответ по данным: повтор даст то же, диалог идёт в карантин.

    28.09.2026 один такой диалог дал 96 стеков за 48 часов.
    """
    assert permanent_rejection_code(_http_error(400)) == 400
    assert permanent_rejection_code(_http_error(404)) == 404


def test_permanent_rejection_ignores_try_later_and_our_own_bugs():
    """«Приходи позже» и наши падения в карантин не идут — иначе мы замолчим по живому чату."""
    assert permanent_rejection_code(_http_error(429)) is None
    assert permanent_rejection_code(_http_error(500)) is None
    assert permanent_rejection_code(httpx.ConnectTimeout("нет сети")) is None
    assert permanent_rejection_code(KeyError("наш баг")) is None


def test_one_broken_chat_is_not_an_access_failure():
    """Один битый чат (диалог 3671) — рабочая ситуация, тревожить некого."""
    assert not looks_like_access_failure(0)
    assert not looks_like_access_failure(1)


def test_mass_rejection_looks_like_access_failure():
    """Находка ревью класса C: если Wappi отказывает ВСЕМ, молчаливый карантин на сутки
    спрячет от нас то, что ответы менеджеров перестали доезжать до панели вообще."""
    assert looks_like_access_failure(3)
    assert looks_like_access_failure(25)
