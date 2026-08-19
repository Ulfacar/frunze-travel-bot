from datetime import datetime, timedelta, timezone

from app.core.leadstate import is_noise, is_silent
from app.integrations.panel.store import ConversationView, MessageView


class _Cfg:
    followup_after_hours = 24
    followup_max_pings = 2
    followup_interval_hours = 84
    noise_stale_days = 3


def _conv(uid="u1", **kw):
    base = dict(
        user_id=uid,
        channel="whatsapp",
        bot_id="frunze_tours",
        chat_id=f"{uid}@c.us",
        funnel="tours",
        stage="qualification",
        last_sender="client",
        last_text="хочу тур",
        last_message_at=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )
    base.update(kw)
    return ConversationView(**base)


def test_is_noise_marks_ad_link_greeting_but_not_qualified_lead():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    spam = _conv("spam", stage="greeting", last_text="https://instagram.com/promo")
    real = _conv("real", stage="greeting", last_text="https://instagram.com/profile",
                 qualification={"name": "Алия"})

    assert is_noise(spam, now, _Cfg()) is True
    assert is_noise(real, now, _Cfg()) is False


def test_is_noise_marks_stale_empty_greeting_without_bot_or_manager_messages():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    stale = _conv("stale", stage="greeting", last_text="добрый день",
                  last_message_at=now - timedelta(days=4),
                  messages=[MessageView("client", "добрый день", now - timedelta(days=4))])
    answered = _conv("answered", stage="greeting", last_text="Здравствуйте",
                     last_sender="bot", last_message_at=now - timedelta(days=4),
                     messages=[
                         MessageView("client", "добрый день", now - timedelta(days=4)),
                         MessageView("bot", "Здравствуйте", now - timedelta(days=4)),
                     ])

    assert is_noise(stale, now, _Cfg()) is True
    assert is_noise(answered, now, _Cfg()) is False


def test_is_silent_broad_stuck_leads_and_exclusions():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(hours=30)
    fresh = now - timedelta(hours=2)

    assert is_silent(_conv("client-last", last_sender="client", last_message_at=old), now, _Cfg()) is True
    assert is_silent(_conv("bot-last", last_sender="bot", last_message_at=old), now, _Cfg()) is True
    assert is_silent(_conv("fresh", last_message_at=fresh), now, _Cfg()) is False
    assert is_silent(_conv("manager", stage="manager", last_message_at=old), now, _Cfg()) is False
    # Прошедших консультацию/офис теперь ДОЖИМАЕМ (правка 06.07) — раньше было False.
    assert is_silent(_conv("office", stage="office", last_message_at=old), now, _Cfg()) is True
    assert is_silent(_conv("won", outcome="won", last_message_at=old), now, _Cfg()) is False
    assert is_silent(_conv("spam", stage="greeting", last_text="https://instagram.com/ad",
                           last_message_at=old), now, _Cfg()) is False


def test_followup_cadence_limits_and_interval():
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    old = now - timedelta(hours=30)           # молчит 30ч (> 24ч первого порога, < 84ч интервала)
    long_ago = now - timedelta(hours=100)     # молчит 100ч (> 84ч интервала повторного пинга)

    # Уже пингован 1 раз: 30ч < интервала 84ч → ещё рано.
    assert is_silent(_conv("p1-early", followup_count=1, last_message_at=old), now, _Cfg()) is False
    # Пингован 1 раз, но прошло 100ч > интервала → снова пора.
    assert is_silent(_conv("p1-due", followup_count=1, last_message_at=long_ago), now, _Cfg()) is True
    # Исчерпан лимит (2 пинга) → больше не дожимаем, даже если давно молчит.
    assert is_silent(_conv("p2-max", followup_count=2, last_message_at=long_ago), now, _Cfg()) is False
    # Legacy: старый булев followup_sent считается как 1 пинг (совместимость).
    assert is_silent(_conv("legacy-early", followup_sent=True, last_message_at=old), now, _Cfg()) is False
    assert is_silent(_conv("legacy-due", followup_sent=True, last_message_at=long_ago), now, _Cfg()) is True


# --- Предохранитель «разговор ведут без нас» (19.08.2026) -------------------------------
#
# Замер прода 19.08: на визовом канале 385 из 681 диалога за 30 дней не имели НИ ОДНОГО
# нашего сообщения — при том что клиент в них отвечает на вопросы («1. На визы шенген не
# подавала  2. ИП...»), то есть менеджер с ним работал, а эхо ответа до нас не долетело.
# До 11.08 (пока не слушали outgoing_message_api) таких было 72.9%, после — 25.2%.
# Для дожима такой диалог выглядит как «клиент замолчал» — и бот полез бы писать человеку,
# которого уже ведёт живой менеджер. Ниже — гейт на это поведение.

def test_is_silent_skips_conversation_where_our_replies_never_arrived():
    """Клиент писал много раз, наших реплик нет ни одной — значит мы просто не видим ответы."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    started = now - timedelta(days=3)
    unseen = _conv("unseen", last_message_at=now - timedelta(hours=48), messages=[
        MessageView("client", "здравствуйте, нужна виза в Италию", started),
        MessageView("client", "1. не подавала  2. ИП, сдаю недвижимость", started + timedelta(hours=2)),
        MessageView("client", "есть возможность до 20 сентября?", started + timedelta(hours=5)),
    ])

    assert is_silent(unseen, now, _Cfg()) is False


def test_is_silent_still_fires_when_we_actually_replied():
    """Наш ответ в истории есть — значит тишина настоящая, дожим работает как раньше."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    started = now - timedelta(days=3)
    answered = _conv("answered", last_message_at=now - timedelta(hours=48), messages=[
        MessageView("client", "здравствуйте, нужна виза в Италию", started),
        MessageView("bot", "Здравствуйте! Подскажите даты поездки", started + timedelta(minutes=1)),
        MessageView("client", "в сентябре", started + timedelta(hours=2)),
        MessageView("client", "ещё думаю", started + timedelta(hours=5)),
    ])

    assert is_silent(answered, now, _Cfg()) is True


def test_is_silent_still_fires_on_short_unanswered_lead():
    """Одно-два сообщения без ответа — это настоящий брошенный лид, ради него дожим и живёт."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    dropped = _conv("dropped", last_message_at=now - timedelta(hours=48), messages=[
        MessageView("client", "здравствуйте, сколько стоит виза?", now - timedelta(hours=48)),
    ])

    assert is_silent(dropped, now, _Cfg()) is True


def test_unseen_guard_stays_quiet_without_loaded_history():
    """Без загруженной истории судить не о чем — поведение прежнее, сводки не ломаем."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    light = _conv("light", last_message_at=now - timedelta(hours=48))

    assert is_silent(light, now, _Cfg()) is True


def test_is_noise_does_not_archive_conversation_led_past_us():
    """Кнопка «архивировать шум» не должна прятать диалог, который менеджер уже ведёт."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    started = now - timedelta(days=6)
    unseen = _conv("unseen-noise", stage="greeting", last_text="есть возможность до 20 сентября?",
                   last_message_at=now - timedelta(days=5), messages=[
        MessageView("client", "https://instagram.com/p/xxx подробнее про визу?", started),
        MessageView("client", "туристическая, в Италию", started + timedelta(hours=2)),
        MessageView("client", "есть возможность до 20 сентября?", started + timedelta(hours=5)),
    ])

    assert is_noise(unseen, now, _Cfg()) is False


def test_is_noise_still_archives_repeated_ad_links():
    """Настоящий мусор — повтор рекламной ссылки — чистится как раньше."""
    now = datetime(2026, 6, 30, 12, 0, tzinfo=timezone.utc)
    started = now - timedelta(days=6)
    spam = _conv("spam-many", stage="greeting", last_text="https://fb.me/xxx",
                 last_message_at=now - timedelta(days=5), messages=[
        MessageView("client", "https://fb.me/xxx", started),
        MessageView("client", "https://fb.me/xxx", started + timedelta(hours=1)),
        MessageView("client", "https://fb.me/xxx", started + timedelta(hours=2)),
    ])

    assert is_noise(spam, now, _Cfg()) is True
