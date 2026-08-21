"""ГЕЙТ: ссылка на диалог обязана открываться человеком с телефона.

Написан ДО реализации и исполнителем НЕ редактируется.

## Зачем (замер прода 21.08.2026)

Владелец, проверяя уведомления сам: «есть ссылки которые от frunze, они кривые, я вот
когда сам переходил — там страница поломанная».

Проверено живьём. Визовый менеджер получает в каждой готовой заявке три ссылки:

    💬 написать:      https://wa.me/996509051280                      → 200
    🗂 карточка:      https://getvisakg.bitrix24.kz/crm/lead/details/186447/ → 200
    👉 открыть диалог: https://frunzetravel.kg/admin/conversation/getvisa:996509051280 → 401

Последняя сломана дважды. Без сессии отдаётся не форма входа, а голый JSON
`{"detail":"login required"}` — для человека это и есть «поломанная страница».
А после входа открылся бы HTMX-партиал: кусок разметки без вёрстки и навигации,
который панель подгружает внутрь себя. Прямое открытие в него не задумывалось.

Та же ссылка стоит в утреннем брифе, в календаре и — с 21.08 — в досье карточки
Битрикса, то есть скоро попала бы в каждую из 326 туровых карточек.

## Решение

Дип-линк `/admin?open=<user_id>` в панели УЖЕ есть (сделан для «Горячего листа»)
и ведёт себя правильно: без сессии — 303 на форму входа. Значит чинить надо не
страницу, а адрес, который мы кладём в уведомления, и возврат после логина —
иначе менеджер войдёт и окажется на главной без нужного диалога.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.calendar_brief import _client_link

BASE = "https://frunzetravel.kg"
USER = "getvisa:996509051280"


# ---------------- сама ссылка --------------------------------------------------------
def test_client_link_is_a_deep_link_not_a_partial():
    link = _client_link(USER, BASE)
    assert "/admin/conversation/" not in link, "партиал не предназначен для открытия человеком"
    assert link.startswith(f"{BASE}/admin?open=")


def test_client_link_encodes_the_colon():
    """`bot_id:phone` едет в query — двоеточие обязано быть закодировано."""
    link = _client_link(USER, BASE)
    assert "%3A" in link and "getvisa%3A996509051280" in link


def test_client_link_without_base_stays_relative():
    """Ложноположительный: прежнее поведение при пустом базовом адресе не меняем."""
    assert _client_link(USER, "").startswith("/admin?open=")


# ---------------- поведение панели ---------------------------------------------------
@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, follow_redirects=False)


def test_deep_link_without_session_redirects_to_login(client):
    response = client.get(f"/admin?open={USER}")
    assert response.status_code == 303, "человеку показываем форму входа, а не JSON с ошибкой"
    assert "/admin/login" in response.headers.get("location", "")


def test_login_redirect_carries_next(client):
    """Войдя, менеджер обязан попасть на запрошенный диалог, а не на главную."""
    response = client.get(f"/admin?open={USER}")
    location = response.headers.get("location", "")
    assert "next=" in location
    assert "open" in location


def test_login_form_keeps_next(client):
    response = client.get("/admin/login", params={"next": f"/admin?open={USER}"})
    assert response.status_code == 200
    assert "next" in response.text


@pytest.mark.parametrize("evil", [
    "https://evil.example/steal",
    "//evil.example/steal",
    "http://frunzetravel.kg.evil/x",
    "javascript:alert(1)",
])
def test_next_outside_panel_is_ignored(client, evil):
    """Открытый редирект — дыра: `next` принимаем только внутрь своей панели."""
    from app.admin.router import _safe_next

    assert _safe_next(evil) == "/admin"


def test_safe_next_keeps_panel_paths():
    from app.admin.router import _safe_next

    assert _safe_next(f"/admin?open={USER}") == f"/admin?open={USER}"
    assert _safe_next("/admin/calendar") == "/admin/calendar"


# ---------------- ложноположительные: партиал не сломан ------------------------------
def test_partial_still_requires_auth(client):
    """HTMX-партиал остаётся закрытым и по-прежнему отвечает 401, а не редиректом.

    Панель ходит в него ajax-ом: редирект вместо 401 подсунул бы в блок диалога
    HTML формы логина вместо переписки.
    """
    response = client.get(f"/admin/conversation/{USER}")
    assert response.status_code == 401
