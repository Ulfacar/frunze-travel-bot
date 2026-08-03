"""Sprint 1: personal calendar Morning Brief (per-manager). Time/telegram/DB injected."""
import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import ManagerConfig
from app.core import calendar_brief as cb
from app.core import flags
from app.domain.calendar_tasks import CalendarTaskService
from app.domain.models import Contact

NOW = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)   # 10:00 Bishkek → inside [9,12)
TODAY = date(2026, 7, 20)


@dataclass
class Task:
    kind: str
    scheduled_at: datetime | None = None
    priority: str = "normal"
    status: str = "planned"
    user_id: str = "getvisa:996700111"
    comment: str = ""
    ai_summary: str = ""
    direction: str = "visa"


@dataclass
class Conv:
    bot_id: str = "getvisa"
    user_id: str = "getvisa:996700111222"
    channel: str = "whatsapp"
    funnel: str = "visa"
    outcome: str = ""
    assigned_to: str = ""
    intercepted: bool = False
    last_sender: str = "client"
    last_message_at: datetime = NOW
    qualification: dict = field(default_factory=dict)
    estimated_value: float | None = None
    estimated_value_currency: str = ""
    readiness_reason: str = ""


class _Store:
    def __init__(self, convs):
        self._convs = convs

    async def all_conversations_light(self):
        return self._convs


# --- pure builder / render ----------------------------------------------------

def test_build_and_render_contains_tasks_and_night():
    tasks = [Task("call", scheduled_at=datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
                  comment="перезвонить", ai_summary="ждёт визу в Дубай")]
    night = [Conv(qualification={"name": "Асель"})]
    brief = cb.build_manager_brief("medina", "Медина", tasks, night, NOW)
    assert brief["task_count"] == 1 and brief["night_count"] == 1
    text = cb.render_manager_brief_text(brief, base_url="https://p.kg")
    assert "📅 План" in text and "перезвонить" in text and "14:00" in text  # 08:00 UTC = 14:00 Bishkek
    assert "ждёт визу в Дубай" in text
    assert "🌙 Ночные заявки" in text and "Асель" in text
    assert "https://p.kg/admin/conversation/getvisa:996700111" in text


def test_brief_gives_a_dialable_number_and_says_wait_once():
    """Бриф читают с телефона: по номеру звонят тапом, «ждёт» не должно двоиться."""
    tasks = [Task("call", scheduled_at=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
                  user_id="frunze_tours:996553333424", comment="перезвонить")]
    night = [Conv(user_id="frunze_tours:996555754852",
                  last_message_at=datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc))]
    text = cb.render_manager_brief_text(
        cb.build_manager_brief("sezim", "Сезим", tasks, night, NOW))
    assert "+996 553 33 34 24" in text            # задача — с полным номером
    assert "+996 555 75 48 52" in text            # ночная заявка — тоже
    assert "Без имени" not in text                # мусорная подпись вместо номера
    assert "ждёт ждёт" not in text and "ждёт 4 ч" in text


# --- run: flags / delivery ----------------------------------------------------

def _domain_sm():
    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False},
                                 poolclass=StaticPool)
    return engine


async def _prepare(engine):
    from app.domain.models import DomainBase
    async with engine.begin() as conn:
        await conn.run_sync(DomainBase.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _run_case(body, monkeypatch, *, convs=None, managers=None):
    async def _main():
        flags.reset()
        engine = _domain_sm()
        sm = await _prepare(engine)
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            await CalendarTaskService.create(s, manager_id="medina", direction="visa",
                                             kind="call", scheduled_date=TODAY, contact_id=c.id,
                                             user_id="getvisa:996700111", comment="звонок")
            await s.commit()
        monkeypatch.setattr("app.integrations.panel.store.get_conversation_store",
                            lambda: _Store(convs if convs is not None else []))
        monkeypatch.setattr(cb.settings, "managers", managers if managers is not None else [
            ManagerConfig(login="medina", name="Медина", telegram_chat_id="111"),
        ], raising=False)
        monkeypatch.setattr(cb.settings, "telegram_bot_token", "tok", raising=False)
        sent = []
        async def fake_push(token, chat_id, text):
            sent.append((chat_id, text)); return True
        monkeypatch.setattr(cb, "_push_telegram", fake_push)
        try:
            await body(sm, sent)
        finally:
            flags.reset()
            await engine.dispose()
    asyncio.run(_main())


def test_flag_off_sends_nothing(monkeypatch):
    async def body(sm, sent):
        await cb.run(NOW, sessionmaker=sm)          # calendar_brief_enabled default OFF
        assert sent == []
    _run_case(body, monkeypatch)


def test_flag_on_sends_personal_brief(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert len(sent) == 1
        chat_id, text = sent[0]
        assert chat_id == "111" and "звонок" in text
    _run_case(body, monkeypatch)


def test_idempotent_per_manager(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        await cb.run(NOW, sessionmaker=sm)          # second run same day
        assert len(sent) == 1                        # sent once
    _run_case(body, monkeypatch)


def test_manager_without_chat_id_skipped(monkeypatch):
    managers = [ManagerConfig(login="medina", name="Медина", telegram_chat_id=""),
                ManagerConfig(login="eliza", name="Элиза", telegram_chat_id="222")]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        # medina (no chat id) skipped; eliza gets a brief (empty tasks but night/greeting)
        assert [c for c, _ in sent] == ["222"]
    _run_case(body, monkeypatch, managers=managers)


def test_outside_window_no_send(monkeypatch):
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        early = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)   # 06:00 Bishkek < 09:00
        await cb.run(early, sessionmaker=sm)
        assert sent == []
    _run_case(body, monkeypatch)


def _text_for(sent, chat_id):
    return next((t for c, t in sent if c == chat_id), "")


_TEAM = [ManagerConfig(login="medina", name="Медина", telegram_chat_id="111"),
         ManagerConfig(login="eliza", name="Элиза", telegram_chat_id="222"),
         ManagerConfig(login="boss", name="Босс", telegram_chat_id="999", admin=True)]


def test_unassigned_lead_only_to_admin_not_managers(monkeypatch):
    """Shared visa bot + 2 managers + 1 UNASSIGNED overnight lead → absent in both
    personal briefs, present once in the admin brief under 'Требуют распределения'."""
    convs = [Conv(bot_id="getvisa", user_id="getvisa:1", assigned_to="",
                  qualification={"name": "НужноРаспределить"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert "НужноРаспределить" not in _text_for(sent, "111")   # medina
        assert "НужноРаспределить" not in _text_for(sent, "222")   # eliza
        admin_text = _text_for(sent, "999")
        assert "Требуют распределения" in admin_text
        assert admin_text.count("НужноРаспределить") == 1           # once, no duplication
    _run_case(body, monkeypatch, convs=convs, managers=_TEAM)


def test_assigned_lead_only_to_owner(monkeypatch):
    """An assigned overnight lead appears only in its owner's brief — not peers, not admin."""
    convs = [Conv(bot_id="getvisa", user_id="getvisa:1", assigned_to="medina",
                  qualification={"name": "КлиентМедины"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert "КлиентМедины" in _text_for(sent, "111")             # owner medina
        assert "КлиентМедины" not in _text_for(sent, "222")         # peer eliza
        assert "КлиентМедины" not in _text_for(sent, "999")         # admin (it's assigned)
    _run_case(body, monkeypatch, convs=convs, managers=_TEAM)


# --- список на обзвон: свежесть, дедуп, сортировка, wa.me -----------------------

def test_night_sorted_longest_wait_first():
    """Дольше всех ждёт — первым (самый горячий не теряется под капом)."""
    from datetime import timedelta
    fresh = Conv(user_id="getvisa:996700111222", last_message_at=NOW - timedelta(minutes=30),
                 qualification={"name": "Недавний"})
    old = Conv(user_id="getvisa:996700333444", last_message_at=NOW - timedelta(hours=8),
               qualification={"name": "Давнийждёт"})
    brief = cb.build_manager_brief("medina", "Медина", [], [fresh, old], NOW)
    text = cb.render_manager_brief_text(brief)
    assert text.index("Давнийждёт") < text.index("Недавний")     # дольше ждёт — выше


def test_night_has_whatsapp_link():
    """У ночного клиента есть прямая wa.me-ссылка на его номер."""
    night = [Conv(user_id="getvisa:996700111222", qualification={"name": "Клиент"})]
    brief = cb.build_manager_brief("medina", "Медина", [], night, NOW)
    text = cb.render_manager_brief_text(brief)
    assert "https://wa.me/996700111222" in text


def test_stale_lead_excluded_from_night(monkeypatch):
    """Лид с активностью старше окна свежести не попадает в «ночные» (не весь пайплайн)."""
    from datetime import timedelta
    convs = [Conv(user_id="getvisa:996700111222", assigned_to="medina",
                  last_message_at=NOW - timedelta(hours=20),   # >16ч lookback
                  qualification={"name": "СтарыйЛид"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert "СтарыйЛид" not in _text_for(sent, "111")
    _run_case(body, monkeypatch, convs=convs)


def test_fresh_lead_included_in_night(monkeypatch):
    convs = [Conv(user_id="getvisa:996700111222", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "СвежийЛид"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert "СвежийЛид" in _text_for(sent, "111")
    _run_case(body, monkeypatch, convs=convs)


def test_lead_with_task_deduped_from_night(monkeypatch):
    """Клиент, на кого уже стоит задача сегодня, не дублируется в «ночных»."""
    # Харнесс сеет задачу для medina на user_id="getvisa:996700111".
    convs = [Conv(user_id="getvisa:996700111", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "УжеСЗадачей"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        text = _text_for(sent, "111")
        assert "🌙" not in text or "УжеСЗадачей" not in text     # в ночных его нет
    _run_case(body, monkeypatch, convs=convs)


# --- Шаг 1: бот → авто-задача звонка на ночные лиды (флаг calendar_autotask) --------

async def _bot_tasks_today(sm, manager_id):
    async with sm() as s:
        rows = await CalendarTaskService.list_for_manager(
            s, manager_id, date_from=TODAY, date_to=TODAY, include_terminal=True)
    return [t for t in rows if (t.created_by or "") == "bot"]


def test_autotask_off_creates_no_bot_task(monkeypatch):
    """Бриф включён, autotask ВЫКЛ → бот не создаёт задач (поведение прежнее)."""
    convs = [Conv(user_id="getvisa:996700111222", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "СвежийЛид"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert await _bot_tasks_today(sm, "medina") == []
    _run_case(body, monkeypatch, convs=convs)


def test_autotask_on_materializes_call_task_for_night_lead(monkeypatch):
    """autotask ВКЛ → на owner-routed ночной лид появляется задача-звонок created_by='bot'."""
    convs = [Conv(user_id="getvisa:996700111222", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "СвежийЛид"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await flags.set_flag("calendar_autotask_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        bot_tasks = await _bot_tasks_today(sm, "medina")
        assert len(bot_tasks) == 1
        t = bot_tasks[0]
        assert t.kind == "call" and t.user_id == "getvisa:996700111222"
        assert t.manager_id == "medina" and t.scheduled_date == TODAY
    _run_case(body, monkeypatch, convs=convs)


def test_autotask_skips_lead_that_already_has_task(monkeypatch):
    """Лид, у кого уже есть задача сегодня, дедупнут из «ночных» → бот не создаёт вторую."""
    # Харнесс сеет НЕ-bot задачу на user_id="getvisa:996700111".
    convs = [Conv(user_id="getvisa:996700111", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "УжеСЗадачей"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await flags.set_flag("calendar_autotask_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert await _bot_tasks_today(sm, "medina") == []
    _run_case(body, monkeypatch, convs=convs)


def test_autotask_idempotent_second_run_same_day(monkeypatch):
    """Второй прогон в тот же день не плодит дубли (sent_key гейтит повторную доставку)."""
    convs = [Conv(user_id="getvisa:996700111222", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "СвежийЛид"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await flags.set_flag("calendar_autotask_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        await cb.run(NOW, sessionmaker=sm)
        assert len(await _bot_tasks_today(sm, "medina")) == 1
    _run_case(body, monkeypatch, convs=convs)


def test_autotask_handles_foreign_whatsapp_number(monkeypatch):
    """WhatsApp отдаёт полный E.164 без «+» — общее правило звало такой номер ambiguous,
    и каждое утро 1–3 иностранных клиента молча выпадали из списка обзвона (прод, 03.08:
    Германия, Польша, Турция). Клиент в переписке есть, а в работе менеджера — нет."""
    convs = [Conv(bot_id="frunze_tours_sezim", user_id="frunze_tours_sezim:4915781345793",
                  channel="whatsapp", funnel="tours", assigned_to="medina",
                  last_message_at=NOW, qualification={"name": "Германия"})]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await flags.set_flag("calendar_autotask_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        tasks = await _bot_tasks_today(sm, "medina")
        assert len(tasks) == 1
        assert tasks[0].user_id == "frunze_tours_sezim:4915781345793"
    _run_case(body, monkeypatch, convs=convs)


def test_autotask_still_rejects_a_number_that_is_not_one(monkeypatch):
    """Послабление даём формату, а не мусору: короткий обрывок номером не становится."""
    convs = [Conv(bot_id="frunze_tours", user_id="frunze_tours:abc", channel="whatsapp",
                  funnel="tours", assigned_to="medina", last_message_at=NOW)]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await flags.set_flag("calendar_autotask_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        assert await _bot_tasks_today(sm, "medina") == []      # пропущен, бриф не упал
        assert len(sent) == 1
    _run_case(body, monkeypatch, convs=convs)


# --- сводка владельца: оба направления в одном утреннем сообщении ----------------

@dataclass
class DigestTask:
    """Задача для сводки: важны направление, владелец и дата (просрочка)."""
    direction: str = "visa"
    manager_id: str = "medina"
    scheduled_date: date = TODAY


def test_owner_digest_counts_visas_and_tours_separately():
    """Гриша/Даулет просили видеть утром ОБА направления: визы и туры считаются
    раздельно — открытые, свежие за ночь, ждущие ответа и бесхозные."""
    from datetime import timedelta
    convs = [
        Conv(bot_id="getvisa", funnel="visa", user_id="getvisa:1", assigned_to="medina"),
        Conv(bot_id="getvisa", funnel="visa", user_id="getvisa:2", assigned_to=""),
        Conv(bot_id="frunze_tours_sezim", funnel="tours", user_id="frunze_tours_sezim:3",
             assigned_to="aisina", last_message_at=NOW - timedelta(minutes=30)),
        # Старый висяк: ждёт больше суток и в «новых за ночь» не считается.
        Conv(bot_id="frunze_tours_sezim", funnel="tours", user_id="frunze_tours_sezim:4",
             assigned_to="", last_message_at=NOW - timedelta(hours=50)),
        # Закрытый лид в сводку не попадает вообще.
        Conv(bot_id="getvisa", funnel="visa", user_id="getvisa:5", outcome="won"),
    ]
    digest = cb.build_owner_digest(convs, [], NOW, lookback_hours=14, day=TODAY)
    by_key = {d["key"]: d for d in digest["directions"]}
    assert [d["key"] for d in digest["directions"]] == ["visa", "tours"]   # визы первыми
    assert by_key["visa"]["open"] == 2 and by_key["visa"]["unassigned"] == 1
    assert by_key["tours"]["open"] == 2 and by_key["tours"]["unassigned"] == 1
    assert by_key["visa"]["fresh"] == 2          # обе визовые свежие
    assert by_key["tours"]["fresh"] == 1         # висяк 50 ч — не «за ночь»
    assert by_key["tours"]["waiting"] == 2 and by_key["tours"]["waiting_stale"] == 1


def test_owner_digest_splits_today_tasks_from_overdue():
    """Просрочка (активная задача со вчера) считается отдельно от сегодняшних."""
    from datetime import timedelta
    tasks = [DigestTask(direction="visa", manager_id="medina"),
             DigestTask(direction="visa", manager_id="eliza",
                        scheduled_date=TODAY - timedelta(days=2)),
             DigestTask(direction="tours", manager_id="aisina")]
    digest = cb.build_owner_digest([], tasks, NOW, lookback_hours=14, day=TODAY)
    by_key = {d["key"]: d for d in digest["directions"]}
    assert by_key["visa"]["tasks_today"] == 1 and by_key["visa"]["tasks_overdue"] == 1
    assert by_key["tours"]["tasks_today"] == 1 and by_key["tours"]["tasks_overdue"] == 0
    assert dict(by_key["visa"]["by_manager"]) == {"medina": 1, "eliza": 1}


def test_owner_digest_empty_renders_nothing():
    """Считать нечего → пустая строка, заголовок впустую не шлём."""
    assert cb.render_owner_digest_text(
        cb.build_owner_digest([], [], NOW, lookback_hours=14, day=TODAY)) == ""


def test_owner_digest_only_for_admin(monkeypatch):
    """Сводка по компании уходит только full-admin; у менеджеров её в брифе нет."""
    convs = [Conv(bot_id="getvisa", funnel="visa", user_id="getvisa:1", assigned_to="medina"),
             Conv(bot_id="frunze_tours_sezim", funnel="tours",
                  user_id="frunze_tours_sezim:2", assigned_to="")]
    async def body(sm, sent):
        await flags.set_flag("calendar_brief_enabled", True)
        await cb.run(NOW, sessionmaker=sm)
        admin_text = _text_for(sent, "999")
        assert "По компании" in admin_text
        assert "Визы" in admin_text and "Туры" in admin_text     # оба направления
        assert "По компании" not in _text_for(sent, "111")       # медина
        assert "По компании" not in _text_for(sent, "222")       # элиза
    _run_case(body, monkeypatch, convs=convs, managers=_TEAM)
