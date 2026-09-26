"""ГЕЙТ: «диагноз=webhook» не ставится, когда вебхук доказанно жив.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 24-26.09.2026)

26.09 в 12:14 по Бишкеку владельцу ушло:

    🔴 Канал getvisa (Медина) молчит 21 ч — входящих нет.
    Сообщения в Wappi приходят, а до нас не доходят — смотри адрес вебхука у этого профиля.

В ту же минуту прод отвечал: `authorized=true`, `app_status=open`, вебхук
`https://frunzetravel.kg/webhook/wappi?s=…` на месте, а в 06:17 UTC (через три минуты
после тревоги) по этому же каналу прошло клиентское входящее. Совет был ложным: чинить
было нечего. Настоящая причина — реклама стоит с 19.09, новых диалогов getvisa 14 → 1 в
сутки, и это вопрос к таргетологам, а не к коду.

## Механика дефекта

`classify_gap` объявляет «webhook», когда счётчик Wappi вырос, а наша отметка последнего
КЛИЕНТСКОГО входящего — нет. Но счётчик `message_count` в ответе Wappi **один на всё**:
разбивки по направлению в этом ответе нет ни в каком поле (живой профиль 26.09:
`message_count: 7115`). При этом в `webhook_types` профиля стоят `outgoing_message_phone`
и `outgoing_message_api` — проверено на всех трёх боевых профилях, — то есть ответы
менеджеров с телефона и из Битрикса увеличивают этот же счётчик. Менеджер дописал в
старый диалог → счётчик вырос → клиентских входящих нет → сторож обвинил наш вебхук.

Глушилка `silence_alert_only_on_gap` (включена на проде) тут не спасает: она снимает
только диагноз `no_traffic`.

## Правило

У нас есть прямое доказательство живости трубы, и оно уже приходит: служебные события
Wappi по этому же профилю (статусы доставки, эхо ответов менеджера) доезжают до нашего
`/webhook/wappi`. Дошло служебное событие — значит адрес вебхука верен и события от
Wappi мы получаем; тогда «до нас не доходят» — ложь, и повод тот же, что у `no_traffic`.

Доказательством считается только ЧУЖОЕ событие. Эхо нашей же реплики
(`outgoing_message_api` под тем же id, что мы отправили) и статусы доставки наших
сообщений — не доказательство: ночной дожим по старым лидам вечно освежал бы их на
канале, который в это время не принимает входящие вообще.

Дыра, которую доказательство НЕ закрывает, закрыта отдельно: если из подписки профиля
пропал сам тип `incoming_message`, Wappi клиентские сообщения нам и не пошлёт — это
настоящая поломка вебхука, и её служебные события замаскировать не имеют права.
Подтвердить подписку не удалось (поля нет, Wappi не ответил) — глушилка не работает:
цена ошибки несимметрична, промолчавший сторож стоил 12 часов 03.08 и шести дней 17-22.09.

Требуется от реализации:
    app/core/channel_heartbeat.py:
        async note_service_event(bot_id)       — отметка «служебное событие дошло»
        async last_service_events() -> dict    — отметки по всем каналам
    app/core/wappi_health.py:
        classify_gap(counter_now, counter_prev, our_inbound_moved,
                     *, service_event_moved=False, incoming_subscribed=True) -> str
    app/config.py + админка: флаг `silence_webhook_proof_enabled`, дефолт OFF.
    app/main.py: служебные события Wappi отмечаются, клиентское входящее — нет
                 (у него своя отметка `note_inbound`, иначе доказательство самоподтвердится).
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import channel_heartbeat as hb
from app.core.wappi_health import classify_gap

GROWN = dict(counter_now=740, counter_prev=715, our_inbound_moved=False)


# --- A. диагноз: доказательство живости вебхука ----------------------------------

def test_service_event_proves_the_pipe_and_clears_the_webhook_blame():
    """Случай 26.09: счётчик вырос на ответах менеджера, события до нас доходят."""
    assert classify_gap(**GROWN, service_event_moved=True) == "no_traffic"


def test_without_proof_the_verdict_is_still_webhook():
    """Ничего от Wappi не дошло за всё окно тишины — подозрение на вебхук остаётся."""
    assert classify_gap(**GROWN, service_event_moved=False) == "webhook"


def test_lost_incoming_subscription_is_a_real_break_and_survives_the_proof():
    """Тип `incoming_message` пропал из подписки — статусы доставки это не оправдывает."""
    assert classify_gap(**GROWN, service_event_moved=True,
                        incoming_subscribed=False) == "webhook"


def test_subscription_check_is_fail_closed_on_an_unreadable_answer():
    """Подтвердить подписку не смогли — глушилку не включаем.

    Формулировать «нет поля → наверное подписан» нельзя: тогда любой обрезанный ответ
    Wappi открывал бы дорогу глушилке, а это ровно тот сторож, чьё молчание стоило нам
    12 часов 03.08 и шести дней 17-22.09.
    """
    from app.core.wappi_health import incoming_subscribed

    live = ["delivery_status", "incoming_message", "authorization_status",
            "outgoing_message_phone", "outgoing_message_api"]
    assert incoming_subscribed({"webhook_types": live}) is True
    assert incoming_subscribed({"webhook_types": ["delivery_status"]}) is False
    assert incoming_subscribed({"webhook_types": []}) is False
    assert incoming_subscribed({}) is False
    assert incoming_subscribed(None) is False


def test_defaults_keep_the_previous_gate_verdict():
    """Ложноположительный: без новых аргументов поведение прежнее (гейт 09.08)."""
    assert classify_gap(**GROWN) == "webhook"
    assert classify_gap(counter_now=715, counter_prev=715, our_inbound_moved=False) == "no_traffic"
    assert classify_gap(counter_now=740, counter_prev=715, our_inbound_moved=True) == ""


def test_proof_does_not_invent_a_verdict_without_counters():
    """Wappi не ответил — молчим о причине, доказательство этого не меняет."""
    assert classify_gap(None, 715, False, service_event_moved=True) == ""
    assert classify_gap(715, None, False, service_event_moved=True) == ""


def test_flat_counter_stays_no_traffic_with_or_without_proof():
    for proof in (True, False):
        assert classify_gap(715, 715, False, service_event_moved=proof) == "no_traffic"


# --- B. отметка служебных событий ------------------------------------------------

def test_service_mark_is_separate_from_the_client_inbound_mark():
    """Клиентская отметка и служебная не должны затирать друг друга.

    Иначе служебное событие выглядело бы как клиентское входящее и сторож тишины
    перестал бы срабатывать вообще — это было бы хуже ложного совета.
    """
    hb._memory_last_seen.pop("getvisa", None)
    asyncio.run(hb.note_service_event("getvisa"))

    assert hb._memory_last_seen.get("getvisa") is None, "служебное событие — не входящее"
    assert asyncio.run(hb.last_service_events()).get("getvisa")


def test_service_mark_survives_an_empty_bot_id():
    """Событие без сопоставленного бота не имеет права ронять вебхук."""
    asyncio.run(hb.note_service_event(""))


def test_last_service_events_is_empty_when_nothing_arrived():
    hb._memory_last_service.clear()
    assert not asyncio.run(hb.last_service_events()).get("frunze_tours")


# --- C. флаг: выкатка не меняет поведение ----------------------------------------

def test_flag_exists_and_is_off_by_default():
    from app.config import settings

    assert settings.silence_webhook_proof_enabled is False


def test_flag_has_a_button_in_the_admin_panel():
    """Тумблер без кнопки — это env-настройка, а решение принимается в панели."""
    from app.admin.router import FEATURE_FLAGS

    assert "silence_webhook_proof_enabled" in FEATURE_FLAGS


@pytest.mark.parametrize("enabled,expected", [(False, "webhook"), (True, "no_traffic")])
def test_diagnosis_follows_the_flag_end_to_end(monkeypatch, enabled, expected):
    """Флаг OFF — прод ведёт себя как сегодня; ON — ложный диагноз снят.

    Дословная обстановка 26.09: профиль жив, счётчик вырос на 25 (ответы менеджера),
    клиентских входящих нет с 1000.0, служебное событие дошло позже — в 5000.0.
    """
    from app.config import BotConfig
    from app.core import flags, wappi_health

    bot = BotConfig(id="getvisa", scenario="visa", wappi_profile_id="2f099bc3-478d")

    class _Registry:
        def all(self):
            return [bot]

    monkeypatch.setattr("app.core.bots.registry", _Registry())
    monkeypatch.setattr(wappi_health, "fetch_status", lambda _pid: _coro({
        "authorized": True, "app_status": "open", "message_count": 740,
        "webhook_types": ["incoming_message", "outgoing_message_phone", "delivery_status"],
    }))
    monkeypatch.setattr(wappi_health, "_counter_snapshot", lambda _bot: _coro((715, 1000.0)))
    monkeypatch.setattr(wappi_health, "_remember_counter", lambda *a, **k: _coro(None))
    monkeypatch.setattr(hb, "_load_last_seen", lambda: _coro({"getvisa": 1000.0}))
    monkeypatch.setattr(hb, "last_service_events", lambda: _coro({"getvisa": 5000.0}))

    async def _go():
        flags.reset()
        if enabled:
            await flags.set_flag("silence_webhook_proof_enabled", True)
        return await wappi_health.diagnoses_and_health()

    diagnoses, healthy = asyncio.run(_go())
    assert diagnoses.get("getvisa") == expected
    assert healthy.get("getvisa") is True


# --- D. отметка ставится на настоящем вебхуке ------------------------------------

def _wappi_event(**over) -> dict:
    base = {"id": "evt-1", "profile_id": "proof-profile", "wh_type": "delivery_status",
            "status": "delivered"}
    base.update(over)
    return base


def _wire_webhook(monkeypatch):
    """Минимальная обвязка /webhook/wappi: бот есть, наружу никто не ходит."""
    import app.core.orchestrator as orch
    import app.main as main
    from app.channels.wappi import WappiAdapter
    from app.config import BotConfig
    from app.core.orchestrator import Orchestrator

    class FakeFunnel:
        async def handle(self, msg, state):
            return ""

    monkeypatch.setattr(orch, "get_funnel", lambda name: FakeFunnel())
    bot = BotConfig(id="getvisa", scenario="visa", wappi_profile_id="proof-profile")

    class Silent(WappiAdapter):
        async def send(self, chat_id, text, **kw):
            return "provider-1"

    monkeypatch.setattr(main, "_wappi_orchestrators",
                        {"proof-profile": Orchestrator(channel=Silent(bot=bot), bot=bot)})
    main._seen_wappi_ids.clear()
    hb._memory_last_service.clear()
    hb._memory_last_seen.pop("getvisa", None)
    return main


def test_delivery_status_marks_the_channel_as_reachable(monkeypatch):
    """Статус доставки — доказательство, что труба от Wappi до нас работает."""
    from fastapi.testclient import TestClient

    main = _wire_webhook(monkeypatch)
    resp = TestClient(main.app).post("/webhook/wappi", json={"messages": [_wappi_event()]})

    assert resp.status_code == 200
    assert asyncio.run(hb.last_service_events()).get("getvisa")


def test_manager_echo_marks_the_channel_as_reachable(monkeypatch):
    """Ответ менеджера с телефона — то же доказательство (и он же растит счётчик Wappi)."""
    from fastapi.testclient import TestClient

    main = _wire_webhook(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", False)
    TestClient(main.app).post("/webhook/wappi", json={"messages": [_wappi_event(
        wh_type="outgoing_message_phone", type="chat", body="ответ менеджера",
        to="996500494009@c.us", chatId="996500494009@c.us", is_me=True)]})

    assert asyncio.run(hb.last_service_events()).get("getvisa")


def test_client_message_does_not_forge_the_proof(monkeypatch):
    """Клиентское входящее служебной отметки НЕ ставит: иначе доказательство
    самоподтвердится последним же входящим и сторож тишины ослепнет."""
    from fastapi.testclient import TestClient

    main = _wire_webhook(monkeypatch)
    TestClient(main.app).post("/webhook/wappi", json={"messages": [_wappi_event(
        id="client-1", wh_type="incoming_message", type="chat", body="нужна виза",
        **{"from": "996500494009@c.us"}, chatId="996500494009@c.us",
        is_me=False, chat_type="dialog")]})

    assert not asyncio.run(hb.last_service_events()).get("getvisa")
    assert hb._memory_last_seen.get("getvisa"), "клиентская отметка обязана остаться"


def test_our_own_echo_is_not_a_proof(monkeypatch):
    """Эхо НАШЕЙ ЖЕ отправки ничего не доказывает про приём входящих.

    Иначе ночной дожим по старым лидам вечно освежал бы доказательство на канале,
    который в это время не принимает клиентские сообщения вообще.
    """
    from fastapi.testclient import TestClient

    from app.core.own_outbound import _reset_for_tests, mark_own

    main = _wire_webhook(monkeypatch)
    _reset_for_tests()
    mark_own("our-own-msg")
    TestClient(main.app).post("/webhook/wappi", json={"messages": [_wappi_event(
        id="our-own-msg", wh_type="outgoing_message_api", type="chat",
        body="реплика бота", to="996500494009@c.us", chatId="996500494009@c.us",
        is_me=True)]})

    assert not asyncio.run(hb.last_service_events()).get("getvisa")


def test_delivery_status_of_our_own_message_is_not_a_proof(monkeypatch):
    """Статус доставки нашего же сообщения вызван нами — доказательством не считается."""
    from fastapi.testclient import TestClient

    from app.core.own_outbound import _reset_for_tests, mark_own

    main = _wire_webhook(monkeypatch)
    _reset_for_tests()
    mark_own("our-own-status")
    TestClient(main.app).post("/webhook/wappi", json={"messages": [
        _wappi_event(id="our-own-status")]})

    assert not asyncio.run(hb.last_service_events()).get("getvisa")


def test_unknown_profile_does_not_break_the_webhook(monkeypatch):
    """Событие по чужому профилю — 200 и никакой отметки, а не падение."""
    from fastapi.testclient import TestClient

    main = _wire_webhook(monkeypatch)
    resp = TestClient(main.app).post(
        "/webhook/wappi", json={"messages": [_wappi_event(profile_id="someone-else")]})

    assert resp.status_code == 200
    assert not asyncio.run(hb.last_service_events()).get("getvisa")


def _coro(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner()
