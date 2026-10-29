"""Меню ⋮ в чате не должно схлопываться (находка прохода менеджера 30.10.2026).

`.chat-menu-body` — position:absolute внутри `.chat-head`, а шапка с 20.10 липкая
(position:sticky) и потому сама становится контейнером. `max-height: calc(100% - 66px)`
считался от высоты шапки (~56 px) → отрицательное значение → меню 22 px (только паддинги).
«Перехватить», «Вернуть боту», исходы и «Договор подписан» были в разметке, но человек их
не видел. Проверяем отрендеренную страницу, а не файл шаблона.
"""
import re

from fastapi.testclient import TestClient

import app.config
import app.main as main
from app.config import ManagerConfig


def _page(monkeypatch) -> str:
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True)], raising=False)
    for key in ("admin_new_look_enabled", "admin_chat_redesign_enabled"):
        monkeypatch.setattr(app.config.settings, key, True, raising=False)
    from app.core import flags
    flags.reset()
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": "admin", "password": "frunze"}).status_code in (200, 303)
    return client.get("/admin").text


def test_chat_menu_height_is_not_relative_to_the_sticky_header(monkeypatch):
    css = _page(monkeypatch)
    assert ".chat-palma .chat-head { position:sticky" in css, "предпосылка теста изменилась"
    rule = re.search(r"\.chat-menu-body \{[^}]*\}", css, flags=re.S)
    assert rule, "в странице нет правила меню чата"
    body = rule.group(0)
    assert "100% - 66px" not in body, "max-height считается от липкой шапки — меню схлопнется до 22 px"
    assert "100dvh" in body, "высота меню должна считаться от экрана"
