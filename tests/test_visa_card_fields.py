# -*- coding: utf-8 -*-
"""Отдельные поля визовой карточки — ответ Медины 11.11.2026, вопрос 6.

Её просьба: гражданство, страна назначения, тип визы, даты поездки и стоимость вместо
свободной анкеты, чтобы по ним можно было фильтровать и собрать отчёт «клиенты по
странам» (её вопрос 21). Заполняет менеджер руками.

Поэтому проверяем не «сохраняется ли строка», а то, из-за чего отчёт по странам
рассыпался бы: закрытые справочники, стирание ошибочного значения, отказ на кривой
сумме целиком (а не наполовину) и запрет править чужую карточку. Плюс отдельно —
что сохранение полей НЕ забирает клиента себе: сторож владения знает три действия, и
с четвёртым он на ничьём лиде доходит до закрепления.
"""
import asyncio

import pytest

import app.admin.router as admin_router
from app.integrations.panel.store import get_conversation_store

from fastapi.testclient import TestClient

import app.main as main
from tests.test_panel import _auth_client, _clear_memory


def _client_as(login: str, monkeypatch):
    """Вход конкретным менеджером: у `_auth_client` из test_panel логин зашит (admin).

    Менеджера надо сначала завести в настройках — иначе вход не пройдёт, и тест про
    чужую карточку молча проверял бы отказ по неверному паролю, а не по владению.
    """
    from app.config import ManagerConfig, settings as app_settings
    monkeypatch.setattr(app_settings, "managers",
                        [ManagerConfig(login=name, name=name, password="SYN-ONLY")
                         for name in ("admin", "medina", "eliza")])
    client = TestClient(main.app, base_url="https://testserver")
    resp = client.post("/admin/login", data={"login": login, "password": "SYN-ONLY"})
    assert resp.status_code == 200, f"вход как {login} не прошёл"
    return client


@pytest.fixture(autouse=True)
def _clean_flags():
    from app.core import flags
    flags.reset()
    yield
    flags.reset()


def _seed(user_id: str = "getvisa:996700888001", funnel: str = "visa",
          assigned_to: str | None = None) -> str:
    """Диалог плюс включённый тумблер.

    Тумблер ставится ЗДЕСЬ, а не в фикстуре: `_clear_memory` сбрасывает и хранилище
    флагов, поэтому флаг, выставленный до него, молча терялся — и тест «блок виден»
    падал, хотя код был верный.
    """
    from app.core import flags
    _clear_memory()
    asyncio.run(flags.set_flag("visa_card_fields_enabled", True))
    store = get_conversation_store()
    asyncio.run(store.add_message(user_id, "client", "нужна виза в Германию",
                                  channel="whatsapp"))
    asyncio.run(store.update_meta(user_id, funnel=funnel, stage="manager",
                                  assigned_to=assigned_to))
    return user_id


def _conv(user_id: str):
    return asyncio.run(get_conversation_store().get(user_id))


def _post(client, user_id, **fields):
    data = {"citizenship": "", "country": "", "visa_type": "",
            "travel_dates": "", "cost": "", "cost_currency": ""}
    data.update(fields)
    return client.post(f"/admin/conversation/{user_id}/visa-fields", data=data)


# --- справочники ------------------------------------------------------------

def test_the_five_fields_are_the_ones_she_asked_for():
    """Пять полей из её вопроса 6 — именно эти, и они в представлении карточки."""
    from app.integrations.panel.store import ConversationView
    for field in ("visa_citizenship", "visa_country", "visa_type",
                  "visa_travel_dates", "visa_cost"):
        assert field in ConversationView.__dataclass_fields__, field


def test_the_visa_type_catalogue_is_closed():
    """Свободный ввод типа визы убил бы группировку, ради которой поля заводились."""
    user_id = _seed()
    client = _auth_client()

    _post(client, user_id, visa_type="рабочая-наверное")

    assert _conv(user_id).visa_type == ""


def test_a_known_visa_type_is_saved():
    user_id = _seed()
    client = _auth_client()

    _post(client, user_id, visa_type="work")

    assert _conv(user_id).visa_type == "work"


def test_the_citizenship_catalogue_is_closed():
    user_id = _seed()
    client = _auth_client()

    _post(client, user_id, citizenship="Нарния")

    assert _conv(user_id).visa_citizenship == ""


def test_an_unknown_currency_is_refused_and_nothing_is_written():
    """Валюта из закрытого списка, и кривая валюта отклоняет форму целиком.

    Раньше этот тест закреплял обратное — «валюту молча отбросить, сумму сохранить».
    Ревью 12.11.2026 показало, почему так нельзя: пустая валюта здесь ОЧИЩАЕТ поле,
    значит молчаливый сброс затирал бы уже сохранённую валюту у ранее введённой суммы,
    и менеджеру при этом писали «сохранено». Сумма без валюты — это к тому же число
    без смысла в её отчёте по странам.
    """
    user_id = _seed()
    client = _auth_client()

    resp = _post(client, user_id, cost="250", cost_currency="ДОЛЛАРЫ")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    conv = _conv(user_id)
    assert conv.visa_cost is None
    assert conv.visa_cost_currency == ""


# --- сохранение и стирание --------------------------------------------------

def test_all_five_fields_round_trip():
    user_id = _seed()
    client = _auth_client()

    _post(client, user_id, citizenship="KG", country="Германия", visa_type="tourist",
          travel_dates="конец августа", cost="250", cost_currency="USD")

    conv = _conv(user_id)
    assert conv.visa_citizenship == "KG"
    assert conv.visa_country == "Германия"
    assert conv.visa_type == "tourist"
    assert conv.visa_travel_dates == "конец августа"
    assert conv.visa_cost == 250.0
    assert conv.visa_cost_currency == "USD"


def test_an_empty_field_clears_the_value():
    """Менеджер должен уметь стереть ошибку — это форма, а не кнопка на поле."""
    user_id = _seed()
    client = _auth_client()
    _post(client, user_id, country="Германия", cost="250", cost_currency="USD")

    _post(client, user_id)                      # пустая форма

    conv = _conv(user_id)
    assert conv.visa_country == ""
    assert conv.visa_cost is None


def test_a_comma_decimal_is_accepted():
    """С телефона запятую вводят чаще точки — отказ на ней был бы придиркой."""
    user_id = _seed()
    client = _auth_client()

    _post(client, user_id, cost="1250,50", cost_currency="KGS")

    assert _conv(user_id).visa_cost == 1250.5


# --- отказы -----------------------------------------------------------------

def test_a_broken_amount_saves_nothing_at_all():
    """Главный предохранитель: не «сохранили четыре поля из пяти» молча.

    Менеджер видел бы «сохранено», а сумма не записалась бы — и он узнал бы об этом
    только из отчёта, где её нет.
    """
    user_id = _seed()
    client = _auth_client()

    resp = _post(client, user_id, country="Германия", cost="двести пятьдесят")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    conv = _conv(user_id)
    assert conv.visa_country == "", "при отказе не должно сохраниться НИЧЕГО"
    assert conv.visa_cost is None


def test_a_negative_amount_is_refused():
    user_id = _seed()
    client = _auth_client()

    resp = _post(client, user_id, cost="-100")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    assert _conv(user_id).visa_cost is None


def test_an_absurd_amount_is_refused():
    """Опечатка в порядке цифр: «250000000» вместо «250» в отчёт попадать не должна."""
    user_id = _seed()
    client = _auth_client()

    resp = _post(client, user_id, cost="250000000")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    assert _conv(user_id).visa_cost is None


def test_a_colleagues_card_cannot_be_edited(monkeypatch):
    """Данные клиента правит владелец, как и договор (contracts._conversation)."""
    user_id = _seed(assigned_to="medina")
    client = _client_as("eliza", monkeypatch)

    resp = _post(client, user_id, country="Германия")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    assert _conv(user_id).visa_country == ""


def test_an_unowned_card_is_editable_and_stays_unowned(monkeypatch):
    """Заполнение полей НЕ забирает клиента себе.

    Сторож владения знает release/send/claim, и с любым другим действием на ничьём
    лиде он доходит до `assign_locked`. Поэтому здесь своя проверка владения — и вот
    её смысл: карточку заполнить можно, владельцем при этом никто не становится.
    """
    user_id = _seed(assigned_to="")
    client = _client_as("eliza", monkeypatch)

    _post(client, user_id, country="Германия")

    conv = _conv(user_id)
    assert conv.visa_country == "Германия"
    assert (conv.assigned_to or "") == "", "сохранение полей не должно закреплять лид"


# --- где блок виден --------------------------------------------------------

def test_the_block_is_hidden_on_a_tours_card():
    """Туровому менеджеру тип визы ни к чему: пять лишних полей никто не заполнит."""
    user_id = _seed(user_id="frunze_tours:996700888002", funnel="tours")
    client = _auth_client()

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "Данные по визе" not in page


def test_the_block_is_shown_on_a_visa_card():
    user_id = _seed()
    client = _auth_client()

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "Данные по визе" in page
    assert "Страна назначения" in page


def test_the_flag_hides_the_block():
    """Дефолт OFF: выкат кода ничего не меняет, включение — отдельное решение."""
    from app.core import flags
    user_id = _seed()
    asyncio.run(flags.set_flag("visa_card_fields_enabled", False))
    client = _auth_client()

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "Данные по визе" not in page


# --- флаг и воронка в самом маршруте ---------------------------------------

def test_a_post_with_the_flag_off_writes_nothing():
    """«Флаг OFF — поведение не меняется» должно быть правдой и для POST.

    Блок в карточке при OFF не рисуется, но форма могла остаться открытой в чужой
    вкладке, да и правило `CLAUDE.md` §2.3 — про выключенную функцию, а не про
    спрятанную кнопку. Ревью 12.11.2026 нашло, что маршрут писал колонки при OFF.
    """
    from app.core import flags
    user_id = _seed()
    asyncio.run(flags.set_flag("visa_card_fields_enabled", False))
    client = _auth_client()

    resp = _post(client, user_id, country="Германия", visa_type="work")

    assert resp.status_code == 404
    conv = _conv(user_id)
    assert conv.visa_country == "" and conv.visa_type == ""


def test_a_post_to_a_tours_card_is_refused():
    """Поля визовые: в туровую карточку они попадать не должны даже POST'ом."""
    user_id = _seed(user_id="frunze_tours:996700888003", funnel="tours")
    client = _auth_client()

    resp = _post(client, user_id, country="Германия")

    assert resp.status_code == 404
    assert _conv(user_id).visa_country == ""


# --- суммы, которые проходили мимо порогов ---------------------------------

@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity", "1_0"])
def test_a_non_finite_amount_is_refused(raw):
    """`float("nan")` разбирается, а `nan < 0` и `nan > 1e6` оба False.

    То есть пороги NaN пропускают, и он уезжает в DOUBLE PRECISION — после чего любая
    SUM или AVG в отчёте «клиенты по странам» становится NaN целиком. Подчёркивание
    тоже отсекаем: `float("1_0")` это 10.0, а менеджер имел в виду другое.
    """
    user_id = _seed()
    client = _auth_client()

    resp = _post(client, user_id, cost=raw)

    assert resp.headers.get("X-Action-Outcome") == "denied", raw
    assert _conv(user_id).visa_cost is None, raw


def test_a_refused_amount_leaves_all_five_fields_untouched():
    """Отказ означает «не сохранено НИЧЕГО» — проверяем все пять полей, не одно.

    Прежний тест смотрел только страну и сумму: если бы код сохранял гражданство,
    тип и даты до проверки суммы, он бы прошёл (ревью 12.11.2026).
    """
    user_id = _seed()
    client = _auth_client()
    _post(client, user_id, citizenship="KG", country="Германия", visa_type="work",
          travel_dates="март", cost="100", cost_currency="USD")

    resp = _post(client, user_id, citizenship="RU", country="Польша", visa_type="study",
                 travel_dates="апрель", cost="nan", cost_currency="EUR")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    conv = _conv(user_id)
    assert conv.visa_citizenship == "KG"
    assert conv.visa_country == "Германия"
    assert conv.visa_type == "work"
    assert conv.visa_travel_dates == "март"
    assert conv.visa_cost == 100.0
    assert conv.visa_cost_currency == "USD"


def test_an_unknown_catalogue_code_is_refused_not_silently_cleared():
    """Пустое значение здесь СТИРАЕТ, поэтому кривой код нельзя превращать в пустой.

    Иначе устаревшая вкладка после смены справочника затирала бы сохранённое, а
    менеджеру писали «сохранено» (ревью 12.11.2026).
    """
    user_id = _seed()
    client = _auth_client()
    _post(client, user_id, visa_type="work")

    resp = _post(client, user_id, visa_type="рабочая-наверное")

    assert resp.headers.get("X-Action-Outcome") == "denied"
    assert _conv(user_id).visa_type == "work", "сохранённое значение должно уцелеть"


def test_a_value_with_markup_is_escaped_in_the_card():
    """Значения приходят из формы и печатаются обратно в атрибут value."""
    user_id = _seed()
    client = _auth_client()
    _post(client, user_id, country='Герм"><script>alert(1)</script>')

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page or "&#34;" in page or "&gt;" in page


# --- реальный путь: Postgres-хранилище -------------------------------------

def test_the_fields_survive_the_real_postgres_path():
    """Запись и чтение через PostgresConversationStore, а не через память.

    Ночью 12.11 причина закрытия писалась в базу и НЕ читалась обратно: поле забыли в
    `_view`, а тесты шли по memory-хранилищу, которое отдаёт сам объект. Памятка
    проекта «тест обязан идти реальным путём» — ровно про это.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.integrations.crm.db import init_models
    from app.integrations.panel.store import PostgresConversationStore

    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://",
                                     connect_args={"check_same_thread": False},
                                     poolclass=StaticPool)
        await init_models(engine)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        store = PostgresConversationStore(sessionmaker=sm)
        uid = "getvisa:996700888009"
        await store.add_message(uid, "client", "виза в Германию",
                                channel="whatsapp", bot_id="getvisa")
        await store.update_meta(uid, funnel="visa")

        await store.set_visa_fields(uid, citizenship="KG", country="Германия",
                                    visa_type="tourist", travel_dates="конец августа",
                                    cost=250.0, cost_currency="USD")
        conv = await store.get(uid)
        assert conv.visa_citizenship == "KG"
        assert conv.visa_country == "Германия"
        assert conv.visa_type == "tourist"
        assert conv.visa_travel_dates == "конец августа"
        assert conv.visa_cost == 250.0
        assert conv.visa_cost_currency == "USD"

        # поля доезжают и до списка карточек, не только до одного диалога
        card = (await store.list_cards("visa"))[0]
        assert card.visa_country == "Германия"

        # стирание суммы отдельным признаком
        await store.set_visa_fields(uid, clear_cost=True)
        assert (await store.get(uid)).visa_cost is None
        # ...а остальные поля при этом на месте
        assert (await store.get(uid)).visa_country == "Германия"

        # несуществующий диалог не создаётся молча
        await store.set_visa_fields("getvisa:000000000", country="Польша")
        assert await store.get("getvisa:000000000") is None

        await engine.dispose()

    asyncio.run(scenario())


def test_a_manager_without_the_visa_direction_is_refused(monkeypatch):
    """Второй контур: доступ к БОТУ ещё не значит право на НАПРАВЛЕНИЕ.

    Обычно одно следует из другого — направление считается из того же скоупа ботов.
    Но `direction_for_bot` отдаёт пустое для бота, которого нет ни в реестре, ни в
    карте направлений, и тогда менеджер видит диалог (бот в скоупе), а направления у
    него нет ни одного. Это настроечная ошибка — завели нового визового бота и забыли
    в карте, — и форма договора в такой ситуации отвечает 404. Поля карточки обязаны
    вести себя так же.

    Мутация показала, что без этого теста проверка прав была непроверенной: выключаешь
    её — все 28 тестов зелёные (ревью 12.11.2026 это и предсказало).
    """
    from app.core import manager_scope
    unknown_bot = "visa_new_channel"      # нет ни в реестре, ни в _FALLBACK_DIRECTIONS
    monkeypatch.setitem(manager_scope.BOT_SCOPE_BY_MANAGER, "eliza", {unknown_bot})
    user_id = _seed(user_id=f"{unknown_bot}:996700888004")
    client = _client_as("eliza", monkeypatch)

    resp = _post(client, user_id, country="Германия")

    assert resp.status_code == 404
    assert _conv(user_id).visa_country == ""


def test_the_same_manager_with_a_mapped_bot_can_edit(monkeypatch):
    """Парный тест: с нормально настроенным визовым ботом та же Элиза поля правит.

    Без него предыдущий тест мог бы проходить по любой другой причине — например если
    маршрут отказывает всем, кто не полный админ.
    """
    from app.core import manager_scope
    monkeypatch.setitem(manager_scope.BOT_SCOPE_BY_MANAGER, "eliza", {"getvisa"})
    user_id = _seed(user_id="getvisa:996700888005")
    client = _client_as("eliza", monkeypatch)

    resp = _post(client, user_id, country="Германия")

    assert resp.status_code == 200
    assert _conv(user_id).visa_country == "Германия"
