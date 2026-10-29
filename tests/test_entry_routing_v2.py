"""ГЕЙТ: маршрутизация v2 — кто попадает во въездную ветку, а кто нет.

Флаг `kg_entry_routing_v2_enabled`, дефолт OFF.

Откуда взялись эти реплики. Замер 28.10 по боевой базе (2324 диалога GetVisa) и прогон
детектора В БОЕВОМ КОНТЕЙНЕРЕ, где бандл знаний загружен и основ стран 112. Каждая
реплика ниже воспроизводилась на проде, а не придумана: двенадцать не попадали во
ветку, одна попадала неверно, одна — контрольная.

Случай с билетами реальный: 26.10 клиент написал «сколько будет стоить билет из Бишкека
в Сеул», и детектор отправил его во въездную ветку для иностранцев из-за слабого
маркера «Бишкек». Это 1 диалог из 8 за пять дней.

Главная проверка файла — последняя: при выключенном флаге детектор обязан отвечать
ДОСЛОВНО как раньше. Иначе выкатка меняет поведение на боевом номере без решения
человека, а это ровно то, что протокол запрещает.
"""
import pytest

from app.core.entry_intent import detect

# (реплика, ожидание v2, почему v1 ошибался)
LIVE_MISSES = [
    ("I'm American, want to travel in Kyrgyzstan for 45 days in May", "kg_entry",
     "ТЗ Б.8 пример 1: сильный маркер знал 'to kyrgyzstan', но не 'in kyrgyzstan', "
     "а слова 'visa' в реплике нет"),
    ("Меня в прошлом году выдворили из Кыргызстана. Сейчас хочу снова приехать, "
     "оформите визу", "kg_entry",
     "'из Кыргызстана' — падеж и обратное направление, но человек едет сюда"),
    ("Хочу оформить ВНЖ Кыргызстана и потом гражданство. С чего начать?", "kg_entry",
     "'ВНЖ Кыргызстана' — кыргызский документ в родительном падеже"),
    ("Я из Казахстана, въезжал 15 августа и 2 октября, выезжал на неделю. "
     "Сколько у меня осталось дней?", "kg_entry",
     "'выезжал' перебивал 'въезжал': иностранец, перечисляющий въезды и выезды, "
     "считался уезжающим"),
    ("Я гражданин Казахстана, въехал 1 октября. Сколько дней у меня осталось?",
     "kg_entry", "в списке приезда была форма 'въехать', а не основа 'въеха'"),
    ("Я лежу в больнице в Бишкеке, выехать до конца срока не смогу. Что делать?",
     "kg_entry", "место плюс признак пребывания в КР ('конца срока')"),
    ("Какие визы Кыргызстана вообще можно продлить, а какие нет?", "kg_entry",
     "'визы Кыргызстана' — родительный падеж рядом с документом"),
    ("I am a journalist and I entered Kyrgyzstan as a tourist. "
     "I want to film a report here.", "kg_entry",
     "'enter kyrgyzstan' не подстрока 'entered kyrgyzstan' — нужна основа"),
    ("У меня была действующая виза, но на границе в Манасе не впустили и отправили "
     "обратно", "kg_entry", "'Манас' и 'границе' — место плюс признак пребывания"),
    ("Салам! Мен Өзбекстандан келем, Кыргызстанга виза керекпи?", "kg_entry",
     "кыргызского языка в детекторе не было вовсе: 'Кыргызстанга' — датив"),
    ("Я из Ирака. Куда прислать скан паспорта, чтобы вы сразу начали?", "ambiguous",
     "назвал своё иностранное гражданство, направления нет — спрашиваем, не угадываем"),
]

LIVE_LEAKS = [
    ("сколько будет стоить билет из Бишкека в Сеул через Алматы 25 дек - 9 янв",
     "живой случай 26.10: запрос билетов уезжал во въездную ветку из-за 'Бишкек'"),
    ("Хотим в Египет из Бишкека в феврале, бюджет 3000 долларов на двоих",
     "туровой запрос: 'Бишкек' как пункт вылета, а не направление"),
]


@pytest.mark.parametrize("text,expected,why", LIVE_MISSES)
def test_v2_takes_what_belongs_to_the_entry_branch(text, expected, why):
    assert detect(text, sticky=None, routing_v2=True) == expected, why


@pytest.mark.parametrize("text,why", LIVE_LEAKS)
def test_v2_does_not_take_tours_and_tickets(text, why):
    assert detect(text, sticky=None, routing_v2=True) != "kg_entry", why


def test_control_tour_request_is_untouched():
    """Контрольная реплика: она и раньше вела себя правильно, и обязана дальше."""
    assert detect("Хотим в Турцию в июне на 10 дней", sticky=None,
                  routing_v2=True) != "kg_entry"


# --- Чего v2 не должен сломать ---------------------------------------------------

UNCHANGED = [
    # Выездные: гражданин КР едет за границу. Самый дорогой класс ошибок — забрать их.
    ("Я гражданка Кыргызстана, нужна виза в Польшу. Сколько стоит?", "outbound"),
    ("Нужна виза в США, запишите на собеседование", "outbound"),
    ("Шенген на двоих, когда ближайшие слоты?", "outbound"),
    ("Я из Германии, нужна виза в Польшу", "outbound"),
    # Въездные, которые работали и до правки.
    ("Я из Нигерии, хочу приехать туристом на 50 дней", "kg_entry"),
    ("Нужна виза в Кыргызстан, я гражданин Индии", "kg_entry"),
    ("Регистрация иностранца — какие сроки?", "kg_entry"),
    # Ни то ни другое.
    ("Здравствуйте", "unknown"),
    ("", "unknown"),
]


@pytest.mark.parametrize("text,expected", UNCHANGED)
def test_v2_keeps_the_answers_that_were_already_right(text, expected):
    assert detect(text, sticky=None, routing_v2=True) == expected


# Таблица независимого ревью 28.10. Одиннадцать реплик выездного клиента, которые
# первая версия v2 забирала во въездную ветку или превращала в вопрос про направление.
# Каждая воспроизведена моим собственным прогоном, прежде чем чинить. Это самый дорогой
# класс ошибки: выездной поток работает и приносит деньги.
REVIEW_OUTBOUND = [
    ("У меня паспорт Кыргызстана, нужна виза в США",
     "окно `_KG_DOC` пересекало запятую: рядом оказывались «Кыргызстана» и «виза» "
     "из двух разных частей фразы"),
    ("Нужна виза в США для граждан Кыргызстана", "то же окно, обратный порядок"),
    ("Гражданам Кыргызстана нужна виза в Корею?", "то же окно"),
    ("Хочу визу в Польшу по кыргызскому паспорту", "паспорт клиента, а не наша виза"),
    ("Список документов кыргызстанцам на шенген",
     "последняя буква слова «документов» принималась за предлог направления"),
    ("Живу у родственников кыргызстанцев, нужен шенген", "то же, без границы слова"),
    ("Кыргызстанда жашайм, АКШга виза керек",
     "кыргызский локатив «в Кыргызстане» — это место, а не направление"),
    ("Нужен шенген, вылет из Кыргызстана",
     "правила v2 стояли до выездного вето и не давали ему сработать"),
    ("Я прилетел в Бишкек и хочу шенген", "то же: место плюс приезд перебивали вето"),
    ("Паспорт кыргызский, хочу записаться на собеседование", "то же"),
    ("Билет из Кыргызстана в Сеул сколько стоит?", "билеты — выездная работа"),
]


@pytest.mark.parametrize("text,why", REVIEW_OUTBOUND)
def test_review_outbound_regressions_are_gone(text, why):
    """Выездной клиент не попадает во въездную ветку и не получает вопроса."""
    assert detect(text, sticky=None, routing_v2=True) != "kg_entry", why


@pytest.mark.parametrize("text,why", REVIEW_OUTBOUND)
def test_review_outbound_gets_no_direction_question(text, why):
    """И вопроса про направление тоже: клиент прямо сказал, куда ему нужно."""
    assert detect(text, sticky=None, routing_v2=True) != "ambiguous", why


# --- Ответ на уточняющий вопрос разбирается, а не теряется ----------------------

@pytest.mark.parametrize("answer,expected", [
    ("в Кыргызстан", "kg_entry"), ("сюда", "kg_entry"), ("к вам", "kg_entry"),
    ("приеду к вам", "kg_entry"), ("to Kyrgyzstan", "kg_entry"),
    ("из Кыргызстана", "outbound"), ("туда", "outbound"), ("отсюда", "outbound"),
    ("за границу", "outbound"), ("from Kyrgyzstan", "outbound"),
    ("не знаю", None), ("🙂", None), ("", None), ("ага", None),
])
def test_direction_answer_is_parsed(answer, expected):
    from app.funnels.visa import _direction_answer
    assert _direction_answer(answer) == expected


def test_unparsed_answer_goes_to_a_human_not_to_the_outbound_funnel(monkeypatch):
    """«не знаю» в ответ на вопрос — передаём человеку, а не уводим молча.

    Прежде `_entry_branch` возвращал None, воронка шла прежним путём, и клиент получал
    «Как могу к вам обращаться?». Найдено независимым ревью 28.10.
    """
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)
    state = _state()
    asked = asyncio.run(visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state))
    assert asked is not None
    answer = asyncio.run(visa._entry_branch(_msg("не знаю"), state))
    assert answer is not None and "специалист" in answer
    assert state.stage == "manager"


def test_answer_here_opens_the_entry_branch(monkeypatch):
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)
    monkeypatch.setattr(app.config.settings, "openrouter_api_key", "", raising=False)
    state = _state()
    asyncio.run(visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state))
    reply = asyncio.run(visa._entry_branch(_msg("сюда, я приезжаю к вам"), state))
    assert reply is not None
    assert state.qualification.get("entry_mode") == "kg_entry"


def test_answer_away_returns_to_the_outbound_funnel(monkeypatch):
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)
    state = _state()
    asyncio.run(visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state))
    assert asyncio.run(visa._entry_branch(_msg("из Кыргызстана, в Польшу"), state)) is None
    assert state.qualification.get("entry_mode") is None
    assert state.stage != "manager"


def test_outbound_client_who_mentions_bishkek_stays_outbound():
    """«Живу в Бишкеке, хочу выехать на учёбу» — выездной клиент, и остаётся им."""
    assert detect("Живу в Бишкеке, хочу выехать на учёбу в Германию", sticky=None,
                  routing_v2=True) == "outbound"


def test_stickiness_still_wins_over_text():
    assert detect("спасибо", sticky="kg_entry", routing_v2=True) == "kg_entry"
    assert detect("спасибо", sticky="outbound", routing_v2=True) == "outbound"


def test_hard_outbound_evidence_still_breaks_stickiness():
    assert detect("а шенген вы делаете?", sticky="kg_entry",
                  routing_v2=True) == "outbound"


# --- Национальность прилагательным ----------------------------------------------
# Замечание перепроверки 29.10. Живой клиент пишет «я узбек», а не «я гражданин
# Узбекистана», и разбор своего гражданства этой формы не знал. Регрессия: v1 отвечал
# `kg_entry` по слабому маркеру «Бишкек», v2 убрал «Бишкек» из слабых — и реплика
# провалилась в `unknown`, то есть иностранец с рабочим патентом уходил в выездную
# воронку для граждан КР. Ожидания ниже сняты прогоном, а не придуманы.
NATIONALITY_TAKEN = [
    ("Я узбек, работаю на стройке в Бишкеке, нужен патент?", "kg_entry",
     "та самая регрессия: v1 давал kg_entry, v2 терял реплику в unknown"),
    ("Я казах, живу в Бишкеке второй год", "kg_entry",
     "место в КР плюс названная национальность"),
    ("я таджик, просрочил регистрацию", "kg_entry", "признак пребывания в КР"),
    ("мы казахи, въезжали 1 августа и 2 октября, сколько осталось дней?", "kg_entry",
     "множественное число и приезд: v1 не брал её вовсе"),
    ("Я испанец, хочу приехать на 30 дней", "kg_entry",
     "основа «испан» есть в выездном брендинге, и вето забирало испанца себе"),
]

# Выездной клиент, назвавший свою национальность, остаётся выездным: вето считается
# раньше. Это самый дорогой класс ошибки, поэтому проверяется отдельно.
NATIONALITY_OUTBOUND = [
    ("Я русский, нужна виза в Польшу", "вето по стране назначения сильнее"),
    ("я кореец, хочу визу в Корею", "«Корея» как пункт назначения, а не гражданство"),
    ("Я узбек, хочу поехать в Польшу на работу", "иностранец бывает и выездным клиентом"),
]

# Не самоназвание и не иностранец. Эти реплики ветку открывать не должны.
NATIONALITY_NOT_A_CLAIM = [
    ("я русский язык плохо знаю", "unknown", "это про язык, а не про гражданство"),
    ("Виза для узбеков сколько стоит", "unknown", "вопрос про третьих лиц"),
    ("Я кыргыз, нужна виза", "unknown",
     "свой гражданин: ни иностранцем, ни поводом для вопроса о направлении"),
]


@pytest.mark.parametrize("text,expected,why", NATIONALITY_TAKEN)
def test_nationality_adjective_counts_as_foreign_citizenship(text, expected, why):
    assert detect(text, sticky=None, routing_v2=True) == expected, why


@pytest.mark.parametrize("text,why", NATIONALITY_OUTBOUND)
def test_nationality_does_not_take_the_outbound_client(text, why):
    assert detect(text, sticky=None, routing_v2=True) == "outbound", why


@pytest.mark.parametrize("text,expected,why", NATIONALITY_NOT_A_CLAIM)
def test_nationality_without_a_self_claim_changes_nothing(text, expected, why):
    assert detect(text, sticky=None, routing_v2=True) == expected, why


def test_own_nationality_does_not_break_stickiness():
    """«Я испанец» внутри въездного разговора — не улика выездного.

    До правки основа «испан» из выездного брендинга выбивала испанца из ветки, в
    которой он уже сидел, и он начинал получать чужие ответы.
    """
    assert detect("я испанец", sticky="kg_entry", routing_v2=True) == "kg_entry"
    assert detect("а шенген вы делаете?", sticky="kg_entry",
                  routing_v2=True) == "outbound", "твёрдая улика по-прежнему работает"


# --- Главное: при флаге OFF поведение дословно прежнее ---------------------------

ALL_PHRASES = ([t for t, _, _ in LIVE_MISSES] + [t for t, _ in LIVE_LEAKS]
               + [t for t, _ in UNCHANGED]
               + [t for t, _, _ in NATIONALITY_TAKEN]
               + [t for t, _ in NATIONALITY_OUTBOUND]
               + [t for t, _, _ in NATIONALITY_NOT_A_CLAIM]
               + ["Хотим в Турцию в июне на 10 дней",
                  "Живу в Бишкеке, хочу выехать на учёбу в Германию",
                  "Мой паспорт действует ещё четыре месяца. Визу успеем оформить?",
                  "Я гражданин Кыргызстана. Мне нужна виза, чтобы въехать в Кыргызстан?"])

# Что отвечал детектор ДО правки. Снято прогоном в боевом контейнере 28.10 и здесь
# прибито гвоздями: не «должно быть так», а «так было». Любое расхождение означает,
# что выключенный флаг всё-таки изменил поведение на боевом номере.
V1_BASELINE = {
    "I'm American, want to travel in Kyrgyzstan for 45 days in May": "unknown",
    "Меня в прошлом году выдворили из Кыргызстана. Сейчас хочу снова приехать, "
    "оформите визу": "unknown",
    "Хочу оформить ВНЖ Кыргызстана и потом гражданство. С чего начать?": "unknown",
    "Я из Казахстана, въезжал 15 августа и 2 октября, выезжал на неделю. "
    "Сколько у меня осталось дней?": "unknown",
    "Я гражданин Казахстана, въехал 1 октября. Сколько дней у меня осталось?": "unknown",
    "Я лежу в больнице в Бишкеке, выехать до конца срока не смогу. Что делать?": "unknown",
    "Какие визы Кыргызстана вообще можно продлить, а какие нет?": "unknown",
    "I am a journalist and I entered Kyrgyzstan as a tourist. "
    "I want to film a report here.": "unknown",
    "У меня была действующая виза, но на границе в Манасе не впустили и отправили "
    "обратно": "unknown",
    "Салам! Мен Өзбекстандан келем, Кыргызстанга виза керекпи?": "unknown",
    "Я из Ирака. Куда прислать скан паспорта, чтобы вы сразу начали?": "unknown",
    "сколько будет стоить билет из Бишкека в Сеул через Алматы 25 дек - 9 янв": "kg_entry",
    "Хотим в Египет из Бишкека в феврале, бюджет 3000 долларов на двоих": "kg_entry",
    "Хотим в Турцию в июне на 10 дней": "unknown",
    # Национальность прилагательным, снято прогоном 29.10 до правки.
    "Я узбек, работаю на стройке в Бишкеке, нужен патент?": "kg_entry",
    "Я казах, живу в Бишкеке второй год": "kg_entry",
    "я таджик, просрочил регистрацию": "kg_entry",
    "мы казахи, въезжали 1 августа и 2 октября, сколько осталось дней?": "unknown",
    "Я испанец, хочу приехать на 30 дней": "outbound",
    "Я русский, нужна виза в Польшу": "outbound",
    "я кореец, хочу визу в Корею": "outbound",
    "Я узбек, хочу поехать в Польшу на работу": "outbound",
    "я русский язык плохо знаю": "unknown",
    "Виза для узбеков сколько стоит": "unknown",
    "Я кыргыз, нужна виза": "unknown",
}


@pytest.mark.parametrize("text", ALL_PHRASES)
def test_flag_off_changes_nothing(text):
    """Выключенный флаг обязан давать ровно прежний ответ."""
    got = detect(text, sticky=None, routing_v2=False)
    expected = V1_BASELINE.get(text)
    if expected is not None:
        assert got == expected, "выключенный флаг изменил поведение на боевом номере"
    assert got != "ambiguous", "четвёртый исход не существует без флага"


def test_default_call_has_no_v2():
    """Вызов без параметра — прежнее поведение. Чтобы забытый вызов не включил v2."""
    assert detect("Какие визы Кыргызстана можно продлить?") == "unknown"


@pytest.mark.parametrize("text", [
    "виза", "здравствуйте", "добрый день, можно узнать подробнее?", "",
    "сколько стоит", "а документы какие нужны",
])
def test_v2_does_not_turn_ordinary_replies_into_a_question(text):
    """Вопрос о направлении задаётся только когда есть о чём спрашивать.

    Прибитый тест `test_ambiguous_keeps_the_old_behaviour` требует по этим репликам
    прежнее поведение, и v2 его не отменяет: Кыргызстан в них не назван.
    """
    assert detect(text, sticky=None, routing_v2=True) == "unknown"


# --- Воронка: вопрос задаётся, и только один раз ---------------------------------

def _state():
    from app.core.state import DialogState
    s = DialogState(user_id="getvisa:996700000097", funnel="visa")
    return s


def _msg(text):
    from app.channels.base import Message
    return Message(channel="telegram", user_id="u", chat_id="u", text=text)


def test_funnel_asks_about_direction_once(monkeypatch):
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)
    state = _state()

    # Реплика, в которой Кыргызстан назван, а направление неясно.
    first = asyncio.run(visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state))
    assert first is not None and "в Кыргызстан" in first and "из Кыргызстана" in first
    assert state.qualification.get("entry_direction_asked") is True
    # Режим НЕ запомнен: ответ клиента разбирает тот же детектор.
    assert state.qualification.get("entry_mode") is None

    # Второй раз тот же вопрос не задаём, а передаём человеку: угадывать нельзя, а
    # упираться в один и тот же вопрос — тоже не ответ.
    again = asyncio.run(visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state))
    assert again is not None and "специалист" in again
    assert state.stage == "manager"


def test_funnel_says_nothing_new_while_the_flag_is_off(monkeypatch):
    """Дефолт OFF: выкатка кода не меняет поведение на боевом номере GetVisa."""
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", False,
                        raising=False)
    state = _state()
    assert asyncio.run(
        visa._entry_branch(_msg("Хочу разобраться с Кыргызстаном"), state)) is None
    assert "entry_direction_asked" not in state.qualification


def test_outbound_price_is_muted_for_the_entry_and_ambiguous_cases(monkeypatch):
    """Второй вызов распознавателя — гвард выездного прайса в оркестраторе.

    Он обязан знать про флаг. Иначе воронка уходит на v2 и уводит немца во въездную
    ветку, а выездной прайс стреляет РАНЬШЕ воронки и называет ему шенгенские сборы —
    ровно тот дефект, из-за которого гвард и появился 21.10.
    """
    import asyncio
    import app.config
    from app.config import BotConfig
    from app.core.orchestrator import Orchestrator

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)

    class _Channel:
        name = "telegram"

        async def send(self, chat_id, text, **kw):
            return True

        async def parse(self, raw):
            raise NotImplementedError

    orch = Orchestrator(channel=_Channel(), bot=BotConfig(id="getvisa", scenario="visa"))
    state = _state()

    # Въездная реплика: прайс молчит.
    assert asyncio.run(orch._entry_talk(
        _msg("Какие визы Кыргызстана можно продлить?"), state)) is True
    # Неясное направление: прайс тоже молчит, вопрос задаст воронка.
    assert asyncio.run(orch._entry_talk(
        _msg("Хочу разобраться с Кыргызстаном"), state)) is True
    # Выездной клиент: прайс работает как прежде.
    assert asyncio.run(orch._entry_talk(
        _msg("Нужна виза в Польшу, сколько стоит?"), state)) is False


def test_funnel_answers_in_english_to_an_english_client(monkeypatch):
    import asyncio
    import app.config
    from app.funnels import visa

    monkeypatch.setattr(app.config.settings, "kg_entry_enabled", True, raising=False)
    monkeypatch.setattr(app.config.settings, "kg_entry_routing_v2_enabled", True,
                        raising=False)
    state = _state()
    reply = asyncio.run(visa._entry_branch(_msg("I have a question about Kyrgyzstan"),
                                           state))
    assert reply is not None and "to Kyrgyzstan" in reply
    assert "Кыргызстан" not in reply, "русская вставка в английский ответ"
