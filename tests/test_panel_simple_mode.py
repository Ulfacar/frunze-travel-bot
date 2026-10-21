"""Простой режим панели за тумблером `panel_simple_mode_enabled`.

Требование заказчика (через Алана, 21.10.2026): «просто, минималистично, главное снизить
порог входа». Сотрудники не прижились в Bitrix, потому что там «кнопки прям в лицо
тыкались». Замер по шаблонам в тот же день: в инбоксе 199 интерактивных элементов, из них
198 видны всегда, а рабочий путь менеджера — «увидел ждущего → открыл → ответил → исход
или задача» — задействует пять.

Опасность упрощения ровно одна и она зеркальна редизайну: прячешь кнопку — теряешь
функцию. Поэтому тест закрепляет не «стало красиво», а три вещи:

1. **Ничего не исчезло.** Спрятанное остаётся в разметке и доступно после раскрытия;
   обработчики и классы, на которых держатся htmx и скрипты, те же.
2. **Откат мгновенный.** OFF отдаёт прежний вид: кнопки снова в шапке, дубли на месте.
3. **Домашний экран.** Менеджер попадает на «Фокус», админ — на доску, а явная ссылка
   из уведомления сильнее домашнего экрана (иначе ломается вход по ссылке на диалог).
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store

TEMPLATES = Path(admin_router.__file__).parent / "templates"
FLAG = "panel_simple_mode_enabled"
# Кнопки разбора списка: в простом режиме они под раскрывашкой, но обязаны существовать.
BULK = ("selectVisibleInboxCards(", "clearInboxSelection(", "archiveSelectedInbox(",
        "archiveNoiseInbox(", "toggleNoise(")


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        # medina есть в BOT_SCOPE_BY_MANAGER — это обычный визовый менеджер, не админ.
        ManagerConfig(login="medina", name="Медина", password="visa-pass", admin=False),
    ], raising=False)


def _setup(monkeypatch, simple: bool, *, focus=True, workday=True):
    _clear()
    _managers(monkeypatch)
    for key, value in (("admin_new_look_enabled", True), ("admin_chat_redesign_enabled", True),
                       ("admin_focus_enabled", focus), ("admin_workday_enabled", workday),
                       ("service_cases_enabled", workday), (FLAG, simple)):
        monkeypatch.setattr(app.config.settings, key, value, raising=False)


def _client():
    return TestClient(main.app, base_url="https://testserver")


def _login(client, login="admin", password="frunze", **data):
    return client.post("/admin/login", data={"login": login, "password": password, **data},
                       follow_redirects=False)


def _page(monkeypatch, path, simple, login="admin", password="frunze", **kw):
    _setup(monkeypatch, simple, **kw)
    client = _client()
    assert _login(client, login, password).status_code in (200, 303)
    return client.get(path).text


# ---------------- инбокс: разбор списка под одной раскрывашкой ----------------
def test_inbox_bulk_actions_hide_behind_one_disclosure(monkeypatch):
    plain = _page(monkeypatch, "/admin/inbox", simple=False)
    simple = _page(monkeypatch, "/admin/inbox", simple=True)
    assert "inbox-tools" not in plain, "при выключенном тумблере вид обязан быть прежним"
    assert "Разобрать список" in simple and "inbox-tools" in simple


@pytest.mark.parametrize("handler", BULK)
def test_every_bulk_action_survives_in_markup(monkeypatch, handler):
    """Спрятать — не значит потерять: массовый архив рекламы чистит реальные диалоги."""
    simple = _page(monkeypatch, "/admin/inbox", simple=True)
    assert handler in simple, handler


def test_counters_and_heading_are_untouched(monkeypatch):
    """Число ждущих — ориентир менеджера, его прятать нельзя (находка ревью 01.10)."""
    simple = _page(monkeypatch, "/admin/inbox", simple=True)
    assert "Ждут ответа" in simple


def test_per_card_controls_are_hidden_until_the_list_is_being_sorted(monkeypatch):
    """Чекбокс и крестик на 60 карточках — 120 элементов, которые на телефоне видны всегда."""
    page = _page(monkeypatch, "/admin", simple=True)
    assert "[data-attention]:not(:has(.inbox-tools[open]))" in page
    # Классы на месте: на них завязаны htmx-обработчики и тест мобильной раскладки.
    for cls in ("card-select", "card-archive", "bulk-checkbox"):
        assert cls in page, cls


# ---------------- домашний экран ----------------
def test_manager_lands_on_focus_and_admin_on_the_board(monkeypatch):
    _setup(monkeypatch, simple=True)
    assert _login(_client(), "medina", "visa-pass").headers["location"] == "/admin/focus"
    assert _login(_client(), "admin", "frunze").headers["location"] == "/admin"


def test_without_the_flag_everyone_lands_where_they_did_before(monkeypatch):
    _setup(monkeypatch, simple=False)
    assert _login(_client(), "medina", "visa-pass").headers["location"] == "/admin"


def test_explicit_link_beats_the_home_screen(monkeypatch):
    """Менеджер тапнул ссылку на диалог из уведомления — обязан попасть в диалог."""
    _setup(monkeypatch, simple=True)
    target = "/admin?open=getvisa:996700000001"
    assert _login(_client(), "medina", "visa-pass", next=target).headers["location"] == target


def test_focus_off_means_the_old_home_screen(monkeypatch):
    """Экран за своим тумблером: выключен — домашним он не становится."""
    _setup(monkeypatch, simple=True, focus=False)
    assert _login(_client(), "medina", "visa-pass").headers["location"] == "/admin"


# ---------------- остальные экраны ----------------
def test_calendar_secondary_actions_move_under_more(monkeypatch):
    plain = _page(monkeypatch, "/admin/calendar", simple=False)
    simple = _page(monkeypatch, "/admin/calendar", simple=True)
    assert "task-more" not in plain
    assert "task-more" in simple
    # Главное действие остаётся снаружи.
    assert "Сделано" in simple


def test_workday_drops_the_duplicate_counter_row(monkeypatch):
    plain = _page(monkeypatch, "/admin/work", simple=False)
    simple = _page(monkeypatch, "/admin/work", simple=True)
    assert 'class="wk-stats"' in plain
    assert 'class="wk-stats"' not in simple
    # Те же числа остаются на вкладках — информация не потеряна.
    assert 'data-count="stuck"' in simple or 'role="tablist"' in simple


def test_focus_hides_the_hotkey_footnote_but_keeps_the_keys(monkeypatch):
    plain = _page(monkeypatch, "/admin/focus", simple=False)
    simple = _page(monkeypatch, "/admin/focus", simple=True)
    assert "следующий ·" in plain
    assert "следующий ·" not in simple
    assert "Ctrl" in simple, "подпись на кнопке отправки обязана остаться"


def test_templates_declare_the_flag_only_through_the_context(monkeypatch):
    """`simple_on` приходит из `_chrome`; забытый `{% if %}` в шаблоне молча ничего не прячет."""
    used = [p.name for p in TEMPLATES.glob("*.html") if "simple_on" in p.read_text("utf-8")]
    assert {"_attention.html", "calendar.html", "_work_list.html", "focus.html",
            "_conversation.html", "boards.html"} <= set(used), used


# ---------------- доступ Гриши (решение Алана 21.10) ----------------
# Две учётки: `grisha` видит ровно то же, что визовые менеджеры, `grisha-admin` — всё.
# Тест держит именно разделение: заказчик оценивает рабочее место сотрудника, а не
# админский экран, и при этом не теряет возможности остановить пилот с другой учётки.
def test_grisha_logs_in_as_a_visa_manager_not_an_admin():
    from app.core.manager_scope import bot_scope_for
    assert bot_scope_for({"login": "grisha", "name": "Гриша", "admin": False}) == {"getvisa", "getvisa_tg"}
    assert bot_scope_for({"login": "grisha", "name": "Гриша", "admin": False}) == \
           bot_scope_for({"login": "medina", "name": "Медина", "admin": False})


def test_the_separate_admin_account_keeps_full_rights():
    from app.core.manager_scope import bot_scope_for
    assert bot_scope_for({"login": "grisha-admin", "name": "Гриша (админ)", "admin": True}) is None


def test_manager_grisha_lands_on_focus_in_simple_mode(monkeypatch):
    _clear()
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="grisha", name="Гриша", password="visa-pass", admin=False),
    ], raising=False)
    for key, value in (("admin_new_look_enabled", True), ("admin_focus_enabled", True), (FLAG, True)):
        monkeypatch.setattr(app.config.settings, key, value, raising=False)
    assert _login(_client(), "grisha", "visa-pass").headers["location"] == "/admin/focus"


# ---------------- путь браузера, а не придуманный (находка ревью 21.10) ----------------
# Первая версия теста слала POST без `next` — так браузер не делает НИКОГДА: `login_form`
# кладёт в скрытое поле `_safe_next("")`, то есть «/admin», а `index` без сессии ведёт на
# `/admin/login?next=%2Fadmin`. Тест был зелёный, а домашний экран не работал. Поэтому
# здесь форма сначала ЗАПРАШИВАЕТСЯ, из неё берётся реальное значение поля, и только
# потом отправляется — ровно как в браузере.
def _next_from_form(client, query: str = "") -> str:
    html = client.get("/admin/login" + query).text
    found = re.search(r'name="next" value="([^"]*)"', html)
    assert found, "в форме входа нет скрытого поля next"
    return found.group(1)


def test_manager_reaches_focus_through_the_real_login_form(monkeypatch):
    _setup(monkeypatch, simple=True)
    client = _client()
    target = _next_from_form(client)
    assert target == "/admin", "форма изменилась — проверь, что сценарий всё ещё реальный"
    r = client.post("/admin/login", data={"login": "medina", "password": "visa-pass",
                                          "next": target}, follow_redirects=False)
    assert r.headers["location"] == "/admin/focus"


def test_link_from_a_notification_still_wins_through_the_form(monkeypatch):
    _setup(monkeypatch, simple=True)
    client = _client()
    deep = "/admin?open=getvisa:996700000001"
    target = _next_from_form(client, "?next=" + deep)
    r = client.post("/admin/login", data={"login": "medina", "password": "visa-pass",
                                          "next": target}, follow_redirects=False)
    assert r.headers["location"] == deep


def test_admin_through_the_form_still_lands_on_the_board(monkeypatch):
    _setup(monkeypatch, simple=True)
    client = _client()
    r = client.post("/admin/login", data={"login": "admin", "password": "frunze",
                                          "next": _next_from_form(client)},
                    follow_redirects=False)
    assert r.headers["location"] == "/admin"


def test_open_sorting_panel_is_not_wiped_by_the_ten_second_poll(monkeypatch):
    """Опрос перерисовывал блок и схлопывал «Разобрать список» — массовый архив был
    практически недостижим: пропуск срабатывал только после отметки чекбокса."""
    page = _page(monkeypatch, "/admin/inbox", simple=True)
    # В условии триггера есть своя квадратная скобка (`.inbox-tools[open]`), поэтому
    # читаем до конца атрибута, а не до первой закрывающей.
    trigger = re.search(r'hx-trigger="(every 10s .*?)"', page)
    assert trigger, "у инбокса пропал триггер опроса"
    assert "inbox-tools[open]" in trigger.group(1), trigger.group(1)
    # И обратная сторона контракта: при выключенном флаге сторожа в разметке нет.
    assert "inbox-tools[open]" not in _page(monkeypatch, "/admin/inbox", simple=False)


# ---------------- календарь не показывает чужих клиентов (находка аудита 21.10) ----------------
# Задачи фильтруются по владельцу, а карточка берёт имя и телефон из диалога. Пока владелец
# задачи и доступ к диалогу совпадают, это незаметно. Перевод Гриши из админов в визовый
# скоуп их развёл: в его календаре остались 25 задач турового клиента — имя и номер видны,
# а «Переписка →» отдаёт 404. Проверяем сам фильтр, а не страницу: он и есть предохранитель.
@pytest.mark.asyncio
async def test_calendar_card_data_is_limited_to_the_managers_scope(monkeypatch):
    _clear()
    store = panel_store._memory_store
    await store.add_message("getvisa:996700000021", "client", "виза", bot_id="getvisa")
    await store.add_message("frunze_tours_sezim:996700000022", "client", "тур",
                            bot_id="frunze_tours_sezim")
    monkeypatch.setattr(panel_store, "get_conversation_store", lambda: store, raising=False)
    monkeypatch.setattr(admin_router, "get_conversation_store", lambda: store, raising=False)
    ids = {"getvisa:996700000021", "frunze_tours_sezim:996700000022"}

    visa_manager = {"login": "medina", "name": "Медина", "admin": False}
    seen = await admin_router._conv_map(ids, visa_manager)
    assert set(seen) == {"getvisa:996700000021"}, "визовому менеджеру видно туровых клиентов"

    full_admin = {"login": "admin", "name": "Админ", "admin": True}
    assert set(await admin_router._conv_map(ids, full_admin)) == ids, "админ потерял видимость"
