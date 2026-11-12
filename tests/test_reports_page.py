# -*- coding: utf-8 -*-
"""Страница отчётов в панели.

Расчёт проверен отдельно (`test_reports.py`). Здесь — то, что видно менеджеру:
закрыта ли страница тумблером, не отдаёт ли она чужие направления и, главное,
печатает ли она ПРИЧИНУ вместо нуля. Последнее и есть смысл страницы: ноль в
колонке «клиенты по странам» и «поле никто не заполняет» выглядят одинаково, а
значат противоположное.
"""
import asyncio

import pytest

from app.integrations.panel.store import get_conversation_store

from tests.test_panel import _auth_client, _clear_memory


@pytest.fixture(autouse=True)
def _clean():
    from app.core import flags
    flags.reset()
    yield
    flags.reset()


def _seed(*, with_country: str = "") -> None:
    from app.core import flags
    _clear_memory()
    asyncio.run(flags.set_flag("panel_reports_enabled", True))
    store = get_conversation_store()
    for i, funnel in enumerate(("visa", "visa", "tours")):
        bot = "getvisa" if funnel == "visa" else "frunze_tours"
        uid = f"{bot}:99670077700{i}"
        asyncio.run(store.add_message(uid, "client", "здравствуйте", channel="whatsapp"))
        asyncio.run(store.update_meta(uid, funnel=funnel, stage="greeting"))
    if with_country:
        asyncio.run(store.set_visa_fields("getvisa:996700777000", country=with_country))


def test_the_flag_hides_the_page():
    """Дефолт OFF: выкат кода ничего не открывает."""
    from app.core import flags
    _seed()
    asyncio.run(flags.set_flag("panel_reports_enabled", False))
    client = _auth_client()

    assert client.get("/admin/reports").status_code == 404


def test_the_page_opens_with_the_flag_on():
    _seed()
    client = _auth_client()

    resp = client.get("/admin/reports")

    assert resp.status_code == 200
    assert "Новые лиды" in resp.text


def test_an_empty_country_column_explains_itself():
    """Главное требование: причина вместо нуля.

    Без этой подписи руководитель увидит пустую колонку и решит, что клиентов нет,
    хотя на деле поле просто не заполняют.
    """
    _seed()
    client = _auth_client()

    page = client.get("/admin/reports?direction=visa").text

    assert "Страна не заполнена ни у одной карточки" in page


def test_a_filled_country_is_shown_instead_of_the_excuse():
    _seed(with_country="Германия")
    client = _auth_client()

    page = client.get("/admin/reports?direction=visa").text

    assert "Германия" in page
    assert "Страна не заполнена ни у одной карточки" not in page


def test_metrics_without_data_say_why_on_the_page():
    _seed()
    client = _auth_client()

    page = client.get("/admin/reports").text

    assert "Пока не считается" in page
    assert "cases_write_enabled" in page


def test_the_direction_switch_changes_the_numbers():
    """Визы и туры считаются отдельно: иначе менеджер видит чужие цифры как свои."""
    _seed()
    client = _auth_client()

    visa = client.get("/admin/reports?direction=visa").text
    tours = client.get("/admin/reports?direction=tours").text

    assert visa != tours


def test_an_unknown_direction_falls_back_instead_of_failing():
    """Кривой параметр в адресе не должен ронять страницу."""
    _seed()
    client = _auth_client()

    assert client.get("/admin/reports?direction=нарния").status_code == 200


def test_the_page_opens_without_the_domain_database():
    """Задачи живут в доменной базе; её может не быть, а отчёт обязан открыться."""
    _seed()
    client = _auth_client()

    resp = client.get("/admin/reports")

    assert resp.status_code == 200
    assert "Задачи" in resp.text
