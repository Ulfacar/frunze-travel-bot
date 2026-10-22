"""ГЕЙТ: самые частые первые реплики иностранца попадают во въездную ветку.

Написан ДО правок, по результатам прогона клиентских историй 22.10
(`scripts/run_entry_stories.py`, каталог `scenarios/kg_entry_stories.json`).

Шесть историй из двадцати провалились по одной причине: распознаватель темы требовал,
чтобы Кыргызстан был назван пунктом назначения словами («виза в Кыргызстан»), а живой
иностранец пишет иначе — «Я из Нигерии, хочу приехать туристом на 50 дней». Такие
диалоги уходили в ВЫЕЗДНУЮ воронку, и бот спрашивал «в какую страну вам нужна виза?»
у человека, который хочет приехать в Кыргызстан.

Седьмая история вскрыла вторую дыру в том же слое: немцу, спросившему про въезд,
детерминированный прайс ВЫЕЗДНЫХ виз ответил «сопровождение 100€, консульский сбор
90€» — цены по Шенгену. Гвард существовал, но смотрел на `entry_mode`, который
появляется лишь после первого прохода воронки, а прайс стреляет ДО неё.

Главное правило ветки не меняется: **при сомнении остаётся прежнее поведение.**
Поэтому здесь столько же проверок на то, что выездные реплики остались выездными.
"""
import asyncio

import pytest

import app.config
from app.channels.base import Message
from app.core import flags
from app.core.entry_intent import detect
from app.core.state import DialogState

SANDBOX = "getvisa_tg"


@pytest.fixture(autouse=True)
def clean_flags():
    flags.reset()
    yield
    flags.reset()


# --- A. Первые реплики иностранца, которые бот обязан узнать -------------------

@pytest.mark.parametrize("text", [
    "Я из Нигерии, хочу приехать туристом на 50 дней.",
    "Я из Германии, хочу приехать туристом на три месяца.",
    "Здравствуйте! Я из Пакистана, моя сестра замужем за гражданином Кыргызстана. "
    "Хочу приехать к ним на полгода.",
    "Я гражданин Индии, хочу приехать на работу.",
    "Я из Узбекистана, приеду в начале ноября.",
    "Я гражданка Турции, планирую приехать к мужу.",
    "I am from Nigeria and I want to come for tourism for 50 days.",
    "I'm a citizen of India, I would like to arrive next month.",
])
def test_declared_foreign_origin_plus_arrival_is_an_entry_talk(text):
    """«Я из <чужой страны>» рядом с «приехать» — это въезд, даже без слова «Кыргызстан».

    Клиент на номере GetVisa, который называет СВОЁ гражданство и собирается
    приехать, — иностранец. Гражданин КР так про себя не пишет.
    """
    assert detect(text) == "kg_entry", f"не распознано как въезд: {text!r}"


# --- B. Выездное осталось выездным (при сомнении — прежнее поведение) ----------

@pytest.mark.parametrize("text", [
    "Хочу поехать в Германию, нужна виза.",
    "Я гражданин Кыргызстана, нужна виза в США.",
    "Нужна виза в Польшу, когда ближайший слот?",
    "Я из Бишкека, хочу поехать в Корею на работу.",
    "Записался на собеседование в посольство, что брать с собой?",
    "Отказали в визе в Шенген, что делать?",
    "Сколько стоит виза в Японию?",
    "Я из Кыргызстана, хочу приехать в Германию на учёбу.",
])
def test_outbound_talk_is_not_hijacked(text):
    """Выездная воронка работает и приносит деньги — забирать её нельзя."""
    assert detect(text) != "kg_entry", f"выездная реплика уехала во въезд: {text!r}"


def test_kyrgyz_origin_is_never_an_entry_client():
    """Гражданин КР не бывает въездным клиентом, как бы он ни написал."""
    for text in ("Я гражданин Кыргызстана, хочу приехать домой.",
                 "Я из Кыргызстана, приеду в сентябре.",
                 "I am a citizen of Kyrgyzstan and I want to come back."):
        assert detect(text) != "kg_entry", text


def test_origin_without_arrival_does_not_decide():
    """Одного гражданства мало: «я гражданин России, нужна виза в США» — выезд."""
    assert detect("Я гражданин России, нужна виза в США.") == "outbound"
    assert detect("Я из Казахстана, подскажите по Шенгену.") == "outbound"


def test_stickiness_still_wins():
    assert detect("Сколько стоит?", sticky="outbound") == "outbound"
    assert detect("Сколько стоит?", sticky="kg_entry") == "kg_entry"


# --- C. Выездной прайс не отвечает на въездной вопрос --------------------------

def _state():
    return DialogState(user_id=f"{SANDBOX}:996700000001", funnel="visa", bot_id=SANDBOX)


def _msg(text):
    uid = f"{SANDBOX}:996700000001"
    return Message(channel="telegram", user_id=uid, chat_id=uid, text=text)


ENTRY_PRICE_QUESTION = ("Я из Германии, приеду на две недели. "
                        "Сколько будет стоить виза и ваши услуги?")


def test_outbound_price_is_not_quoted_to_an_inbound_client(monkeypatch):
    """Решение владельца «бот цен не называет» нарушалось на ПЕРВОЙ же реплике.

    Прайс выездных виз стоит в оркестраторе выше воронки, а прежний гвард смотрел на
    `entry_mode`, который к этому моменту ещё не выставлен.
    """
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", False, raising=False)
    from app.core.visa_pricing import visa_price_reply
    assert visa_price_reply(ENTRY_PRICE_QUESTION), \
        "предпосылка теста неверна: выездной прайс на эту реплику не срабатывает"

    from app.core.orchestrator import Orchestrator
    from app.config import BotConfig

    class Collect:
        channel = "telegram"

        def __init__(self):
            self.sent = []

        async def parse(self, raw):
            raise NotImplementedError

        async def send(self, chat_id, text, **kw):
            self.sent.append(text)
            return "1"

    async def go():
        await flags.set_flag(f"kg_entry_enabled:{SANDBOX}", True)
        await flags.set_flag("bots_enabled", True)
        await flags.set_flag("night_mode_enabled", False)
        monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)
        channel = Collect()
        orch = Orchestrator(channel=channel,
                            bot=BotConfig(id=SANDBOX, scenario="visa"))
        await orch.handle(_msg(ENTRY_PRICE_QUESTION))
        return "\n".join(channel.sent)

    reply = asyncio.run(go())
    for forbidden in ("€", "$", "евро", "консульский сбор"):
        assert forbidden not in reply, \
            f"иностранцу назвали выездной прайс ({forbidden!r}): {reply!r}"


def test_with_the_flag_off_the_price_faq_behaves_exactly_as_before(monkeypatch):
    """Откат должен быть дословным: при выключенной ветке прайс отвечает как сегодня."""
    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", False, raising=False)
    from app.core.orchestrator import Orchestrator
    from app.config import BotConfig

    class Collect:
        channel = "telegram"

        def __init__(self):
            self.sent = []

        async def parse(self, raw):
            raise NotImplementedError

        async def send(self, chat_id, text, **kw):
            self.sent.append(text)
            return "1"

    async def go():
        await flags.set_flag("bots_enabled", True)
        await flags.set_flag("night_mode_enabled", False)
        monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)
        channel = Collect()
        orch = Orchestrator(channel=channel,
                            bot=BotConfig(id="getvisa", scenario="visa"))
        await orch.handle(_msg("Сколько стоит виза в Германию?"))
        return "\n".join(channel.sent)

    reply = asyncio.run(go())
    assert reply.strip(), "при выключенной ветке бот вообще не ответил"
    assert "€" in reply or "евро" in reply.lower() or "сбор" in reply.lower(), \
        f"выездной прайс перестал отвечать при выключенной ветке: {reply!r}"
