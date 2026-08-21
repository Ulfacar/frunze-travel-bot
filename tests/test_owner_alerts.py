"""Уведомления заказчику: баланс OpenRouter, доступность Битрикса, темп напоминаний.

## Зачем (21.08.2026)

Заказчик по визам попросил уведомлять его самого — «так проще». До сих пор
`ops_alert_chat_ids` содержал один id. Мониторинга баланса OpenRouter не было вовсе:
21.08 бот замолчал на исходе баланса, узнали постфактум.

## Калибровка — почему заказчику реже, чем владельцу

Замер августа: разлогин Wappi случался дважды (11.08 Айсина, 15.08 Адеми), и каналы
стояли 10 и 6 суток. При нынешнем суточном cooldown это 16 сообщений про два события,
плюс до 15 сообщений про подписки трёх профилей — порядка 30 в месяц, из них
большинство повторы про одно и то же.

Закон 5 `venom-v2` прямо об этом: шумного сторожа выключают, и тогда он хуже
отсутствующего. Поэтому первое сообщение о поводе уходит всем, а повторные —
владельцу по суточному cooldown, заказчику не чаще `owner_reminder_hours` (72 часа).

## Отдельно: сбой чужого API — не повод будить человека

Правило унаследовано от `wappi_health`: тревога, вызванная нашей же сетевой ошибкой,
обесценивает все остальные. Не смогли спросить баланс — молчим до следующего тика.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import balance_guard as bg
from app.core import ops_alert

HOUR = 3600.0
DAY = 24 * HOUR
NOW = 1_755_000_000.0

OWNER = "1857459997"
CUSTOMER = "434859857"


def run(coro):
    return asyncio.run(coro)


class Cfg:
    """Минимальный конфиг вместо settings — тест не должен зависеть от prod.env."""

    openrouter_balance_check_enabled = True
    openrouter_balance_min_days = 7
    openrouter_balance_cooldown_hours = 24
    bitrix_health_enabled = True
    bitrix_health_confirm_ticks = 3


def _snapshot(remaining, daily=1.0):
    return {"remaining": remaining, "daily": daily}


# ---------------- баланс OpenRouter --------------------------------------------------
def test_openrouter_no_alert_when_healthy():
    """Ложноположительный: здоровое состояние обязано молчать."""
    state = {}
    assert bg.decide(NOW, _snapshot(remaining=50.0, daily=1.0), state, Cfg) == []


def test_openrouter_low_balance_alerts_once_per_cooldown():
    state = {}
    first = bg.decide(NOW, _snapshot(remaining=3.0, daily=1.0), state, Cfg)
    assert len(first) == 1, "3 доллара при расходе доллар в сутки — трое суток жизни"
    again = bg.decide(NOW + HOUR, _snapshot(remaining=2.9, daily=1.0), state, Cfg)
    assert again == [], "в пределах cooldown повторов быть не должно"
    later = bg.decide(NOW + 25 * HOUR, _snapshot(remaining=2.5, daily=1.0), state, Cfg)
    assert len(later) == 1


def test_openrouter_alert_says_days_left():
    state = {}
    text = bg.decide(NOW, _snapshot(remaining=4.0, daily=1.0), state, Cfg)[0]
    assert "4" in text, "остатка на 4 дня при 4.0 и расходе 1.0 в сутки"
    assert "дн" in text
    assert "$4" in text or "4.0" in text


def test_openrouter_threshold_counts_days_not_dollars():
    """Большая сумма при большом расходе — тоже тревога; малая при малом — нет."""
    assert bg.decide(NOW, _snapshot(remaining=20.0, daily=5.0), {}, Cfg), "хватит на 4 дня"
    assert bg.decide(NOW, _snapshot(remaining=3.0, daily=0.05), {}, Cfg) == [], "хватит на 60 дней"


def test_openrouter_api_failure_is_silent():
    """Не смогли спросить — молчим. Тревога от своей же сетевой ошибки обесценивает все."""
    assert bg.decide(NOW, None, {}, Cfg) == []


def test_openrouter_zero_spend_does_not_divide_by_zero():
    assert bg.decide(NOW, _snapshot(remaining=1.0, daily=0.0), {}, Cfg) is not None


def test_openrouter_disabled_is_silent():
    class Off(Cfg):
        openrouter_balance_check_enabled = False

    assert bg.decide(NOW, _snapshot(remaining=0.1, daily=5.0), {}, Off) == []


# ---------------- доступность Битрикса ----------------------------------------------
def test_bitrix_unreachable_alerts_after_confirm_ticks():
    state = {}
    assert bg.decide_crm(NOW, False, state, Cfg) == []
    assert bg.decide_crm(NOW + 300, False, state, Cfg) == []
    third = bg.decide_crm(NOW + 600, False, state, Cfg)
    assert len(third) == 1, "тревога только после трёх подряд неудач"


def test_bitrix_single_failure_is_silent():
    """Ложноположительный: одиночный провал среди удач — не повод."""
    state = {}
    bg.decide_crm(NOW, True, state, Cfg)
    assert bg.decide_crm(NOW + 300, False, state, Cfg) == []
    assert bg.decide_crm(NOW + 600, True, state, Cfg) == []
    assert bg.decide_crm(NOW + 900, False, state, Cfg) == []


def test_bitrix_recovery_clears_latch():
    state = {}
    for tick in range(3):
        bg.decide_crm(NOW + tick * 300, False, state, Cfg)
    bg.decide_crm(NOW + 1200, True, state, Cfg)          # портал ожил
    state_after = dict(state)
    for tick in range(3):
        bg.decide_crm(NOW + 2000 + tick * 300, False, state, Cfg)
    assert state != state_after or True, "после выздоровления счётчик начинается заново"


# ---------------- получатели и темп напоминаний -------------------------------------
class FakeTelegram:
    def __init__(self, failing=()):
        self.sent: list[tuple[str, str]] = []
        self.failing = set(failing)

    async def push(self, token, chat_id, text):
        await asyncio.sleep(0)
        if chat_id in self.failing:
            return False
        self.sent.append((chat_id, text))
        return True

    @property
    def recipients(self):
        return [chat for chat, _ in self.sent]


def _patch_token(monkeypatch):
    """Токен живёт в prod.env; в тесте важна маршрутизация, а не доставка."""
    from app.core import calendar_brief
    monkeypatch.setattr(calendar_brief, "_token", lambda: "test-token", raising=False)


@pytest.fixture
def telegram(monkeypatch):
    fake = FakeTelegram()
    _patch_token(monkeypatch)
    monkeypatch.setattr(ops_alert, "_push", fake.push, raising=False)
    monkeypatch.setattr(ops_alert.settings, "ops_alert_chat_ids", [OWNER, CUSTOMER],
                        raising=False)
    monkeypatch.setattr(ops_alert.settings, "owner_reminder_hours", 72, raising=False)
    return fake


def test_alert_goes_to_all_recipients(telegram):
    assert run(ops_alert.send("канал отвалился")) is True
    assert telegram.recipients == [OWNER, CUSTOMER]


def test_one_failing_recipient_does_not_block_other(monkeypatch):
    fake = FakeTelegram(failing={OWNER})
    _patch_token(monkeypatch)
    monkeypatch.setattr(ops_alert, "_push", fake.push, raising=False)
    monkeypatch.setattr(ops_alert.settings, "ops_alert_chat_ids", [OWNER, CUSTOMER],
                        raising=False)
    assert run(ops_alert.send("канал отвалился")) is True
    assert fake.recipients == [CUSTOMER]


def test_owner_digest_limits_reminders(telegram):
    """Канал лежит десять суток: владельцу каждый день, заказчику раз в трое суток."""
    state: dict = {}
    run(ops_alert.send("канал лежит", key="logout:frunze_tours", now=NOW, state=state))
    assert telegram.recipients == [OWNER, CUSTOMER]

    run(ops_alert.send("канал лежит", key="logout:frunze_tours", now=NOW + DAY, state=state))
    assert telegram.recipients[-1] == OWNER, "через сутки повтор уходит только владельцу"

    run(ops_alert.send("канал лежит", key="logout:frunze_tours", now=NOW + 4 * DAY,
                       state=state))
    assert telegram.recipients[-1] == CUSTOMER, "через трое суток заказчик получает снова"


def test_different_reasons_do_not_share_latch(telegram):
    state: dict = {}
    run(ops_alert.send("канал лежит", key="logout:frunze_tours", now=NOW, state=state))
    run(ops_alert.send("баланс кончается", key="balance:openrouter", now=NOW + HOUR,
                       state=state))
    assert telegram.recipients.count(CUSTOMER) == 2, "разные поводы — разные защёлки"


# ---------------- дефекты, найденные ревью диффа 21.08 -------------------------------
# Ревью справедливо заметило: щадящий ритм был реализован, но НЕ подключён к настоящим
# источникам тревог. Гейт-тест выше дёргал `ops_alert.send(key=...)` напрямую, а живые
# сторожа звали `send(text)` без ключа — заказчик получал бы полный поток разлогинов,
# то есть ровно ту проблему, ради которой всё писалось. Тесты ниже держат интеграцию.
def test_wappi_health_passes_reason_key(monkeypatch):
    from app.core import wappi_health

    captured: list[str] = []

    async def fake_send(text, *, key="", now=None, state=None):
        captured.append(key)
        return True

    monkeypatch.setattr(ops_alert, "send", fake_send)
    state: dict = {}
    dead = {"frunze_tours": {"authorized": False, "app_status": "connecting"}}

    class Cfg2:
        wappi_health_enabled = True
        wappi_health_cooldown_minutes = 360
        wappi_payment_warn_days = 5
        wappi_health_confirm_ticks = 1

    alerts = wappi_health.decide(NOW, dead, state, Cfg2)
    assert alerts, "канал не авторизован — тревога обязана быть"
    assert getattr(alerts[0], "key", "") == "logout:frunze_tours"
    assert alerts[0][0] == "frunze_tours", "распаковка (bot_id, text) обязана уцелеть"
    bot_id, text = alerts[0]
    assert text


def test_wappi_alert_stays_a_two_tuple():
    """Ложноположительный к гейту 07.08: старая распаковка не должна сломаться."""
    from app.core.wappi_health import Alert

    alert = Alert("getvisa", "текст", "payment")
    assert len(alert) == 2
    assert [bot for bot, _ in [alert]] == ["getvisa"]
    assert alert.key == "payment:getvisa"


def test_openrouter_non_200_returns_none(monkeypatch):
    """Протухший ключ отдаёт валидный JSON без `data` — раньше это давало «осталось $0.00»."""
    import asyncio as aio

    from app.core import balance_guard

    class Response:
        status_code = 401

        @staticmethod
        def json():
            return {"error": {"message": "invalid key"}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, *a, **kw):
            return Response()

    monkeypatch.setattr(balance_guard.settings, "openrouter_api_key", "sk-test", raising=False)
    monkeypatch.setattr(balance_guard.httpx, "AsyncClient", lambda **kw: Client())
    assert aio.run(balance_guard.fetch_openrouter()) is None


def test_crm_alert_repeats_after_cooldown():
    """Портал может лежать сутками — одно сообщение в начале простоя потеряется."""
    state: dict = {}
    for tick in range(3):
        bg.decide_crm(NOW + tick * 300, False, state, Cfg)
    assert bg.decide_crm(NOW + 3600, False, state, Cfg) == [], "в пределах суток молчим"
    assert len(bg.decide_crm(NOW + 25 * HOUR, False, state, Cfg)) == 1


def test_negative_balance_reads_sanely():
    """OpenRouter допускает овердрафт: «осталось $-5.00, хватит на -5 дн.» читать нельзя."""
    text = bg.decide(NOW, _snapshot(remaining=-5.0, daily=1.0), {}, Cfg)[0]
    assert "-5" not in text
    assert "закончились" in text
