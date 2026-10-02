"""ГЕЙТ: инбокс отдаёт страницу, а не всю базу.

Написан ДО реализации и исполнителем НЕ редактируется.

Зачем. Замер на проде 02.10.2026: `/admin/inbox` отдаёт **1.95 МБ HTML и 1012 карточек**
одним ответом — лимита в коде нет вообще (`cards = _waiting_sorted(models)`). При этом
`_attention.html` перезагружает сам себя **каждые 10 секунд**, то есть у менеджера,
открывшего панель на телефоне, уходит порядка 12 МБ в минуту. Диалогов в базе 3757,
живых за неделю — 213.

Четыре ловушки, которые делают эту правку опасной, и все четыре закреплены ниже:

1. **Счётчик обязан считать всю базу, а список — показывать страницу.** Обратную ошибку
   («бейдж одно, список другое») независимое ревью уже находило 01.10.
2. **`noise_count` — по всей базе.** Кнопка «Очистить рекламу (N)» чистит НА СЕРВЕРЕ
   (`/admin/conversations/archive-noise`), а число для подтверждения берёт из
   `data-noise-count`. Посчитай его по странице — и диалог спросит «заархивировать 12?»,
   а снесёт все двести.
3. **Поиск не имеет права терять совпадения за лимитом.** Инбокс показывает свежие, но
   найти старый лид по номеру нужно всегда — иначе клиент, написавший месяц назад,
   становится ненаходимым.
4. **«Показать все» должно переживать автообновление.** Иначе менеджер разворачивает
   список, и через десять секунд он сворачивается сам.
"""
import asyncio

from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

LIMIT_FLAG = "admin_inbox_limit_enabled"
MANY = 40          # заметно больше лимита, выставленного в тестах
TEST_LIMIT = 10


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ], raising=False)


def _limit(monkeypatch, value=TEST_LIMIT):
    monkeypatch.setattr(app.config.settings, "admin_inbox_page_size", value, raising=False)


def _seed_waiting(count=MANY):
    """`count` диалогов, где последним писал КЛИЕНТ — то есть все ждут ответа."""
    store = get_conversation_store()

    async def _s():
        for i in range(count):
            user = f"getvisa:99670000{i:04d}"
            await store.add_message(user, "client", f"нужна виза номер {i}",
                                    channel="whatsapp", bot_id="getvisa",
                                    phone=f"99670000{i:04d}")
            await store.update_meta(user, funnel="visa")
    asyncio.run(_s())


def _login():
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "admin", "password": "frunze"}).status_code == 200
    return client


def _cards(body: str) -> int:
    return body.count('class="card"')


def _on(monkeypatch):
    monkeypatch.setattr(app.config.settings, LIMIT_FLAG, True, raising=False)


# --- A. Собственно лимит ------------------------------------------------------

def test_flag_off_keeps_the_whole_list(monkeypatch):
    """OFF — поведение дословно прежнее, иначе это не откат."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _seed_waiting()
    monkeypatch.setattr(app.config.settings, LIMIT_FLAG, False, raising=False)
    assert _cards(_login().get("/admin/inbox").text) == MANY


def test_flag_on_sends_only_a_page(monkeypatch):
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    assert _cards(_login().get("/admin/inbox").text) == TEST_LIMIT


def test_page_keeps_those_who_wait_longest(monkeypatch):
    """Обрезаем хвост, а не голову: наверху те, кто ждёт дольше всех."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    full = _login()
    monkeypatch.setattr(app.config.settings, LIMIT_FLAG, False, raising=False)
    everyone = [l for l in full.get("/admin/inbox").text.splitlines() if "data-user-id" in l]
    _on(monkeypatch)
    page = [l for l in full.get("/admin/inbox").text.splitlines() if "data-user-id" in l]
    assert page == everyone[:TEST_LIMIT], "страница не совпала с началом полного списка"


# --- B. Счётчики считают базу, а не страницу ---------------------------------

def test_header_counts_everyone_not_just_the_page(monkeypatch):
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    body = _login().get("/admin/inbox").text
    assert f"Ждут ответа — {MANY}" in body, "заголовок показывает размер страницы вместо базы"


def test_page_says_it_is_a_page(monkeypatch):
    """Молча обрезанный список — это вранье: менеджер не узнает, что видит часть."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    body = _login().get("/admin/inbox").text
    assert str(TEST_LIMIT) in body and "Показать все" in body


def test_noise_counter_is_computed_over_the_whole_base(monkeypatch):
    """Иначе подтверждение массового архива соврёт: спросит про страницу, снесёт базу."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch)
    store = get_conversation_store()

    async def _s():
        for i in range(MANY):
            user = f"getvisa:99670001{i:04d}"
            # Шум в терминах панели (`leadstate.is_noise`) — первая реплика клиента со
            # ссылкой на рекламный пост. Правка гейта: прежняя фикстура слала текст без
            # ссылки, и шумом он не считался — ломалось моё утверждение, не требование.
            await store.add_message(user, "client",
                                    "https://instagram.com/p/Cxyz Можно узнать подробнее?",
                                    channel="whatsapp", bot_id="getvisa",
                                    phone=f"99670001{i:04d}")
            await store.update_meta(user, funnel="visa", source="ad")
    asyncio.run(_s())

    body = _login().get("/admin/inbox").text
    noise_total = sum(1 for _ in range(MANY))      # все засеянные — шум
    assert f'data-noise-count="{noise_total}"' in body, (
        "счётчик рекламы посчитан по странице — кнопка массового архива соврёт")


# --- C. Поиск не теряет никого ------------------------------------------------

def test_search_finds_a_lead_beyond_the_page(monkeypatch):
    """Лид, не попавший на страницу инбокса, обязан находиться по номеру."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    far_phone = f"99670000{MANY - 1:04d}"
    client = _login()
    assert far_phone not in client.get("/admin/inbox").text, "лид и так на странице, тест ни о чём"
    found = client.get("/admin/search", params={"q": far_phone}).text
    assert far_phone in found, "поиск не нашёл лид за пределами страницы"


# --- D. «Показать все» переживает автообновление ------------------------------

def test_show_all_returns_everyone(monkeypatch):
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    assert _cards(_login().get("/admin/inbox", params={"all": "1"}).text) == MANY


def test_expanded_list_refreshes_itself_expanded(monkeypatch):
    """Автообновление каждые 10 с не имеет права свернуть список обратно."""
    _clear(); _managers(monkeypatch); _limit(monkeypatch); _on(monkeypatch); _seed_waiting()
    body = _login().get("/admin/inbox", params={"all": "1"}).text
    assert 'hx-get="/admin/inbox?all=1"' in body, (
        "развёрнутый список перезагружает себя без all=1 — через 10 секунд свернётся")


# --- E. Тумблер ---------------------------------------------------------------

def test_flag_defaults_to_off():
    assert app.config.settings.admin_inbox_limit_enabled is False


def test_flag_is_switchable_without_deploy():
    assert LIMIT_FLAG in admin_router.FEATURE_FLAGS
