"""Тесты утреннего «горячего листа» (Фаза 0 календаря звонков).

Чистые функции (build_brief/render_text/_in_send_window) — без БД и LLM. Джоба run —
через инъекцию времени + memory-флаги, проверяем гейтинг и идемпотентность «раз в день».
"""
import asyncio
from datetime import datetime, timezone

from app.core import flags
from app.core import morning_brief as mb
from app.integrations.panel.store import ConversationView


def _conv(uid, **kw):
    base = dict(user_id=uid, funnel="tours")
    base.update(kw)
    return ConversationView(**base)


# ---------------- отбор: build_brief ----------------
def test_build_brief_splits_green_warm_and_excludes():
    now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)  # 10:00 Бишкек
    convs = [
        _conv("g1", readiness_tier="green", estimated_value=1500, estimated_value_currency="$"),
        _conv("g2", readiness_tier="green", estimated_value=500, estimated_value_currency="$"),
        _conv("w1", readiness_tier="warm"),
        _conv("n1", readiness_tier="noise"),            # шум — не в лист
        _conv("i1", readiness_tier="insufficient"),     # мало данных — не в лист
        _conv("won", readiness_tier="green", outcome="won"),        # закрыт — исключить
        _conv("asg", readiness_tier="green", assigned_to="sezim"),  # уже у человека
        _conv("itc", readiness_tier="green", intercepted=True),     # ведёт менеджер
    ]
    b = mb.build_brief(convs, now)
    assert [c["user_id"] for c in b["green"]] == ["g1", "g2"]   # чек desc
    assert [c["user_id"] for c in b["warm"]] == ["w1"]
    assert b["green_count"] == 2 and b["warm_count"] == 1
    assert b["date_label"] == "12.07"


def test_build_brief_empty():
    b = mb.build_brief([], datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc))
    assert b["green"] == [] and b["warm"] == []
    assert b["green_count"] == 0 and b["warm_count"] == 0


# ---------------- рендер текста ----------------
def test_render_text_lists_lead_with_check_and_reason():
    now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
    txt = mb.render_text(mb.build_brief([
        _conv("g1", readiness_tier="green", estimated_value=1500, estimated_value_currency="$",
              qualification={"name": "Айгерим", "destination": "Анталья"},
              readiness_reason="Готов платить"),
    ], now))
    assert "🔥 Горячий лист · 12.07" in txt
    assert "Айгерим" in txt and "1500$" in txt and "Анталья" in txt
    assert "Готов платить" in txt


def test_render_text_empty_is_calm():
    now = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)
    assert "спокойное утро" in mb.render_text(mb.build_brief([], now))


# ---------------- окно отправки ----------------
def test_in_send_window():
    class _Cfg:
        morning_brief_hour = 9
    cfg = _Cfg()
    assert mb._in_send_window(9, cfg)
    assert mb._in_send_window(11, cfg)
    assert not mb._in_send_window(8, cfg)       # рано
    assert not mb._in_send_window(12, cfg)      # окно [9, 12)


# ---------------- джоба: гейтинг + идемпотентность ----------------
def _patch_store(monkeypatch, convs):
    class _Store:
        async def all_conversations_light(self):
            return list(convs)
    monkeypatch.setattr("app.integrations.panel.store.get_conversation_store", lambda: _Store())


def test_run_sends_once_per_day(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    pushed = []

    async def fake_push(text, cfg):
        pushed.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", fake_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    morning = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)  # 10:00 Бишкек, в окне
    asyncio.run(mb.run(now=morning))
    asyncio.run(mb.run(now=morning))   # второй прогон того же дня — не должен слать снова

    assert len(pushed) == 1            # ровно один пуш — идемпотентно
    assert asyncio.run(flags.get_flag("morning_brief_sent_20260712", False)) is True


def test_run_skips_when_disabled(monkeypatch):
    flags.reset()  # флаг не выставлен → дефолт settings.morning_brief_enabled = False
    pushed = []

    async def fake_push(text, cfg):
        pushed.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", fake_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    asyncio.run(mb.run(now=datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)))
    assert pushed == []


def test_run_skips_outside_window(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    pushed = []

    async def fake_push(text, cfg):
        pushed.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", fake_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    # 06:00 Бишкек = 00:00 UTC — до окна [9,12)
    asyncio.run(mb.run(now=datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)))
    assert pushed == []
