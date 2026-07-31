"""Подтягивание ответов менеджера с телефона (вопрос Гриши «почему ждёт ответа?»).

Ключевое, что проверяем — правило отбора. Оно должно быть таким, чтобы сообщение бота
физически не могло попасть в «ответы менеджера»: берём только исходящие новее последнего
сообщения диалога, и только те, чьих id у нас ещё нет.
"""
from datetime import datetime, timezone

from app.channels.wappi import is_manager_reply, message_time
from app.core.manager_sync import select_missing_replies

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
