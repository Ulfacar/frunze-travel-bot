"""Стадия диалога должна двигаться по мере разговора.

Замер прода 19.08.2026: 1014 из 1107 диалогов за 30 дней стоят в стадии `greeting`,
средняя длина такого «приветствия» — 8.3 сообщения, у 141 из них шесть и больше, рекорд
69 сообщений. Причина не в клиентах: в коде `stage` менялась ровно в двух местах и только
на `manager`/`office`. То есть канбан показывал не воронку, а флаг эскалации, и вопрос
«где отваливается клиент» на этих данных не имел ответа.

Второе требование — не топтать менеджера: ручной перенос карточки главнее бота
(решение владельца от 16.07), поэтому бот стадию только продвигает и никогда не откатывает.
"""
from app.core.leadstate import advance_stage, derive_stage


class _State:
    def __init__(self, qualification=None, stage="greeting"):
        self.qualification = dict(qualification or {})
        self.stage = stage


def test_empty_dialog_stays_in_greeting():
    assert derive_stage(_State()) == "greeting"


def test_first_answers_move_to_qualification():
    assert derive_stage(_State({"country": "Italy"})) == "qualification"
    assert derive_stage(_State({"country": "Italy", "name": "Динара"})) == "qualification"


def test_filled_profile_moves_to_progress():
    filled = {"destination": "Турция", "region": "Анталья", "budget": "2000 USD",
              "dates": "05.09.2026", "tourists": "2"}

    assert derive_stage(_State(filled)) == "progress"


def test_bot_never_rolls_the_card_back():
    """Эскалация и ручной перенос менеджера пережидают любой пересчёт."""
    assert advance_stage("manager", "progress") == "manager"
    assert advance_stage("office", "qualification") == "office"
    assert advance_stage("progress", "greeting") == "progress"


def test_bot_moves_the_card_forward():
    assert advance_stage("greeting", "qualification") == "qualification"
    assert advance_stage("qualification", "progress") == "progress"
    assert advance_stage("", "qualification") == "qualification"


# ---------- Карточка в панели действительно движется ----------
import asyncio

from app.channels.base import Message
from app.config import BotConfig
from app.core.orchestrator import Orchestrator
from app.core.state import DialogState
from app.integrations.panel import store as panel_store


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()


def _msg():
    return Message(channel="whatsapp", user_id="996700123456",
                   chat_id="996700123456@c.us", text="хочу тур")


def test_card_moves_out_of_greeting_when_answers_arrive():
    _clear()
    orc = Orchestrator(channel=None, bot=BotConfig(id="frunze_tours", scenario="tours"))
    state = DialogState(user_id="996700123456", funnel="tours",
                        qualification={"destination": "Турция", "dates": "05.09", "budget": "2000"})

    asyncio.run(orc._sync_card(_msg(), state))

    conv = asyncio.run(panel_store._memory_store.get("frunze_tours:996700123456"))
    assert conv.stage == "progress"


def test_manual_move_by_manager_survives_the_next_turn():
    """Менеджер перетащил карточку в «Офис» — следующий ход бота её не возвращает."""
    _clear()
    orc = Orchestrator(channel=None, bot=BotConfig(id="frunze_tours", scenario="tours"))
    state = DialogState(user_id="996700123456", funnel="tours",
                        qualification={"destination": "Турция"})
    asyncio.run(orc._sync_card(_msg(), state))
    asyncio.run(panel_store._memory_store.update_meta("frunze_tours:996700123456", stage="office"))

    asyncio.run(orc._sync_card(_msg(), state))

    conv = asyncio.run(panel_store._memory_store.get("frunze_tours:996700123456"))
    assert conv.stage == "office"
