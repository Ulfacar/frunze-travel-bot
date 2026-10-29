"""Простой режим, шаг 2 (30.10.2026): день менеджера «как в WhatsApp».

Проход менеджера кликами (Медина — визы, Айсина — туры) на стенде 30.10 нашёл:

* меню ⋮ в чате схлопывалось до 22 px — «Перехватить», «Вернуть боту», исход и договор
  были в разметке, но человек их не видел (контейнер — липкая шапка, `100% − 66px` < 0);
* «кто сейчас отвечает клиенту» — только цветная точка; перехват и возврат — в том же меню;
* напоминание на завтра — 6 действий через «Досье → Новая задача», дата по умолчанию сегодня;
* файл — английское «Choose File / No file chosen» и форма на треть экрана телефона;
* жаргон: «Фокус», «Досье · ИИ: не определён», «ваш ход / ждут / всего», «Слился»,
  подсказки клавиш на кнопках, «Предложить ответ»;
* WhatsApp без настроенного канала: в чате галочка «отправлено», хотя Wappi ничего не слал.

Тест держит три вещи: менеджер в простом режиме видит новый вид; админ и выключенный
тумблер — прежний; ни одно действие не потеряно (те же эндпоинты, те же обработчики).
Проверки по ОТРЕНДЕРЕННОЙ странице, а не по файлу шаблона.
"""
import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

FLAG = "panel_simple_mode_enabled"
TEMPLATES = Path(admin_router.__file__).parent / "templates"
VISA = "getvisa:996700000501"


def _setup(monkeypatch, simple=True):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login="medina", name="Медина", password="visa-pass", admin=False),
    ], raising=False)
    for key, value in (("admin_new_look_enabled", True), ("admin_chat_redesign_enabled", True),
                       ("admin_focus_enabled", True), ("admin_workday_enabled", True),
                       ("service_cases_enabled", True), ("panel_send_media_enabled", True),
                       (FLAG, simple)):
        monkeypatch.setattr(app.config.settings, key, value, raising=False)


def _client(login="medina", password="visa-pass"):
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": login, "password": password},
                       follow_redirects=False).status_code in (200, 303)
    return client


def _seed(user=VISA, text="Когда можно подойти?", minutes_ago=40, *, bot_id="getvisa",
          channel="whatsapp", **meta):
    store = get_conversation_store()

    async def _s():
        await store.add_message(user, "client", text, channel=channel, bot_id=bot_id,
                                phone=user.split(":")[-1])
        conv = panel_store._memory_store._conv[user]
        conv.last_message_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        for m in conv.messages:
            m.created_at = conv.last_message_at
        await store.update_meta(user, funnel="visa", qualification={"name": "Эльмира"}, **meta)
    asyncio.run(_s())


def _main_nav(page: str) -> str:
    found = re.search(r'<nav class="main-nav".*?</nav>', page, flags=re.S)
    assert found, "нет основной навигации"
    return found.group(0)


def _visible_nav(nav: str) -> str:
    """Навигация без раскрывашки «Ещё»: то, что видно без клика."""
    return re.sub(r'<details class="more-nav">.*?</details>', "", nav, flags=re.S)


# ---------------- меню разделов ----------------
def test_manager_nav_speaks_plain_words(monkeypatch):
    _setup(monkeypatch)
    nav = _main_nav(_client().get("/admin/calendar").text)
    visible = _visible_nav(nav)
    for word in ("Главная", "Диалоги", "Мои дела", "Договоры"):
        assert word in visible, word
    for jargon in ("Фокус", "Рабочий день", "Покупатели"):
        assert jargon not in visible, jargon
    # Ничего не пропало: редкое — под «Ещё».
    assert "/admin/buyers" in nav and "/admin/morning" in nav
    # Админские разделы менеджеру не показываем, как и раньше.
    assert "/admin/system" not in nav and "/admin/audit" not in nav


def test_admin_and_flag_off_keep_the_old_nav(monkeypatch):
    _setup(monkeypatch)
    admin_nav = _visible_nav(_main_nav(_client("admin", "frunze").get("/admin/calendar").text))
    assert "Фокус" in admin_nav and "Рабочий день" in admin_nav and "Покупатели" in admin_nav
    _setup(monkeypatch, simple=False)
    off_nav = _visible_nav(_main_nav(_client().get("/admin/calendar").text))
    assert "Фокус" in off_nav and "Главная" not in off_nav


# ---------------- главная (бывший «Фокус») ----------------
def test_home_has_no_hotkey_badges_but_keeps_the_keys(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get("/admin/focus").text
    row = re.search(r'<div class="act-row">.*?</form>', page, flags=re.S).group(0)
    assert "<kbd>" not in row, "подсказки клавиш на кнопках — только в title"
    assert 'title="Ctrl+Enter"' in row
    for label in ("Отправить", "Подсказать ответ", "Взять себе", "Следующий клиент"):
        assert label in row, label
    # Клавиши работают как раньше: обработчик и кнопка архива с тем же id на месте.
    assert "'t': function" in page and 'id="act-archive"' in page
    assert "Кому ответить сейчас" in page and "Дольше всех ждёт ответа" in page
    assert "ваш ход" not in page


def test_home_without_the_flag_is_unchanged(monkeypatch):
    _setup(monkeypatch, simple=False); _seed()
    page = _client().get("/admin/focus").text
    assert "Позже <kbd>J</kbd>" in page and "ваш ход" in page
    assert "Мои дела на сегодня" not in page


def _task(tid, day, *, user=VISA, comment="", hhmm=None, status="planned"):
    at = None
    if hhmm:
        h, m = map(int, hhmm.split(":"))
        at = datetime(day.year, day.month, day.day, h, m, tzinfo=timezone.utc) - timedelta(hours=6)
    return SimpleNamespace(id=tid, scheduled_at=at, scheduled_date=day, user_id=user,
                           status=status, ai_summary="", kind="call", priority="normal",
                           comment=comment, direction="visa", manager_id="medina")


def test_home_lists_my_tasks_for_today(monkeypatch):
    """Второй вопрос дня — «что у меня сегодня» — на том же экране, из того же источника,
    что календарь (`_fetch_calendar_tasks`: менеджер видит только свои задачи)."""
    _setup(monkeypatch); _seed()
    today = admin_router._bishkek_today()
    rows = [_task(1, today, comment="Перезвонить про документы", hhmm="11:00"),
            _task(2, today - timedelta(days=2), comment="Просроченный звонок"),
            _task(3, today + timedelta(days=1), comment="Завтрашнее дело")]
    fetch = AsyncMock(return_value=rows)
    monkeypatch.setattr(admin_router, "_fetch_calendar_tasks", fetch)
    page = _client().get("/admin/focus").text
    block = page[page.index("Мои дела на сегодня"):]
    assert "Перезвонить про документы" in block and "11:00" in block
    assert "Просроченный звонок" in block and "просрочено" in block
    assert "Завтрашнее дело" not in block, "завтрашнее — не «сегодня»"
    # Просроченное — первым.
    assert block.index("Просроченный звонок") < block.index("Перезвонить про документы")
    assert fetch.await_args.args[0]["login"] == "medina"


# ---------------- чат ----------------
def test_chat_says_who_answers_and_puts_takeover_in_view(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    strip = re.search(r'<div class="chat-who.*?</details>', page, flags=re.S).group(0)
    assert "Отвечает бот" in strip
    assert f'hx-post="/admin/conversation/{VISA}/takeover"' in strip and "Взять себе" in strip
    menu = re.search(r'<details class="chat-menu".*?</details>', page, flags=re.S).group(0)
    assert "/takeover" not in menu and "/release" not in menu, "одно действие — одно место"
    # Исход и договор — по-прежнему в меню, понятными словами.
    for label in ("Продажа состоялась", "Пришёл в офис", "Клиент отказался"):
        assert label in menu, label
    assert "Слился" not in page


def test_chat_strip_offers_release_when_i_answer(monkeypatch):
    _setup(monkeypatch); _seed(intercepted=True, assigned_to="medina")
    page = _client().get(f"/admin/conversation/{VISA}").text
    strip = re.search(r'<div class="chat-who.*?</details>', page, flags=re.S).group(0)
    assert "Отвечаете вы" in strip and f"/conversation/{VISA}/release" in strip


def test_chat_remind_defaults_to_tomorrow_and_uses_the_same_endpoint(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    form = re.search(r'<form class="chat-remind-form".*?</form>', page, flags=re.S).group(0)
    assert f'hx-post="/admin/conversation/{VISA}/task/create"' in form
    tomorrow = (admin_router._bishkek_today() + timedelta(days=1)).isoformat()
    assert f'value="{tomorrow}"' in form
    # Форма создания больше не дублируется в «О клиенте».
    assert page.count("/task/create") == 1
    # Открытая форма не сбрасывается опросом раз в 4 секунды.
    assert "#chat .chat-remind[open]" in page


def test_chat_file_is_a_paperclip_and_the_dossier_has_no_jargon(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    assert f'for="chat-upload-{VISA}"' in page and f'id="chat-upload-{VISA}"' in page
    assert f'hx-post="/admin/conversation/{VISA}/send-file"' in page
    assert "chat-file is-simple" in page and "chatFilePicked(this)" in page
    # Выбранный файл не теряется при опросе карточки.
    assert "#chat .chat-file.has-file" in page
    assert "О клиенте" in page and "Досье" not in page and "ИИ: не определён" not in page
    assert "<dt>Имя</dt>" in page
    assert "Подсказать ответ" in page and "Предложить ответ" not in page


def test_chat_without_the_flag_is_the_old_chat(monkeypatch):
    _setup(monkeypatch, simple=False); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    assert "chat-who" not in page and "Досье" in page
    assert "Перехватить — бот замолчит" in page and "Слился" in page
    assert "chat-file is-simple" not in page and "Отправка перехватывает диалог" in page


def test_chat_menu_is_not_clipped_by_the_sticky_header():
    """`max-height: calc(100% - 66px)` считался от липкой шапки (≈56 px) — меню было 22 px."""
    css = (TEMPLATES / "boards.html").read_text("utf-8")
    rule = re.search(r"\.chat-menu-body \{[^}]*\}", css, flags=re.S).group(0)
    assert "100% - 66px" not in rule and "100dvh" in rule


# ---------------- диалоги ----------------
def test_inbox_card_says_it_plainly_and_once(monkeypatch):
    _setup(monkeypatch); _seed(minutes_ago=240, stage="manager")
    page = _client().get("/admin/inbox").text
    assert "ждёт 4 ч" in page
    assert 'class="time"' not in page, "время ожидания показано дважды"
    assert "отвечать вам" in page and "ваш ход" not in page
    _setup(monkeypatch, simple=False); _seed(minutes_ago=240, stage="manager")
    assert 'class="time"' in _client().get("/admin/inbox").text


def test_visa_manager_sees_only_her_own_board_tab(monkeypatch):
    _setup(monkeypatch)
    page = _client().get("/admin").text
    tabs = re.search(r'<nav class="tabs">.*?</nav>', page, flags=re.S).group(0)
    assert 'data-funnel="visa"' in tabs and 'data-funnel="tours"' not in tabs
    assert "Входящие" in tabs and "Инбокс" not in tabs
    admin_tabs = re.search(r'<nav class="tabs">.*?</nav>', _client("admin", "frunze").get("/admin").text,
                           flags=re.S).group(0)
    assert 'data-funnel="tours"' in admin_tabs


def test_phone_is_readable_but_data_is_untouched(monkeypatch):
    _setup(monkeypatch); _seed(minutes_ago=240)
    client = _client()
    inbox = client.get("/admin/inbox").text
    assert "+996 700 00 05 01" in inbox and "Фильтры и архив" in inbox
    chat = client.get(f"/admin/conversation/{VISA}").text
    assert "+996 700 00 05 01" in chat
    assert 'data-phone="996700000501"' in chat, "копируется исходный номер"
    assert get_conversation_store() and asyncio.run(get_conversation_store().get(VISA)).phone == "996700000501"
    _setup(monkeypatch, simple=False); _seed(minutes_ago=240)
    assert "+996 700 00 05 01" not in _client().get("/admin/inbox").text


def test_quick_replies_wrap_on_wide_card_and_hint_scroll_on_phone():
    css = (TEMPLATES / "boards.html").read_text("utf-8")
    assert re.search(r"@container \(min-width: 421px\) \{ \.chat-quick-replies\.is-simple \{ flex-wrap:wrap", css)
    assert "mask-image:linear-gradient" in css


# ---------------- честный статус отправки ----------------
def test_whatsapp_without_channel_is_failed_not_sent(monkeypatch):
    """Wappi без токена возвращает "" и ничего не шлёт — галочка «отправлено» была враньём."""
    _setup(monkeypatch); _seed()
    monkeypatch.setattr(app.config.settings, "wappi_token", "", raising=False)
    monkeypatch.setattr(admin_router, "_ownership_guard", AsyncMock(return_value=(True, "")))
    r = _client().post(f"/admin/conversation/{VISA}/send", data={"text": "Добрый день"})
    assert r.headers["X-Action-Outcome"] == "failed"
    conv = asyncio.run(get_conversation_store().get(VISA))
    assert conv.messages[-1].status == "failed"


def test_configured_channel_with_empty_id_stays_sent(monkeypatch):
    """Обратная сторона: настроенный канал без id ответа — не «сбой», иначе повтор даст дубль."""
    _setup(monkeypatch); _seed()
    monkeypatch.setattr(app.config.settings, "wappi_token", "synthetic-token", raising=False)
    monkeypatch.setattr(app.config.settings, "wappi_profile_id", "synthetic-profile", raising=False)
    monkeypatch.setattr(admin_router, "_ownership_guard", AsyncMock(return_value=(True, "")))
    monkeypatch.setattr(admin_router.outbound, "send_to_client", AsyncMock(return_value=""))
    r = _client().post(f"/admin/conversation/{VISA}/send", data={"text": "Добрый день"})
    assert r.headers["X-Action-Outcome"] == "sent"


# ---------------- «Мои дела»: простой список (30.10, шаг 2) ----------------
def _calendar_rows():
    today = admin_router._bishkek_today()
    return [_task(11, today, comment="Сегодняшнее дело", hhmm="15:00"),
            _task(12, today - timedelta(days=2), comment="Просроченное дело"),
            _task(13, today + timedelta(days=1), comment="Завтрашнее дело", hhmm="10:30"),
            _task(14, today + timedelta(days=3), comment="Через три дня")]


def test_my_tasks_default_to_a_simple_list_for_a_manager(monkeypatch):
    _setup(monkeypatch); _seed()
    fetch = AsyncMock(return_value=_calendar_rows())
    monkeypatch.setattr(admin_router, "_fetch_calendar_tasks", fetch)
    page = _client().get("/admin/calendar").text
    assert "<h1>Мои дела</h1>" in page
    over, today, tomorrow = (page.index(f"<h2>{h}</h2>") for h in ("Просрочено", "Сегодня", "Завтра"))
    assert over < page.index("Просроченное дело") < today < page.index("Сегодняшнее дело") \
        < tomorrow < page.index("Завтрашнее дело")
    assert "Через три дня" not in page, "в списке только просрочено/сегодня/завтра"
    # Те же эндпоинты: «Сделано» — complete, «Перенести на завтра» — snooze mode=tomorrow.
    assert "/admin/calendar/task/11/complete" in page and "/admin/calendar/task/11/snooze" in page
    assert 'name="mode" value="tomorrow"' in page and "Перенести на завтра" in page
    # Неделя — по кнопке; права те же — выборка по менеджеру.
    assert 'href="/admin/calendar?view=week' in page
    assert fetch.await_args.args[0]["login"] == "medina"


def test_my_tasks_list_keeps_the_list_after_an_action(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(admin_router, "_apply_calendar_action", AsyncMock())
    r = _client().post("/admin/calendar/task/11/snooze", data={"mode": "tomorrow", "view": "list"},
                       follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin/calendar?view=list"


def test_admin_and_flag_off_keep_the_day_calendar(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(admin_router, "_fetch_calendar_tasks", AsyncMock(return_value=[]))
    admin_page = _client("admin", "frunze").get("/admin/calendar").text
    assert "<h1>Мои дела</h1>" not in admin_page and ">День</a>" in admin_page
    _setup(monkeypatch, simple=False)
    monkeypatch.setattr(admin_router, "_fetch_calendar_tasks", AsyncMock(return_value=[]))
    off_page = _client().get("/admin/calendar").text
    assert "<h1>Мои дела</h1>" not in off_page and ">День</a>" in off_page
    # Явный view=list без простого режима не включает список (тот же день).
    assert "<h1>Мои дела</h1>" not in _client().get("/admin/calendar?view=list").text
