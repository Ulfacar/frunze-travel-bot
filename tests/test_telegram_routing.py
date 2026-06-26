"""Тестовые Telegram-боты (песочница): маршрут /webhook/telegram/<id> и жёсткий сценарий."""
from app.config import BotConfig, TelegramBotConfig
from app.core.orchestrator import Orchestrator


def test_telegram_bot_config_parses_scenario():
    tb = TelegramBotConfig(id="getvisa_tg", scenario="visa", token="222:BBB")
    assert tb.scenario == "visa"
    assert tb.token == "222:BBB"


def test_orchestrator_forces_scenario_from_telegram_bot():
    # Тест-бот фиксирует воронку так же, как WhatsApp-бот (через bot.scenario).
    bot = BotConfig(id="frunze_tours_tg", scenario="tours")
    orch = Orchestrator(channel=None, bot=bot)
    assert orch.bot.scenario == "tours"
    assert orch._bot_id == "frunze_tours_tg"


def test_unknown_telegram_bot_returns_404():
    from fastapi.testclient import TestClient

    import app.main as m

    # В тестовой среде telegram_bots не настроены → любой bot_id неизвестен → 404.
    with TestClient(m.app) as client:
        resp = client.post("/webhook/telegram/nope", json={"message": {"text": "hi"}})
    assert resp.status_code == 404
    assert resp.json()["reason"] == "unknown_bot"
