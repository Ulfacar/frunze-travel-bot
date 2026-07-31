"""Юнит-тесты агентного цикла «Туры» с мок-Claude (без сети и без API-ключа).

Мокаем app.agent.runner.client (Anthropic) и runner._tourvisor.search_detailed, проверяя:
- round-trip tool_use → tool_result → финальный текст;
- guard по максимуму итераций;
- graceful degrade инструмента search_tours при ошибке TourVisor.
"""
import asyncio
from unittest.mock import AsyncMock

from app.agent import runner
from app.core.state import DialogState
from app.integrations.crm import get_crm
from app.integrations.tourvisor.client import TourSearch, TourVisorError


def _found(lines: list[str]) -> TourSearch:
    """Успешная выдача подбора в том виде, в каком её отдаёт клиент TourVisor."""
    return TourSearch(lines=lines, found=len(lines), reason="ok", departure="Бишкек")


# ---- фейковые ответы Claude (форма, которую ждёт runner) ----
class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input or {}
        self.id = id

    def model_dump(self):
        return {"type": self.type, "text": self.text, "name": self.name,
                "input": self.input, "id": self.id}


class FakeResp:
    def __init__(self, stop_reason, content, usage=None):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = usage


def _tool_use(name="search_tours", inp=None, id="t1"):
    return FakeResp("tool_use", [FakeBlock("tool_use", name=name,
                                           input=inp or {"destination": "Турция"}, id=id)])


def _text(text="Готово"):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _patch_client(monkeypatch, *responses, repeat_last=False):
    fake = AsyncMock()
    if repeat_last:
        fake.messages.create = AsyncMock(return_value=responses[-1])
    else:
        fake.messages.create = AsyncMock(side_effect=list(responses))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


def test_tool_use_then_text(monkeypatch):
    """search_tours отрабатывает, затем Claude отдаёт финальный текст."""
    state = DialogState(user_id="u1", funnel="tours")
    fake = _patch_client(monkeypatch, _tool_use(), _text("Вот варианты"))
    monkeypatch.setattr(runner._tourvisor, "search_detailed", AsyncMock(return_value=_found(["Отель X 5*"])))

    reply = asyncio.run(runner.run_tours_turn(state, "хочу тур в Турцию"))

    assert reply == "Вот варианты"
    runner._tourvisor.search_detailed.assert_awaited()
    assert state.deal_id is not None  # лид создан по ходу search_tours
    assert fake.messages.create.await_count == 2


def test_tours_turn_escalates_model_after_search_tours(monkeypatch):
    """Туры стартуют на cheap, после search_tours следующий LLM-вызов идёт на main."""
    monkeypatch.setattr(runner.settings, "llm_model_cheap", "cheap-model")
    monkeypatch.setattr(runner.settings, "llm_model_main", "main-model")
    state = DialogState(user_id="u-route", funnel="tours")
    fake = _patch_client(monkeypatch, _tool_use(), _text("Вот варианты"))
    monkeypatch.setattr(runner._tourvisor, "search_detailed", AsyncMock(return_value=_found(["Отель X 5*"])))

    reply = asyncio.run(runner.run_tours_turn(state, "хочу тур в Турцию"))

    assert reply == "Вот варианты"
    assert fake.messages.create.await_args_list[0].kwargs["model"] == "cheap-model"
    assert fake.messages.create.await_args_list[1].kwargs["model"] == "main-model"


def test_tours_turn_precheck_starts_escalated_on_commercial_terms(monkeypatch):
    """Коммерческие слова в тур-запросе сразу выбирают main-модель."""
    monkeypatch.setattr(runner.settings, "llm_model_cheap", "cheap-model")
    monkeypatch.setattr(runner.settings, "llm_model_main", "main-model")
    state = DialogState(user_id="u-route-price", funnel="tours")
    fake = _patch_client(monkeypatch, _text("Цена такая-то"))

    reply = asyncio.run(runner.run_tours_turn(state, "какая стоимость и есть ли скидка?"))

    assert reply == "Цена такая-то"
    assert fake.messages.create.await_args.kwargs["model"] == "main-model"


def test_visa_turn_uses_cheap_model(monkeypatch):
    """Визы всегда идут на cheap-модель."""
    monkeypatch.setattr(runner.settings, "llm_model_cheap", "cheap-model")
    monkeypatch.setattr(runner.settings, "llm_model_main", "main-model")
    state = DialogState(user_id="v-route", funnel="visa")
    fake = _patch_client(monkeypatch, _text("Ок"))

    reply = asyncio.run(runner.run_visa_turn(state, "нужна виза"))

    assert reply == "Ок"
    assert fake.messages.create.await_args.kwargs["model"] == "cheap-model"


def test_runner_records_usage(monkeypatch):
    """Usage из LLM response прокидывается в observ.record_usage."""
    monkeypatch.setattr(runner.settings, "llm_model_cheap", "cheap-model")
    state = DialogState(user_id="bot:phone", bot_id="bot", funnel="tickets")
    calls = []
    fake = _patch_client(
        monkeypatch,
        FakeResp(
            "end_turn",
            [FakeBlock("text", text="Ок")],
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "cost": 0.001},
        ),
    )
    monkeypatch.setattr(runner.observ, "record_usage", lambda *args, **kwargs: calls.append((args, kwargs)))

    reply = asyncio.run(runner.run_tickets_turn(state, "нужен билет"))

    assert reply == "Ок"
    assert fake.messages.create.await_count == 1
    assert calls[0][0] == ("cheap-model", 11, 7, 0.001, "bot", "bot:phone")
    assert calls[0][1]["usage"]["total_tokens"] == 18


def test_runner_estimates_missing_usage_cost(monkeypatch):
    monkeypatch.setattr(runner.settings, "llm_model_cheap", "anthropic/claude-haiku-4.5")
    state = DialogState(user_id="bot:phone", bot_id="bot", funnel="tickets")
    calls = []
    _patch_client(
        monkeypatch,
        FakeResp(
            "end_turn",
            [FakeBlock("text", text="РћРє")],
            usage={"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
        ),
    )
    monkeypatch.setattr(runner.observ, "record_usage", lambda *args, **kwargs: calls.append((args, kwargs)))

    reply = asyncio.run(runner.run_tickets_turn(state, "РЅСѓР¶РµРЅ Р±РёР»РµС‚"))

    assert reply == "РћРє"
    assert calls[0][0] == ("anthropic/claude-haiku-4.5", 1000, 2000, 0.011, "bot", "bot:phone")
    assert calls[0][1]["usage"]["cost"] == 0.011


def test_tours_turn_uses_bot_specific_manager_name(monkeypatch):
    """Второй тур-бот может говорить от имени Сезим, не меняя общий сценарий туров."""
    state = DialogState(user_id="u-sezim", funnel="tours", manager_name="Сезим")
    fake = _patch_client(monkeypatch, _text("Ок"))

    reply = asyncio.run(runner.run_tours_turn(state, "хочу тур"))

    assert reply == "Ок"
    system = fake.messages.create.await_args.kwargs["system"]
    assert "Я Сезим, ваш менеджер Frunze Travel" in system
    assert "Я Адеми, ваш менеджер Frunze Travel" not in system


def test_dozhim_flag_off_keeps_system_unchanged(monkeypatch):
    state = DialogState(user_id="u-dozhim-off", funnel="tours")
    fake = _patch_client(monkeypatch, _text("Ок"))
    monkeypatch.setattr(runner.flags, "get_flag", AsyncMock(return_value=False))

    asyncio.run(runner.run_tours_turn(state, "дороговато"))

    system = fake.messages.create.await_args.kwargs["system"]
    assert system == runner.TOURS_SYSTEM
    assert "ЦЕНОВАЯ ВИЛКА" not in system


def test_dozhim_flag_on_appends_prompt_block(monkeypatch):
    state = DialogState(user_id="u-dozhim-on", funnel="tours")
    fake = _patch_client(monkeypatch, _text("Ок"))
    monkeypatch.setattr(runner.flags, "get_flag", AsyncMock(return_value=True))

    asyncio.run(runner.run_tours_turn(state, "дороговато"))

    system = fake.messages.create.await_args.kwargs["system"]
    assert "ЦЕНОВАЯ ВИЛКА" in system
    assert system == runner.TOURS_SYSTEM + "\n\n" + runner.DOZHIM_AND_PRICE_FORK


def test_dozhim_on_preserves_manager_persona(monkeypatch):
    state = DialogState(user_id="u-sezim-dozhim", funnel="tours", manager_name="Сезим")
    fake = _patch_client(monkeypatch, _text("Ок"))
    monkeypatch.setattr(runner.flags, "get_flag", AsyncMock(return_value=True))

    asyncio.run(runner.run_tours_turn(state, "дороговато"))

    system = fake.messages.create.await_args.kwargs["system"]
    assert "Я Сезим, ваш менеджер Frunze Travel" in system
    assert "ЦЕНОВАЯ ВИЛКА" in system
    assert system == runner.tours_system_for_manager("Сезим") + "\n\n" + runner.DOZHIM_AND_PRICE_FORK


def test_max_iterations_guard(monkeypatch):
    """Если Claude бесконечно зовёт инструменты — выходим по лимиту с безопасным ответом."""
    state = DialogState(user_id="u2", funnel="tours")
    fake = _patch_client(monkeypatch, _tool_use(), repeat_last=True)
    monkeypatch.setattr(runner._tourvisor, "search_detailed", AsyncMock(return_value=_found(["X"])))

    reply = asyncio.run(runner.run_tours_turn(state, "тур"))

    assert reply  # не пусто — есть запасная фраза
    assert fake.messages.create.await_count == runner.MAX_TOOL_ITERATIONS


def test_search_tool_graceful_degrade(monkeypatch):
    """Ошибка TourVisor не валит диалог — инструмент возвращает понятное сообщение."""
    state = DialogState(user_id="u3", funnel="tours")
    crm = get_crm()
    monkeypatch.setattr(runner._tourvisor, "search_detailed", AsyncMock(side_effect=TourVisorError("auth")))

    out = asyncio.run(runner._tours_exec_tool("search_tours", {"destination": "Турция"}, state, crm))

    assert "менеджер" in out.lower()


def test_tours_office_gate_asks_name_before_escalation():
    """Горячий тур-лид без имени не уезжает в офис преждевременно."""
    state = DialogState(
        user_id="u-office-name",
        funnel="tours",
        qualification={"selected_option": "PALMORA LARA HOTEL 4*"},
    )
    crm = get_crm()

    out = asyncio.run(runner._tours_exec_tool(
        "escalate_to_office",
        {"reason": "клиент думает завтра прийти в офис"},
        state,
        crm,
    ))

    assert state.stage == "greeting"
    assert "имя" in out.lower()
    assert "менеджер уже ждёт" in out


def test_tours_office_gate_asks_visit_time_before_escalation():
    """Имя без времени ещё не считается подтверждённой записью в офис."""
    state = DialogState(
        user_id="u-office-time",
        funnel="tours",
        qualification={"name": "Alan", "selected_option": "PALMORA LARA HOTEL 4*"},
    )
    crm = get_crm()

    out = asyncio.run(runner._tours_exec_tool(
        "escalate_to_office",
        {"reason": "клиент хочет в офис"},
        state,
        crm,
    ))

    assert state.stage == "greeting"
    assert "время" in out.lower()
    assert "менеджер уже ждёт" in out


def test_tours_office_escalates_after_name_and_visit_time():
    """После имени и времени визита executor фиксирует офисную стадию и данные карточки."""
    state = DialogState(user_id="u-office-ok", funnel="tours")
    crm = get_crm()

    out = asyncio.run(runner._tours_exec_tool(
        "escalate_to_office",
        {
            "reason": "клиент придёт завтра в офис",
            "name": "Alan",
            "visit_time": "завтра в 15:00",
            "selected_option": "PALMORA LARA HOTEL 4*",
        },
        state,
        crm,
    ))

    assert state.stage == "office"
    assert state.qualification["name"] == "Alan"
    assert state.qualification["visit_time"] == "завтра в 15:00"
    assert state.qualification["selected_option"] == "PALMORA LARA HOTEL 4*"
    assert "загранпаспорта" in out


def test_visa_turn_scores_and_replies(monkeypatch):
    """Воронка «Визы» на общем run_turn: score_visa отрабатывает → финальный текст."""
    state = DialogState(user_id="v1", funnel="visa")
    fake = _patch_client(
        monkeypatch,
        _tool_use(name="score_visa", inp={"country": "Германия", "prior_visas": "да"}, id="v"),
        _text("Ваши шансы — высокие. Приглашаю на консультацию."),
    )
    reply = asyncio.run(runner.run_visa_turn(state, "нужна виза в Германию"))

    assert reply and "консультаци" in reply.lower()
    assert state.deal_id is not None  # лид по визе создан
    assert fake.messages.create.await_count == 2


def test_visa_price_preempts_llm_and_returns_single_country(monkeypatch):
    """Вопрос цены по США не должен уходить в LLM, чтобы не выдать весь прайс."""
    state = DialogState(user_id="v-price", funnel="visa")
    fake = _patch_client(monkeypatch, _text("не должно использоваться"))

    reply = asyncio.run(runner.run_visa_turn(state, "Сколько стоит виза в США?"))

    assert "250$" in reply
    assert "185$" in reply
    assert "Шенген" not in reply
    assert fake.messages.create.await_count == 0


def test_orchestrator_visa_price_preempts_faq_and_llm(monkeypatch):
    """Orchestrator checks scoped visa pricing before generic FAQ rules."""
    from app.channels.base import ChannelAdapter, Message
    from app.config import BotConfig
    from app.core import flags
    from app.core.faq import reset as reset_faq, seed_defaults
    from app.core.orchestrator import Orchestrator
    from app.core.state import get_state_store

    class RecordingChannel(ChannelAdapter):
        channel = "whatsapp"

        def __init__(self):
            self.sent = []

        async def parse(self, raw):  # pragma: no cover
            raise NotImplementedError

        async def send(self, chat_id, text, **kwargs):
            self.sent.append(text)
            return "msg-id"

    async def scenario():
        reset_faq()
        await seed_defaults()
        await flags.set_flag("bots_enabled:visa-test", True)
        state = await get_state_store().load("visa-test:996700001")
        state.funnel = "visa"
        await get_state_store().save(state)
        ch = RecordingChannel()
        orch = Orchestrator(ch, bot=BotConfig(id="visa-test", scenario="visa", title="Visa"))
        await orch.handle(Message(
            channel="whatsapp",
            user_id="996700001",
            chat_id="996700001@c.us",
            text="Сколько стоит виза в США?",
        ))
        return ch.sent

    fake = _patch_client(monkeypatch, _text("не должно использоваться"))
    sent = asyncio.run(scenario())

    assert len(sent) == 1
    assert "250$" in sent[0]
    assert "Шенген" not in sent[0]
    assert fake.messages.create.await_count == 0


def test_visa_self_apply_retention_then_handoff(monkeypatch):
    """Self-visa один раз удерживаем мягко, на повторе передаём менеджеру."""
    state = DialogState(user_id="v-self", funnel="visa")
    fake = _patch_client(monkeypatch, _text("не должно использоваться"))

    first = asyncio.run(runner.run_visa_turn(state, "Я сам оформлю визу"))
    second = asyncio.run(runner.run_visa_turn(state, "Нет, точно без вас сделаю"))

    assert "проверяем анкету" in first
    assert "Передам менеджеру" in second
    assert state.stage == "manager"
    assert state.intercepted is True
    assert fake.messages.create.await_count == 0


def test_visa_category_thresholds():
    """Категории шансов по порогам."""
    from app.funnels.visa import visa_category
    assert visa_category(80) == "высокие"
    assert visa_category(50) == "средние"
    assert visa_category(20) == "низкие"


def test_tickets_turn_submits_request(monkeypatch):
    """Воронка «Билеты»: submit_request фиксирует заявку и создаёт лид."""
    state = DialogState(user_id="b1", funnel="tickets")
    fake = _patch_client(
        monkeypatch,
        _tool_use(name="submit_request",
                  inp={"route": "Бишкек-Москва", "dates": "10.07", "passengers": "2"}, id="b"),
        _text("Заявка принята, менеджер свяжется с вами."),
    )
    reply = asyncio.run(runner.run_tickets_turn(state, "нужен билет в Москву"))

    assert reply and "менеджер" in reply.lower()
    assert state.deal_id is not None
    assert state.qualification.get("route") == "Бишкек-Москва"
    assert fake.messages.create.await_count == 2
