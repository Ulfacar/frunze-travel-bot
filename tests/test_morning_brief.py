"""Тесты утреннего «горячего листа» (Фаза 0 календаря звонков).

Чистые функции (build_brief/render_text/формат чека/окно) — без БД и LLM. Джоба run —
через инъекцию времени + memory-флаги: гейтинг, идемпотентность, флаг-только-при-успехе.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from app.core import flags
from app.core import morning_brief as mb
from app.integrations.panel.store import ConversationView

NOW = datetime(2026, 7, 12, 4, 0, tzinfo=timezone.utc)  # 10:00 Бишкек, в окне отправки


def _conv(uid, **kw):
    base = dict(user_id=uid, funnel="tours")
    base.update(kw)
    return ConversationView(**base)


def _waiting(uid, minutes, **kw):
    """green-лид, который ждёт ответа `minutes` (последним писал клиент)."""
    return _conv(uid, readiness_tier="green", last_sender="client",
                 last_message_at=NOW - timedelta(minutes=minutes), **kw)


# ---------------- отбор: build_brief ----------------
def test_build_brief_splits_green_warm_and_excludes():
    convs = [
        _conv("g1", readiness_tier="green"),
        _conv("w1", readiness_tier="warm"),
        _conv("n1", readiness_tier="noise"),            # шум — не в лист
        _conv("i1", readiness_tier="insufficient"),     # мало данных — не в лист
        _conv("won", readiness_tier="green", outcome="won"),        # закрыт
        _conv("asg", readiness_tier="green", assigned_to="sezim"),  # уже у человека
        _conv("itc", readiness_tier="green", intercepted=True),     # ведёт менеджер
    ]
    b = mb.build_brief(convs, NOW)
    assert [c["user_id"] for c in b["green"]] == ["g1"]
    assert [c["user_id"] for c in b["warm"]] == ["w1"]
    assert b["green_count"] == 1 and b["warm_count"] == 1
    assert b["date_label"] == "12.07"


# ---------------- приоритет: ожидание первично, чек тайбрейк ----------------
def test_sort_wait_primary():
    b = mb.build_brief([_waiting("short", 60), _waiting("long", 300)], NOW)
    assert [c["user_id"] for c in b["green"]] == ["long", "short"]  # дольше ждёт → выше


def test_sort_tiebreak_normalized_value_som_vs_usd():
    # оба wait=0 (последним писал бот) → тайбрейк по нормализованному чеку
    usd = _conv("usd", readiness_tier="green", estimated_value=1000, estimated_value_currency="$")
    som = _conv("som", readiness_tier="green", estimated_value=100000, estimated_value_currency="сом")
    b = mb.build_brief([usd, som], NOW)
    # 100000 сом ≈ $1120 > $1000 → som выше (нормализация работает, не сравниваем сырьё)
    assert [c["user_id"] for c in b["green"]] == ["som", "usd"]


# ---------------- чек: единица / неизвестная валюта ----------------
def test_check_shows_unit_and_marks_unknown():
    b = mb.build_brief([
        _conv("a", readiness_tier="green", estimated_value=1500, estimated_value_currency="$"),
        _conv("b", readiness_tier="green", estimated_value=7000, estimated_value_currency=""),
        _conv("c", readiness_tier="green"),  # без чека
    ], NOW)
    by = {c["user_id"]: c for c in b["green"]}
    assert by["a"]["check"] == "1500 $"
    assert by["b"]["check"] == "7000 ?"      # неизвестную валюту метим, не выдаём за доллары
    assert by["c"]["check"] == ""


def test_wait_label_formatting():
    b = mb.build_brief([_waiting("h", 200), _waiting("m", 30)], NOW)
    by = {c["user_id"]: c for c in b["green"]}
    assert by["h"]["wait_label"] == "ждёт 3 ч"
    assert by["m"]["wait_label"] == "ждёт 30 мин"


# ---------------- рендер текста ----------------
def test_render_text_lists_lead():
    txt = mb.render_text(mb.build_brief([
        _waiting("g1", 120, estimated_value=1500, estimated_value_currency="$",
                 qualification={"name": "Айгерим", "destination": "Анталья", "dates": "10-17 авг"}),
    ], NOW))
    assert "🔥 Горячий лист · 12.07" in txt
    assert "Айгерим" in txt and "1500 $" in txt and "Анталья" in txt
    assert "вылет 10-17 авг" in txt and "ждёт 2 ч" in txt


def test_render_text_limit_folds_tail():
    convs = [_waiting(f"g{i}", 100 + i) for i in range(5)]
    txt = mb.render_text(mb.build_brief(convs, NOW), limit=2)
    assert "…и ещё 3" in txt          # 5 лидов, лимит 2 → хвост 3
    assert "/admin/morning" in txt


def test_render_text_empty_is_calm():
    assert "спокойное утро" in mb.render_text(mb.build_brief([], NOW))


# ---------------- окно отправки ----------------
def test_in_send_window():
    class _Cfg:
        morning_brief_hour = 9
    cfg = _Cfg()
    assert mb._in_send_window(9, cfg) and mb._in_send_window(11, cfg)
    assert not mb._in_send_window(8, cfg)       # рано
    assert not mb._in_send_window(12, cfg)      # окно [9, 12)


# ---------------- джоба: гейтинг, идемпотентность, флаг-при-успехе ----------------
def _patch_store(monkeypatch, convs):
    class _Store:
        async def all_conversations_light(self):
            return list(convs)
    monkeypatch.setattr("app.integrations.panel.store.get_conversation_store", lambda: _Store())


def _configure_telegram(monkeypatch, on=True):
    monkeypatch.setattr(mb.settings, "managers_telegram_chat_id", "grp" if on else "", raising=False)
    monkeypatch.setattr(mb.settings, "managers_telegram_bot_token", "tok" if on else "", raising=False)
    monkeypatch.setattr(mb.settings, "telegram_bot_token", "", raising=False)  # без легаси-фолбэка


def test_run_sends_once_per_day(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    _configure_telegram(monkeypatch, on=True)
    pushed = []

    async def fake_push(text, cfg):
        pushed.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", fake_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    asyncio.run(mb.run(now=NOW))
    asyncio.run(mb.run(now=NOW))   # второй прогон того же дня — не должен слать снова
    assert len(pushed) == 1
    assert asyncio.run(flags.get_flag("morning_brief_sent_20260712", False)) is True


def test_run_does_not_set_flag_on_push_failure(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    _configure_telegram(monkeypatch, on=True)
    pushed = []

    async def failing_push(text, cfg):
        pushed.append(text)
        return False   # доставка не удалась
    monkeypatch.setattr(mb, "_push_telegram", failing_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    asyncio.run(mb.run(now=NOW))
    assert len(pushed) == 1  # попытка была
    # флаг НЕ выставлен → джоба повторит на следующем тике (окно ещё открыто)
    assert asyncio.run(flags.get_flag("morning_brief_sent_20260712", False)) is False


def test_run_sets_flag_when_telegram_off(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    _configure_telegram(monkeypatch, on=False)   # chat_id/токен пусты — слать некуда
    called = []

    async def spy_push(text, cfg):
        called.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", spy_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])

    asyncio.run(mb.run(now=NOW))
    assert called == []  # пуш даже не пытались — Telegram не настроен
    # флаг всё равно ставим: слать нечего, экран /admin/morning покрывает
    assert asyncio.run(flags.get_flag("morning_brief_sent_20260712", False)) is True


def test_run_skips_when_disabled(monkeypatch):
    flags.reset()  # флаг не выставлен → дефолт settings.morning_brief_enabled = False
    _configure_telegram(monkeypatch, on=True)
    pushed = []
    monkeypatch.setattr(mb, "_push_telegram",
                        lambda text, cfg: pushed.append(text) or asyncio.sleep(0))
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])
    asyncio.run(mb.run(now=NOW))
    assert pushed == []


def test_run_skips_outside_window(monkeypatch):
    flags.reset()
    asyncio.run(flags.set_flag("morning_brief_enabled", True))
    _configure_telegram(monkeypatch, on=True)
    pushed = []

    async def fake_push(text, cfg):
        pushed.append(text)
        return True
    monkeypatch.setattr(mb, "_push_telegram", fake_push)
    _patch_store(monkeypatch, [_conv("g1", readiness_tier="green")])
    # 06:00 Бишкек = 00:00 UTC — до окна [9,12)
    asyncio.run(mb.run(now=datetime(2026, 7, 12, 0, 0, tzinfo=timezone.utc)))
    assert pushed == []
