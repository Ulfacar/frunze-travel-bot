"""Ночной режим: бот отвечает только в ночном окне по Бишкеку (флаг night_mode_enabled)."""
import asyncio

import app.config
from app.core import flags
from app.core.orchestrator import Orchestrator


def _clear():
    flags.reset()


def _orch(bot_id="frunze_tours"):
    """Оркестратор с ботом — _bot_id выводится из self.bot.id; для _bots_on хватает."""
    from app.config import BotConfig
    o = Orchestrator.__new__(Orchestrator)
    o.bot = BotConfig(id=bot_id, scenario="tours")
    return o


def _bots_on(o):
    return asyncio.run(o._bots_on())


def _set_hour(monkeypatch, hour):
    """Заморозить час Бишкека: подменяем datetime.now(utc) так, чтобы +6 дал hour."""
    from datetime import datetime, timezone
    import app.core.orchestrator as orch
    utc_hour = (hour - 6) % 24
    fixed = datetime(2026, 7, 24, utc_hour, 30, tzinfo=timezone.utc)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed
    monkeypatch.setattr(orch, "datetime", _DT)


def test_night_mode_off_bot_answers_daytime(monkeypatch):
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    # флаг ночного режима OFF → день не мешает
    _set_hour(monkeypatch, 14)
    assert _bots_on(_orch()) is True


def test_night_mode_on_blocks_daytime(monkeypatch):
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    _set_hour(monkeypatch, 14)                 # 14:00 — день
    assert _bots_on(_orch()) is False


def test_night_mode_on_allows_night(monkeypatch):
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    for h in (22, 23, 0, 3, 7):                # ночь [22, 8)
        _set_hour(monkeypatch, h)
        assert _bots_on(_orch()) is True, f"час {h} должен быть ночью"


def test_night_mode_boundaries(monkeypatch):
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    _set_hour(monkeypatch, 22)                 # ровно 22:00 — вкл (граница включена)
    assert _bots_on(_orch()) is True
    _set_hour(monkeypatch, 8)                  # ровно 08:00 — уже день (граница выключена)
    assert _bots_on(_orch()) is False
    _set_hour(monkeypatch, 21)                 # 21:00 — ещё день
    assert _bots_on(_orch()) is False


def test_night_mode_never_wakes_disabled_bot(monkeypatch):
    """Ночь НЕ включает бота, выключенного кнопкой."""
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", False))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    _set_hour(monkeypatch, 3)                  # глубокая ночь
    assert _bots_on(_orch()) is False


def test_per_bot_key_frees_one_channel_for_daytime(monkeypatch):
    """Решение владельца 30.07: туры днём, визы ночью. Глобальный флаг остаётся ON,
    туровому каналу ночной режим снимается персональным ключом."""
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("bots_enabled:getvisa", True))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    asyncio.run(flags.set_flag("night_mode_enabled:frunze_tours", False))

    _set_hour(monkeypatch, 14)                              # день
    assert _bots_on(_orch("frunze_tours")) is True           # туры отвечают
    assert _bots_on(_orch("getvisa")) is False               # визы молчат днём

    _set_hour(monkeypatch, 3)                               # ночь
    assert _bots_on(_orch("frunze_tours")) is True           # туры отвечают и ночью
    assert _bots_on(_orch("getvisa")) is True                # визы работают ночью


def test_per_bot_key_can_also_add_night_mode_to_one_channel(monkeypatch):
    """Обратный случай: глобально ночного режима нет, а одному каналу он нужен."""
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("bots_enabled:getvisa", True))
    asyncio.run(flags.set_flag("night_mode_enabled:getvisa", True))
    _set_hour(monkeypatch, 14)
    assert _bots_on(_orch("frunze_tours")) is True
    assert _bots_on(_orch("getvisa")) is False


def test_per_bot_night_key_never_wakes_disabled_bot(monkeypatch):
    """Персональный ключ ночного режима тоже не включает выключенного кнопкой бота."""
    _clear()
    asyncio.run(flags.set_flag("bots_enabled:getvisa", False))
    asyncio.run(flags.set_flag("night_mode_enabled:getvisa", False))
    _set_hour(monkeypatch, 3)
    assert _bots_on(_orch("getvisa")) is False


def test_night_mode_custom_window(monkeypatch):
    """Окно берётся из настроек (напр. 20→10)."""
    _clear()
    monkeypatch.setattr(app.config.settings, "night_mode_from", 20)
    monkeypatch.setattr(app.config.settings, "night_mode_to", 10)
    asyncio.run(flags.set_flag("bots_enabled:frunze_tours", True))
    asyncio.run(flags.set_flag("night_mode_enabled", True))
    _set_hour(monkeypatch, 21)                 # теперь 21:00 — уже ночь
    assert _bots_on(_orch()) is True
    _set_hour(monkeypatch, 11)                 # 11:00 — день
    assert _bots_on(_orch()) is False
