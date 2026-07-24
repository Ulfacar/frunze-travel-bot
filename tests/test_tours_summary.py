"""Еженедельная тур-сводка владельцу: честные факты + ручные продажи отдельно от AI-оценки."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.config import ManagerConfig
from app.core import flags
from app.core import tours_summary as ts

NOW = datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc)   # понедельник, 10:00 Bishkek → в окне


@dataclass
class Conv:
    funnel: str = "tours"
    user_id: str = "frunze_tours:996700111"
    stage: str = "qualification"
    outcome: str = ""
    outcome_inferred: str = ""
    archived: bool = False
    intercepted: bool = False
    assigned_to: str = ""
    last_message_at: datetime = NOW
    last_sender: str = "client"
    qualification: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)


def _s(convs, now=NOW):
    return ts.build_tours_summary(convs, now)


def test_counts_only_tour_leads():
    convs = [Conv(funnel="tours"), Conv(funnel="visa"), Conv(funnel="tours")]
    assert _s(convs)["total"] == 2                     # визы не считаются


def test_manual_sale_is_the_numerator_not_ai():
    """Продано = ТОЛЬКО ручной won; AI-оценка отдельно, не в числителе."""
    convs = [
        Conv(outcome="won"),                            # ручная продажа — считается
        Conv(outcome="", outcome_inferred="won"),       # AI думает «продал» — НЕ в продажи
        Conv(outcome=""),                               # без отметки
    ]
    s = _s(convs)
    assert s["sold_manual"] == 1                        # только ручной
    assert s["ai_won_estimate"] == 1                    # AI-оценка отдельной цифрой
    assert s["total"] == 3
    assert s["conversion_pct"] == round(100 * 1 / 3, 1)


def test_reached_office_counts_office_and_manager_stages():
    convs = [Conv(stage="office"), Conv(stage="manager"), Conv(stage="qualification")]
    assert _s(convs)["reached_office"] == 2


def test_top_destinations():
    convs = [Conv(qualification={"destination": "Анталья"}),
             Conv(qualification={"destination": "Анталья"}),
             Conv(qualification={"destination": "Дубай"})]
    s = _s(convs)
    assert s["top_destinations"][0] == ("Анталья", 2)


def test_render_marks_ai_estimate_as_not_confirmed():
    convs = [Conv(outcome="won"), Conv(outcome_inferred="won")]
    text = ts.render_tours_summary(_s(convs))
    assert "Продано (отметил менеджер): 1" in text
    assert "не подтверждено" in text.lower() or "оценка" in text.lower()


def test_stale_and_archived_excluded():
    convs = [Conv(last_message_at=NOW - timedelta(days=10)),   # старше 7 дней
             Conv(archived=True),                              # архив
             Conv()]                                           # свежий
    assert _s(convs)["total"] == 1


# --- джоба: флаг, окно, получатель, идемпотентность ---

def _run_case(body, monkeypatch, *, convs=None, managers=None):
    async def _main():
        flags.reset()

        class _Store:
            async def all_conversations(self):
                return convs or []
        monkeypatch.setattr("app.integrations.panel.store.get_conversation_store",
                            lambda: _Store())
        monkeypatch.setattr(ts.settings, "managers", managers if managers is not None else [
            ManagerConfig(login="grisha", name="Гриша", admin=True, telegram_chat_id="900"),
        ], raising=False)
        monkeypatch.setattr("app.core.calendar_brief.settings.telegram_bot_token", "tok",
                            raising=False)
        sent = []
        async def fake_push(token, chat_id, text):
            sent.append((chat_id, text)); return True
        monkeypatch.setattr("app.core.calendar_brief._push_telegram", fake_push)
        try:
            await body(sent)
        finally:
            flags.reset()
    asyncio.run(_main())


def test_flag_off_sends_nothing(monkeypatch):
    async def body(sent):
        await ts.run(NOW)
        assert sent == []
    _run_case(body, monkeypatch, convs=[Conv(outcome="won")])


def test_flag_on_sends_to_owner(monkeypatch):
    async def body(sent):
        await flags.set_flag("tours_summary_enabled", True)
        await ts.run(NOW)
        assert len(sent) == 1 and sent[0][0] == "900"
        assert "Туры за неделю" in sent[0][1]
    _run_case(body, monkeypatch, convs=[Conv(outcome="won"), Conv()])


def test_non_admin_manager_not_a_recipient(monkeypatch):
    async def body(sent):
        await flags.set_flag("tours_summary_enabled", True)
        await ts.run(NOW)
        assert sent == []                                # у обычного менеджера сводку не шлём
    _run_case(body, monkeypatch, convs=[Conv()], managers=[
        ManagerConfig(login="ademi", name="Адеми", admin=False, telegram_chat_id="111")])


def test_wrong_weekday_no_send(monkeypatch):
    tuesday = NOW + timedelta(days=1)
    async def body(sent):
        await flags.set_flag("tours_summary_enabled", True)
        await ts.run(tuesday)                            # вторник — не день отправки
        assert sent == []
    _run_case(body, monkeypatch, convs=[Conv()])


def test_idempotent_per_week(monkeypatch):
    async def body(sent):
        await flags.set_flag("tours_summary_enabled", True)
        await ts.run(NOW)
        await ts.run(NOW)                                # второй тик той же недели
        assert len(sent) == 1
    _run_case(body, monkeypatch, convs=[Conv()])
