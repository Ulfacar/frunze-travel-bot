"""Тесты авто-исхода через LLM (app/core/outcome_infer.py). Пасс gated OFF по умолчанию."""
import asyncio
from datetime import datetime, timedelta, timezone

from app.core import outcome_infer
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import ConversationView, MessageView


def _cv(uid, outcome="", inferred="", hours_stale=48, msgs=1):
    now = datetime.now(timezone.utc)
    return ConversationView(
        user_id=uid, funnel="tours", outcome=outcome, outcome_inferred=inferred,
        last_message_at=now - timedelta(hours=hours_stale),
        messages=[MessageView("client", "текст", now) for _ in range(msgs)])


# ---------- _parse ----------

def test_parse_label_and_reason():
    assert outcome_infer._parse("WON\nоплатил картой") == ("won", "оплатил картой")


def test_parse_bare_label():
    assert outcome_infer._parse("GHOSTED") == ("ghosted", "")


def test_parse_unknown_defaults_active():
    assert outcome_infer._parse("непонятно что тут") == ("active", "")
    assert outcome_infer._parse("") == ("active", "")


def test_parse_punctuation_only_first_line_does_not_crash():
    # регресс (codex-reviewer MAJOR): «!!!»/«...» первой строкой не должны падать IndexError
    assert outcome_infer._parse("!!!") == ("active", "")
    assert outcome_infer._parse("...\nWON") == ("active", "WON")


# ---------- _candidates ----------

def test_candidates_selection_rules():
    now = datetime.now(timezone.utc)
    convs = [
        _cv("stale_new"),                          # кандидат
        _cv("manual_won", outcome="won"),          # ручной финал → пропуск
        _cv("already", inferred="lost"),           # уже классифицирован → пропуск
        _cv("fresh", hours_stale=2),               # свежий → пропуск
        _cv("nomsg", msgs=0),                      # нет сообщений → пропуск
    ]
    picked = [c.user_id for c in outcome_infer._candidates(convs, now, stale_hours=24, limit=10)]
    assert picked == ["stale_new"]


def test_candidates_reevaluates_active_but_freezes_terminal():
    """codex-review MAJOR: 'active' не терминальный → переоцениваем; won/lost/ghosted — заморожены.
    Приоритет — сперва ни разу не размеченным."""
    now = datetime.now(timezone.utc)
    convs = [
        _cv("fresh_active", inferred="active", hours_stale=30),   # active → кандидат (переоценка)
        _cv("frozen_ghosted", inferred="ghosted", hours_stale=99),  # терминал → пропуск
        _cv("never_judged", inferred="", hours_stale=40),          # "" → кандидат, приоритет
    ]
    picked = [c.user_id for c in outcome_infer._candidates(convs, now, stale_hours=24, limit=10)]
    assert "frozen_ghosted" not in picked
    assert picked == ["never_judged", "fresh_active"]             # не-размеченный первым


def test_run_stops_when_budget_capped_mid_sweep(monkeypatch):
    """codex-review MAJOR: бюджет исчерпался в процессе — sweep не жжёт вызовы дальше."""
    panel_store._memory_store._conv.clear()
    from app.core import flags
    flags.reset()
    outcome_infer._last_run = 0.0
    monkeypatch.setattr("app.config.settings.outcome_infer_enabled", True)

    async def avail():
        return True

    async def capped():
        return True

    async def boom(*a, **k):
        raise AssertionError("не должны классифицировать при исчерпанном бюджете")

    monkeypatch.setattr("app.agent.llm.llm_available", avail)   # прошли пред-цикловую проверку
    monkeypatch.setattr("app.core.budget.hard_capped", capped)  # но в цикле — уже capped
    monkeypatch.setattr("app.agent.llm.chat", boom)

    store = panel_store.get_conversation_store()
    asyncio.run(store.add_message("frunze_tours:oi3", "client", "оплатить", channel="whatsapp", bot_id="frunze_tours"))
    conv = asyncio.run(store.get("frunze_tours:oi3"))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=48)
    asyncio.run(outcome_infer.run())
    assert (asyncio.run(store.get("frunze_tours:oi3")).outcome_inferred or "") == ""


def test_candidates_oldest_first_and_capped():
    now = datetime.now(timezone.utc)
    convs = [_cv("a", hours_stale=30), _cv("b", hours_stale=99), _cv("c", hours_stale=50)]
    picked = [c.user_id for c in outcome_infer._candidates(convs, now, stale_hours=24, limit=2)]
    assert picked == ["b", "c"]                    # старые первыми, кап 2


# ---------- run() с мок-LLM ----------

def test_run_writes_inferred_outcome(monkeypatch):
    panel_store._memory_store._conv.clear()
    from app.core import flags
    flags.reset()
    outcome_infer._last_run = 0.0
    monkeypatch.setattr("app.config.settings.outcome_infer_enabled", True)

    async def fake_available():
        return True

    async def fake_chat(system, messages, **kw):
        return {"content": [{"type": "text", "text": "WON\nприслал чек об оплате"}]}

    monkeypatch.setattr("app.agent.llm.llm_available", fake_available)
    monkeypatch.setattr("app.agent.llm.chat", fake_chat)

    store = panel_store.get_conversation_store()
    uid = "frunze_tours:oi1"
    asyncio.run(store.add_message(uid, "client", "хочу оплатить тур", channel="whatsapp", bot_id="frunze_tours"))
    conv = asyncio.run(store.get(uid))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=48)

    asyncio.run(outcome_infer.run())

    conv = asyncio.run(store.get(uid))
    assert conv.outcome_inferred == "won"
    assert "чек" in conv.outcome_inferred_reason


def test_run_noop_when_disabled(monkeypatch):
    panel_store._memory_store._conv.clear()
    from app.core import flags
    flags.reset()
    outcome_infer._last_run = 0.0
    monkeypatch.setattr("app.config.settings.outcome_infer_enabled", False)
    store = panel_store.get_conversation_store()
    uid = "frunze_tours:oi2"
    asyncio.run(store.add_message(uid, "client", "оплатить", channel="whatsapp", bot_id="frunze_tours"))
    asyncio.run(outcome_infer.run())
    assert (asyncio.run(store.get(uid)).outcome_inferred or "") == ""


# ---------- Разговор, который ведут мимо нас (19.08.2026) ----------

def _cv_unseen(uid, with_reply=False):
    """Диалог, где клиент писал трижды. with_reply=True — наш ответ в истории есть."""
    now = datetime.now(timezone.utc)
    msgs = [MessageView("client", "текст", now) for _ in range(3)]
    if with_reply:
        msgs.insert(1, MessageView("bot", "Здравствуйте!", now))
    return ConversationView(user_id=uid, funnel="tours", outcome="", outcome_inferred="",
                            last_message_at=now - timedelta(hours=48), messages=msgs)


def test_candidates_skip_conversation_without_any_reply_of_ours():
    """Транскрипт из одних клиентских реплик — половина разговора; ИИ решил бы «lost»
    по диалогу, который менеджер вёл с телефона, а эхо до нас не долетело."""
    now = datetime.now(timezone.utc)
    convs = [_cv_unseen("led_past_us"), _cv_unseen("we_replied", with_reply=True)]

    picked = [c.user_id for c in outcome_infer._candidates(convs, now, stale_hours=24, limit=10)]

    assert picked == ["we_replied"]
