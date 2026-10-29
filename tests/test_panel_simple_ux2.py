"""Поток ux, 3-й заход (30.10.2026, на интеграции): замечания ревью потока bitrix и PM.

1. Админ в простом режиме на диалоге, который закреплён за менеджером, но не перехвачен,
   не видел ни «Взять себе», ни «Перехватить» (ревью bitrix, NEEDS_HUMAN_DECISION низкое).
2. В «Напомнить» нельзя было отметить «Важно».
3. Поиск в «Диалогах» не срабатывал на вставленный номер: триггер `keyup` не приходит
   при вставке мышью или долгим нажатием на телефоне (приёмка PM).
"""
import re

from test_panel_simple_manager_day import VISA, _client, _seed, _setup


def _strip(page: str) -> str:
    return re.search(r'<div class="chat-who.*?</details>', page, flags=re.S).group(0)


def test_admin_can_take_a_client_pinned_to_a_manager(monkeypatch):
    _setup(monkeypatch); _seed(assigned_to="medina", intercepted=False)
    strip = _strip(_client("admin", "frunze").get(f"/admin/conversation/{VISA}").text)
    assert "Клиента ведёт Медина" in strip
    assert f'hx-post="/admin/conversation/{VISA}/takeover"' in strip and "Взять себе" in strip


def test_manager_still_has_no_takeover_on_a_colleagues_client(monkeypatch):
    _setup(monkeypatch); _seed(assigned_to="eliza", intercepted=False)
    strip = _strip(_client().get(f"/admin/conversation/{VISA}").text)
    assert "/takeover" not in strip and "/release" not in strip


def test_remind_can_be_marked_important_and_default_stays_server_side(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    form = re.search(r'<form class="chat-remind-form".*?</form>', page, flags=re.S).group(0)
    assert re.findall(r'name="priority"[^>]*', form) == ['name="priority" value="high"'], \
        "одна галочка «Важно»; без неё поле не уходит и сервер ставит normal"
    assert 'type="checkbox" name="priority" value="high"' in form and "Важно" in form


def test_search_fires_on_paste_not_only_on_keyup(monkeypatch):
    for simple in (True, False):
        _setup(monkeypatch, simple=simple)
        page = _client().get("/admin").text
        tag = re.search(r'<input type="search" name="q"[^>]*>', page, flags=re.S).group(0)
        assert 'hx-trigger="input changed delay:300ms, search"' in tag, tag
