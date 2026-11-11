# -*- coding: utf-8 -*-
"""Причина закрытия лида — справочник Медины (письменные ответы 11.11.2026, вопрос 5).

Её просьба была точной: отдельная стадия «некачественный клиент» не нужна, нужна
ПРИЧИНА у отказа, и причин восемь. Поэтому проверяем не «есть ли поле», а что
справочник закрытый, что причина живёт только у отказа и что она не переживает смену
исхода: «обратился в другую компанию» на карточке оплатившего клиента — это хуже, чем
отсутствие причины вовсе.
"""
import asyncio

import pytest

import app.admin.router as admin_router
from app.integrations.panel.store import get_conversation_store

from tests.test_panel import _auth_client, _clear_memory


@pytest.fixture(autouse=True)
def _reset_flags():
    from app.core import flags
    flags.reset()
    yield
    flags.reset()


def _seed(user_id: str = "getvisa:996700777001") -> str:
    _clear_memory()
    store = get_conversation_store()
    asyncio.run(store.add_message(user_id, "client", "сколько стоит виза",
                                  channel="whatsapp"))
    asyncio.run(store.update_meta(user_id, funnel="visa", stage="manager"))
    return user_id


def _conv(user_id: str):
    return asyncio.run(get_conversation_store().get(user_id))


def test_the_reason_catalogue_is_hers_word_for_word():
    """Восемь причин, в её порядке и её формулировками."""
    assert [label for _, label in admin_router.LOST_REASONS] == [
        "Не отвечает",
        "Не заинтересован",
        "Высокая стоимость услуг",
        "Передумал оформлять визу",
        "Обратился в другую компанию",
        "Не подходит по требованиям",
        "Ошибочное обращение или спам",
        "Отложил поездку",
    ]


def test_a_reason_is_saved_with_the_refusal():
    user_id = _seed()
    client = _auth_client()

    resp = client.post(f"/admin/conversation/{user_id}/outcome",
                       data={"outcome": "lost", "reason": "competitor"})

    assert resp.status_code == 200
    conv = _conv(user_id)
    assert conv.outcome == "lost" and conv.outcome_reason == "competitor"


def test_a_reason_outside_the_catalogue_is_dropped():
    """Справочник закрытый: чужой код в базу не попадает.

    Поле приходит из браузера, и в отчёте «почему теряем клиентов» произвольные
    строки превратили бы группировку в мусор.
    """
    user_id = _seed()
    client = _auth_client()

    client.post(f"/admin/conversation/{user_id}/outcome",
                data={"outcome": "lost", "reason": "просто так"})

    assert _conv(user_id).outcome_reason == ""


def test_the_reason_does_not_survive_a_change_of_outcome():
    """Клиент вернулся и оплатил — причина отказа обязана исчезнуть."""
    user_id = _seed()
    client = _auth_client()

    client.post(f"/admin/conversation/{user_id}/outcome",
                data={"outcome": "lost", "reason": "price"})
    assert _conv(user_id).outcome_reason == "price"

    client.post(f"/admin/conversation/{user_id}/outcome", data={"outcome": "won"})

    conv = _conv(user_id)
    assert conv.outcome == "won" and conv.outcome_reason == ""


def test_a_reason_is_ignored_for_a_win():
    """Причина отказа у выигранной сделки — бессмыслица, не сохраняем даже если пришла."""
    user_id = _seed()
    client = _auth_client()

    client.post(f"/admin/conversation/{user_id}/outcome",
                data={"outcome": "won", "reason": "competitor"})

    assert _conv(user_id).outcome_reason == ""


def test_the_reason_lands_in_the_audit_next_to_the_outcome():
    """В журнале должно читаться не только «слился», но и почему."""
    user_id = _seed()
    client = _auth_client()

    client.post(f"/admin/conversation/{user_id}/outcome",
                data={"outcome": "lost", "reason": "no_answer"})

    store = get_conversation_store()
    # У хранилища есть готовая проверка по журналу — ею же пользуется B3, чтобы не
    # записать продажу дважды.
    assert asyncio.run(store.audit_exists("outcome", "lost:no_answer"))


def test_without_the_flag_the_buttons_are_not_rendered():
    """Тумблер OFF — карточка выглядит как раньше, лишних кнопок нет."""
    user_id = _seed()
    client = _auth_client()

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "Почему не сложилось" not in page


def test_with_the_flag_the_buttons_appear():
    from app.core import flags
    user_id = _seed()
    asyncio.run(flags.set_flag("lost_reason_enabled", True))
    client = _auth_client()

    page = client.get(f"/admin/conversation/{user_id}").text

    assert "Почему не сложилось" in page
    assert "Обратился в другую компанию" in page
    asyncio.run(flags.set_flag("lost_reason_enabled", False))


def test_clicking_lost_again_keeps_the_chosen_reason():
    """Повторный клик «Слился» не должен стирать уже выбранную причину.

    Кнопка исхода и кнопки причин — разные элементы, и нажать «Слился» второй раз
    легко. Раньше это приходило как outcome=lost без причины и затирало её: менеджер
    наказан за лишнее нажатие (ревью 12.11.2026).
    """
    user_id = _seed()
    client = _auth_client()

    client.post(f"/admin/conversation/{user_id}/outcome",
                data={"outcome": "lost", "reason": "price"})
    client.post(f"/admin/conversation/{user_id}/outcome", data={"outcome": "lost"})

    conv = _conv(user_id)
    assert conv.outcome == "lost" and conv.outcome_reason == "price"
