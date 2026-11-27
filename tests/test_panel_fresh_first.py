"""Свежие лиды сверху — показ Грише 14.11.2026: «показывает старые лиды, а не свежие».

Корень: Входящие, Фокус, доска и поиск сортировали по «дольше всех ждёт ответа».
Брошенный месяц назад диалог (клиент написал, ему не ответили) всегда «ждёт» дольше
любого свежего — и занимал верх, а свежие уходили за обрезку страницы инбокса.

Закреплено:
1. Флаг OFF — порядок прежний, байт в байт (дольше ждёт — выше).
2. Флаг ON — ждущие не дольше потолка наверху, внутри дольше ждёт — выше (SLA не теряем).
3. Брошенные дольше потолка и уже отвеченные — ниже, по свежести последнего сообщения.
4. Ничего не пропадает: тот же набор карточек, другой порядок.
5. Доска с флагом — по свежести в каждой колонке; диалог без даты — в конце.
6. Фокус: шум и «молчащие» по-прежнему уходят в конец и с флагом.
"""
from datetime import datetime, timedelta, timezone

import app.config
from app.admin import router as r
from app.integrations.panel.store import ConversationView

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _conv(uid, *, minutes_ago, sender, stage="greeting", funnel="visa"):
    at = None if minutes_ago is None else NOW - timedelta(minutes=minutes_ago)
    return ConversationView(user_id=uid, funnel=funnel, stage=stage,
                            last_message_at=at, last_sender=sender, last_text="x")


# dead — клиент ждёт 30 дней; fresh — ждёт 10 минут; warm — ждёт 2 часа;
# answered — пять минут назад ответил бот; old_answered — бот ответил неделю назад.
CONVS = [
    _conv("dead", minutes_ago=30 * 24 * 60, sender="client"),
    _conv("fresh", minutes_ago=10, sender="client"),
    _conv("answered", minutes_ago=5, sender="bot"),
    _conv("warm", minutes_ago=120, sender="client"),
    _conv("old_answered", minutes_ago=7 * 24 * 60, sender="bot"),
]


def _models():
    return [r._card_model(c, NOW) for c in CONVS]


def _ids(cards):
    return [c["user_id"] for c in cards]


def test_inbox_flag_off_keeps_old_order():
    """Регресс-гейт: без флага — дольше ждёт выше, как было (мертвец первым)."""
    assert _ids(r._waiting_sorted(_models())) == ["dead", "warm", "fresh"]


def test_inbox_flag_on_puts_live_waiting_first_and_dead_last(monkeypatch):
    monkeypatch.setattr(app.config.settings, "panel_fresh_wait_cap_hours", 72, raising=False)
    got = _ids(r._waiting_sorted(_models(), fresh_first=True))
    # живые ждущие — наверху, внутри дольше ждёт выше; брошенный — в конце, но на месте
    assert got == ["warm", "fresh", "dead"]


def test_inbox_flag_on_loses_nothing(monkeypatch):
    monkeypatch.setattr(app.config.settings, "panel_fresh_wait_cap_hours", 72, raising=False)
    assert sorted(_ids(r._waiting_sorted(_models(), fresh_first=True))) == \
        sorted(_ids(r._waiting_sorted(_models())))


def test_cap_is_configurable(monkeypatch):
    """Потолок 1 час: ждущий 2 часа уже «брошен» и идёт по свежести после живого."""
    monkeypatch.setattr(app.config.settings, "panel_fresh_wait_cap_hours", 1, raising=False)
    assert _ids(r._waiting_sorted(_models(), fresh_first=True)) == ["fresh", "warm", "dead"]


def test_board_flag_off_unchanged_and_on_sorts_by_freshness():
    off, _ = r._build_board(CONVS, NOW)
    on, _ = r._build_board(CONVS, NOW, fresh_first=True)
    col_off = next(c for c in off if c["key"] == "greeting")["cards"]
    col_on = next(c for c in on if c["key"] == "greeting")["cards"]
    # «old_answered» (бот ответил неделю назад) доска кладёт в «Молчат», не сюда.
    # без флага: ждущие по ожиданию — мертвец первым, отвеченные (-1) — в хвосте
    assert _ids(col_off) == ["dead", "warm", "fresh", "answered"]
    # с флагом: строго по свежести последнего сообщения
    assert _ids(col_on) == ["answered", "fresh", "warm", "dead"]
    assert sorted(_ids(col_on)) == sorted(_ids(col_off))
    # раскладка по колонкам флагом не меняется
    assert [(c["key"], len(c["cards"])) for c in on] == \
        [(c["key"], len(c["cards"])) for c in off]


def test_board_conversation_without_date_goes_last():
    convs = CONVS + [_conv("nodate", minutes_ago=None, sender="client")]
    on, _ = r._build_board(convs, NOW, fresh_first=True)
    assert _ids(next(c for c in on if c["key"] == "greeting")["cards"])[-1] == "nodate"


def test_focus_noise_still_last_with_flag(monkeypatch):
    monkeypatch.setattr(app.config.settings, "panel_fresh_wait_cap_hours", 72, raising=False)
    models = _models()
    for m in models:
        m["is_noise"] = m["user_id"] == "fresh"   # реклама — даже свежая — в конец
        m["is_silent"] = False
    got = _ids(r._focus_sorted(models, fresh_first=True))
    assert got[-1] == "fresh"
    assert got[:2] == ["warm", "dead"]


def test_flag_registered_with_default_off():
    assert app.config.Settings.model_fields["panel_fresh_first_enabled"].default is False
    assert r.FEATURE_FLAGS["panel_fresh_first_enabled"]["default"]() is False
