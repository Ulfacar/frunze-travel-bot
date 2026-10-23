"""ГЕЙТ: въездные знания включаются по одному боту, а не сразу всем.

Написан ДО реализации.

Зачем. Прогон бота на новых знаниях нужно сделать в песочнице Telegram (`getvisa_tg`,
сценарий `visa`), а не на боевом номере GetVisa, где сидят живые клиенты и работают
Медина с Элизой. Глобальный флаг такого не позволяет: включив знания, включаешь их
всем сразу. Образец уже есть в оркестраторе — `bots_enabled:<bot_id>` поверх
глобального `bots_enabled`.

Второе, что здесь закреплено: **тумблер речи обязан быть рантайм-флагом.** До этого
`kg_entry_say_confirmed_enabled` читался напрямую из настроек, хотя в панели был
зарегистрирован кнопкой. То есть кнопка в панели ничего не делала, а включение речи
требовало правки env и рестарта — и, что хуже, откат тоже. Это недочёт выката 21.10.
"""
import asyncio

import pytest

import app.config
from app.channels.base import Message
from app.core import flags
from app.core.state import DialogState

SANDBOX = "getvisa_tg"
LIVE = "getvisa"


@pytest.fixture(autouse=True)
def clean_flags():
    flags.reset()
    yield
    flags.reset()


def _state(bot_id):
    return DialogState(user_id=f"{bot_id}:996700000001", funnel="visa", bot_id=bot_id)


def _msg(text, bot_id):
    uid = f"{bot_id}:996700000001"
    return Message(channel="telegram", user_id=uid, chat_id=uid, text=text)


# --- A. Помощник «флаг по боту» ------------------------------------------------

def test_personal_key_turns_a_flag_on_for_one_bot_only():
    async def go():
        await flags.set_flag("kg_entry_enabled:getvisa_tg", True)
        for_sandbox = await flags.get_bot_flag("kg_entry_enabled", SANDBOX, False)
        for_live = await flags.get_bot_flag("kg_entry_enabled", LIVE, False)
        return for_sandbox, for_live
    sandbox, live = asyncio.run(go())
    assert sandbox is True, "персональный ключ не включил флаг для песочницы"
    assert live is False, "включение песочницы задело боевой номер GetVisa"


def test_personal_key_can_also_turn_a_flag_off_for_one_bot():
    """Обратная сторона: один бот можно заглушить, не выключая остальных."""
    async def go():
        await flags.set_flag("kg_entry_enabled", True)
        await flags.set_flag("kg_entry_enabled:getvisa", False)
        return (await flags.get_bot_flag("kg_entry_enabled", LIVE, False),
                await flags.get_bot_flag("kg_entry_enabled", SANDBOX, False))
    live, sandbox = asyncio.run(go())
    assert live is False
    assert sandbox is True


def test_without_a_bot_id_the_global_flag_decides():
    async def go():
        await flags.set_flag("kg_entry_enabled", True)
        return await flags.get_bot_flag("kg_entry_enabled", "", False)
    assert asyncio.run(go()) is True


# --- B. Въездная ветка слушается персонального ключа ---------------------------

def test_entry_branch_wakes_up_only_for_the_bot_it_was_enabled_for(monkeypatch):
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", False, raising=False)
    monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)
    from app.funnels.visa import VisaFunnel

    async def go():
        await flags.set_flag("kg_entry_enabled:getvisa_tg", True)
        funnel = VisaFunnel()
        text = "I need a visa to Kyrgyzstan"
        in_sandbox = _state(SANDBOX)
        await funnel.handle(_msg(text, SANDBOX), in_sandbox)
        on_live = _state(LIVE)
        await funnel.handle(_msg(text, LIVE), on_live)
        return in_sandbox.qualification.get("entry_mode"), on_live.qualification.get("entry_mode")

    sandbox_mode, live_mode = asyncio.run(go())
    assert sandbox_mode == "kg_entry", "в песочнице въездная ветка не включилась"
    assert live_mode is None, \
        "въездная ветка включилась на боевом номере GetVisa, хотя её включали в песочнице"


# --- C. Тумблер речи — рантайм-флаг, а не только env ---------------------------

def test_speech_toggle_works_at_runtime(monkeypatch):
    """Кнопка в панели обязана действительно разрешать речь, без правки env и рестарта."""
    monkeypatch.setattr(app.config.settings, "kg_entry_say_confirmed_enabled", False,
                        raising=False)
    from app.agent.runner import _entry_claim_permissions, KG_ENTRY_SPEC

    spec = KG_ENTRY_SPEC
    state = _state(SANDBOX)
    state.qualification["kg_entry"] = {"citizenship": "США", "citizenship_iso3": "USA",
                                       "purpose": "tourism"}

    async def go():
        silent, _, _ = await _entry_claim_permissions(state, spec)
        await flags.set_flag("kg_entry_say_confirmed_enabled:getvisa_tg", True)
        speaking, _, _ = await _entry_claim_permissions(state, spec)
        live_state = _state(LIVE)
        live_state.qualification["kg_entry"] = dict(state.qualification["kg_entry"])
        on_live, _, _ = await _entry_claim_permissions(live_state, spec)
        return silent, speaking, on_live

    silent, speaking, on_live = asyncio.run(go())
    assert silent == frozenset(), "речь разрешена, хотя тумблер выключен"
    assert {"regime", "stay_limit"} <= speaking, \
        "тумблер речи включён для этого бота, но правила всё равно не произносятся"
    assert on_live == frozenset(), \
        "включение речи в песочнице развязало язык боту на боевом номере"


def test_speech_stays_off_by_default_everywhere():
    assert app.config.settings.kg_entry_say_confirmed_enabled is False
    assert app.config.settings.kg_entry_enabled is False
