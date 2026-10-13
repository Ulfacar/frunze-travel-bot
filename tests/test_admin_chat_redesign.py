"""Гейт чата «Пальма»: проверяем ответы сервера, чтобы выключенная ветка не прошла тесты."""
import asyncio
import hashlib
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from unittest.mock import AsyncMock
from xml.etree.ElementTree import Element, SubElement

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.admin.router as admin_router
import app.main as main
from app.config import ManagerConfig, Settings, settings
from app.core import flags
from app.integrations.panel import store as panel_store

FLAG = "admin_chat_redesign_enabled"
USER = "getvisa:996700000101"
URL = f"/admin/conversation/{USER}"


class Rendered(HTMLParser):
    """Минимальное DOM-дерево без новой зависимости: важна вложенность, а не подстроки CSS."""

    def __init__(self, html):
        super().__init__()
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = SubElement(self.stack[-1], tag, dict((k, v or "") for k, v in attrs))
        if tag not in {"input", "br", "hr", "meta", "link", "img", "wbr", "source"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        node = self.stack[-1]
        node.text = (node.text or "") + data

    def nodes(self, cls=None, tag=None, root=None):
        return [
            node for node in (self.root if root is None else root).iter()
            if (tag is None or node.tag == tag)
            and (cls is None or cls in node.get("class", "").split())
        ]


def _text(node):
    return "".join(node.itertext())


def _seed(*, messages=True, user=USER, bot_id="getvisa"):
    store = panel_store.get_conversation_store()

    async def seed():
        await store.ensure(user, phone=user.split(":")[-1], channel="whatsapp", bot_id=bot_id)
        await store.update_meta(
            user,
            funnel="visa", qualification={"name": "Жылдыз", "страна": "Италия"},
            ai_summary="Первый Шенген", manager_next_step="Позвонить в 11:00",
            outcome_inferred="active", outcome_inferred_reason="Ждёт документы",
            source="ad", source_headline="Шенген без очередей",
        )
        if messages:
            for sender, message, status in (
                ("client", "Какие документы нужны?", ""),
                ("bot", "Подготовлю список", "delivered"),
                ("manager", "Позвоню вам утром", "sent"),
            ):
                await store.add_message(user, sender, message, status=status)
            for message in store._conv[user].messages:
                message.created_at = datetime(2026, 10, 4, 5, 30, tzinfo=timezone.utc)
    asyncio.run(seed())
    return store._conv[user]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # Изолируем панель и часы кэша: состояние предыдущего теста не должно выбирать ветку.
    monkeypatch.setattr(settings, "panel_backend", "memory")
    monkeypatch.setattr(settings, "state_backend", "memory")
    monkeypatch.setattr(settings, FLAG, False)
    monkeypatch.setattr(settings, "admin_new_look_enabled", False)
    monkeypatch.setattr(settings, "authz_enforce_enabled", False)
    monkeypatch.setattr(settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="test", admin=True),
        ManagerConfig(login="medina", name="Медина", password="test"),
        ManagerConfig(login="eliza", name="Элиза", password="test"),
        ManagerConfig(login="ademi", name="Адеми", password="test"),
    ])
    monkeypatch.setattr(admin_router, "_look_cache", {
        "at": 0.0, "key": None, "new_look": None, "focus_on": None, "chat_redesign": None,
    })
    monkeypatch.setattr(admin_router, "_load_user_tasks", AsyncMock(return_value=[]))
    monkeypatch.setattr(admin_router, "_bishkek_today", lambda: date(2026, 10, 4))
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    monkeypatch.setattr(panel_store._memory_store, "_mid", 0)
    flags.reset()
    yield
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()


def _client(login="admin"):
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": login, "password": "test"}).status_code == 200
    return client


@pytest.mark.parametrize("chat_on", [False, True])
@pytest.mark.parametrize("shell_on", [False, True])
def test_rendered_layout_is_selected_independently(monkeypatch, chat_on, shell_on):
    monkeypatch.setattr(settings, FLAG, chat_on)
    monkeypatch.setattr(settings, "admin_new_look_enabled", shell_on)
    _seed()
    client = _client()
    response = client.get(URL)
    assert response.status_code == 200
    dom = Rendered(response.text)
    for cls in ("chat-palma", "chat-menu", "chat-dossier", "chat-quick-replies"):
        assert bool(dom.nodes(cls)) is chat_on
    for cls in ("brief", "manager-brief", "quick-replies", "ph-head", "ph-sub", "ph-actions", "chat-details"):
        assert bool(dom.nodes(cls)) is not chat_on
    if chat_on:
        dossier = dom.nodes("chat-dossier")[0]
        assert "open" not in dossier.attrib
        assert response.text.index('class="msgs ') < response.text.index('class="chat-dossier"')
        for value in ("ИИ-исход", "Первый Шенген", "Позвонить в 11:00", "Что узнал бот",
                      "Италия", "Шенген без очередей", "Задачи"):
            assert value in _text(dossier)
        menu = dom.nodes("chat-menu")[0]
        for value in ("копировать", "whatsapp", "visa", "новый", "Перехватить — бот замолчит",
                      "Передать менеджеру", "Исход диалога", "Архивировать"):
            assert value in _text(menu)
        assert dom.nodes("chat-menu-action", root=menu)
        assert dom.nodes("chat-send", tag="button")[0].get("type") == "submit"
        assert dom.nodes("chat-suggest", tag="button")[0].get("type") == "button"
        # Значки интерфейса заменены; содержание клиентских сообщений не фильтруется.
        assert not any(char in _text(dom.root) for char in "✨⚠🔒⏳✓✗➕ℹ📣✅❌💤🏢📞🤝🔁📋")
    page = client.get("/admin").text
    assert ("--wa-bg:#ECE5DD" in page) is chat_on
    assert ('id="chat-loading-template"' in page) is chat_on


def test_flag_default_is_off():
    assert Settings.model_fields[FLAG].default is False


def test_off_card_is_byte_for_byte_the_original_render():
    # Отпечаток снят с исходной карточки af8e440 на этой фиксированной фикстуре.
    # Во время теста читаем только HTTP-ответ: мёртвая ветка шаблона гейт не обманет.
    #
    # Отпечаток обновлён 05.10 при E2-01/E2-02: в список видов задач добавлены
    # `checkin`, `departure`, `review_request`, `complaint` — их заводят операции
    # по билетам и турам, и без подписи в календаре отображался сырой код вида.
    # Причина изменения проверена отдельно: с убранными четырьмя видами прежний
    # отпечаток совпадал, то есть РАЗМЕТКА карточки не менялась — только набор
    # опций в выпадающем списке.
    _seed()
    response = _client().get(URL)
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == (
        "5a2e7e33861462eff282075d45685452bfc65db9442fd092046632a0f43c3a4b"
    )


def test_runtime_flag_and_cache_expiry_change_rendered_card(monkeypatch):
    _seed()
    client = _client()
    assert not Rendered(client.get(URL).text).nodes("chat-dossier")
    asyncio.run(flags.set_flag(FLAG, True))
    monkeypatch.setitem(admin_router._look_cache, "at", 0.0)
    assert Rendered(client.get(URL).text).nodes("chat-dossier")
    # Повторный запрос обязан брать из кэша также и новый, третий флаг.
    assert Rendered(client.get(URL).text).nodes("chat-dossier")
    asyncio.run(flags.set_flag(FLAG, False))
    monkeypatch.setitem(admin_router._look_cache, "at", 0.0)
    assert not Rendered(client.get(URL).text).nodes("chat-dossier")


@pytest.mark.parametrize("on", [False, True])
def test_flag_fallback_on_store_error(monkeypatch, on):
    monkeypatch.setattr(settings, FLAG, on)
    client = _client()
    monkeypatch.setitem(admin_router._look_cache, "at", 0.0)
    monkeypatch.setattr(flags, "get_flag", AsyncMock(side_effect=RuntimeError("offline")))
    _seed()
    assert bool(Rendered(client.get(URL).text).nodes("chat-dossier")) is on


@pytest.mark.parametrize("on", [False, True])
def test_polling_draft_and_intercept_hint_survive(monkeypatch, on):
    monkeypatch.setattr(settings, FLAG, on)
    _seed()
    body = _client().get(URL).text
    dom = Rendered(body)
    panel = dom.nodes("panel")[0]
    assert panel.get("hx-get") == URL
    assert panel.get("hx-swap") == "outerHTML"
    assert panel.get("hx-target") == "this"
    trigger = panel.get("hx-trigger")
    assert "every 4s" in trigger
    assert "document.visibilityState==='visible'" in trigger
    assert "!(document.activeElement && document.activeElement.closest('.composer'))" in trigger
    form = dom.nodes("composer", tag="form")[0]
    assert form.get("id") == f"composer-{USER}"
    assert form.get("hx-preserve") == "true"
    assert form.get("hx-post") == URL + "/send"
    assert form.get("hx-target") == "#chat"
    assert form.get("hx-swap") == "innerHTML"
    # В старой подписи есть слово «ответа»: сохраняем OFF дословно, включая эту формулировку.
    assert re.search(r"Отправка (?:ответа )?перехватывает диалог — бот замолкает", body)


@pytest.mark.parametrize("on", [False, True])
def test_send_takeover_release_and_archive_use_existing_actions(monkeypatch, on):
    monkeypatch.setattr(settings, FLAG, on)
    conv = _seed()
    outbound = AsyncMock(return_value="chat-test-provider-id")
    monkeypatch.setattr(admin_router.outbound, "send_to_client", outbound)
    client = _client("medina")
    body = client.get(URL).text
    dom = Rendered(body)
    assert any(n.get("hx-post") == URL + "/takeover" for n in dom.nodes(tag="button"))
    assert "archiveConversation(" in body
    assert client.post(URL + "/takeover").headers["X-Action-Outcome"] == "claimed"
    assert conv.intercepted and conv.assigned_to == "medina"
    assert client.post(URL + "/release").status_code == 200
    assert not conv.intercepted
    response = client.post(URL + "/send", data={"text": "Проверочный ответ"})
    assert response.headers["X-Action-Outcome"] == "sent"
    outbound.assert_awaited_once_with("whatsapp", "getvisa", USER, "Проверочный ответ")
    assert conv.messages[-1].text == "Проверочный ответ"
    assert conv.messages[-1].status == "sent"
    assert conv.intercepted and conv.assigned_to == "medina"
    assert bool(Rendered(response.text).nodes("chat-dossier")) is on
    assert client.post(URL + "/archive").status_code == 200
    assert conv.archived


@pytest.mark.parametrize("on", [False, True])
@pytest.mark.parametrize("action", ["", "/send", "/takeover", "/archive", "/resend/1", "/reassign"])
def test_other_direction_is_inaccessible(monkeypatch, on, action):
    monkeypatch.setattr(settings, FLAG, on)
    conv = _seed()
    sender = AsyncMock()
    monkeypatch.setattr(admin_router.outbound, "send_to_client", sender)
    client = _client("ademi")
    response = (client.post(URL + action, data={"text": "Запрещено", "target": "ademi"})
                if action else client.get(URL))
    assert response.status_code == (403 if action == "/reassign" else 404)
    assert not conv.intercepted and not conv.archived and not conv.assigned_to
    assert len(conv.messages) == 3
    sender.assert_not_awaited()


@pytest.mark.parametrize("on", [False, True])
def test_peer_ownership_still_blocks_send_and_takeover(monkeypatch, tmp_path, on):
    from app.domain.models import DomainBase

    url = f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}"

    async def init():
        engine = create_async_engine(url)
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)
        await engine.dispose()
    asyncio.run(init())
    engine = create_async_engine(url, poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    monkeypatch.setattr(settings, FLAG, on)
    asyncio.run(flags.set_flag("authz_enforce_enabled", True))
    conv = _seed()
    conv.assigned_to = "eliza"
    sender = AsyncMock()
    monkeypatch.setattr(admin_router.outbound, "send_to_client", sender)
    client = _client("medina")
    try:
        for action in ("send", "takeover"):
            response = client.post(URL + "/" + action, data={"text": "Не отправлять"})
            assert response.headers["X-Action-Outcome"] == "denied"
            assert "eliza" in response.text
        assert conv.assigned_to == "eliza"
        assert not conv.intercepted and len(conv.messages) == 3
        sender.assert_not_awaited()
    finally:
        asyncio.run(engine.dispose())


@pytest.mark.parametrize("on", [False, True])
def test_failed_message_can_be_retried(monkeypatch, on):
    monkeypatch.setattr(settings, FLAG, on)
    conv = _seed()
    sender = AsyncMock(side_effect=RuntimeError("test delivery failure"))
    monkeypatch.setattr(admin_router.outbound, "send_to_client", sender)
    client = _client()
    response = client.post(URL + "/send", data={"text": "Сохраните это сообщение"})
    assert response.headers["X-Action-Outcome"] == "failed"
    message = conv.messages[-1]
    assert message.status == "failed"
    assert "не доставлено" in response.text and "Повторить" in response.text
    dom = Rendered(response.text)
    resend_url = URL + f"/resend/{message.id}"
    assert any(n.get("hx-post") == resend_url for n in dom.nodes(tag="button"))
    if on:
        error = dom.nodes("chat-error")[0]
        assert error.get("role") == "alert" and "hidden" not in error.attrib
        assert "Ошибка отправки в канал" in _text(error)
    sender.side_effect = None
    sender.return_value = "resent-id"
    response = client.post(resend_url)
    assert response.status_code == 200 and message.status == "sent"
    assert resend_url not in response.text
    if on:
        assert "hidden" in Rendered(response.text).nodes("chat-error")[0].attrib


def test_all_statuses_and_times_are_rendered(monkeypatch):
    monkeypatch.setattr(settings, FLAG, True)
    conv = _seed()
    for status in ("pending", "sent", "delivered", "failed"):
        conv.messages[-1].status = status
        dom = Rendered(_client().get(URL).text)
        message = dom.nodes("msg")[-1]
        assert _text(dom.nodes("chat-time", root=message)[0]) == "05:30"
        expected = {"pending": "отправляется", "sent": "отправлено",
                    "delivered": "доставлено", "failed": "не доставлено"}[status]
        assert expected in _text(message) or any(n.get("aria-label") == expected for n in message.iter())
        # Не вводим ISO-атрибут с naive datetime: браузер не должен переинтерпретировать время.
        assert not any(n.get("datetime") for n in message.iter())


def test_empty_chat_uses_mockup_copy(monkeypatch):
    monkeypatch.setattr(settings, FLAG, True)
    _seed(messages=False)
    dom = Rendered(_client().get(URL).text)
    empty = dom.nodes("chat-empty")[0]
    assert "Переписка пустая" in _text(empty)
    assert "Клиент ещё ничего не написал. Первое сообщение от вас перехватит диалог — бот не вмешается." in _text(empty)
    assert not dom.nodes("msg")


def test_dossier_keeps_task_actions_and_source(monkeypatch):
    monkeypatch.setattr(settings, FLAG, True)
    monkeypatch.setattr(admin_router, "_load_user_tasks", AsyncMock(return_value=[{
        "id": 12, "active": True, "time": "11:00", "date_iso": "2026-10-05", "kind_label": "📞 Звонок",
        "priority": "high", "status": "planned", "overdue": False, "comment": "Уточнить документы", "context": "Первый Шенген",
    }]))
    conv = _seed()
    conv.source_url = "https://example.test/source"
    dom = Rendered(_client().get(URL).text)
    dossier = dom.nodes("chat-dossier")[0]
    posts = {n.get("hx-post") for n in dossier.iter() if n.get("hx-post")}
    assert {URL + suffix for suffix in (
        "/outcome", "/task/create", "/task/12/complete", "/task/12/cancel", "/task/12/reschedule",
    )} <= posts
    assert "Уточнить документы" in _text(dossier)
    assert any(n.get("href") == conv.source_url for n in dossier.iter())


def _contrast(fg, bg):
    def luminance(color):
        rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb]
        return sum(x * y for x, y in zip(linear, (.2126, .7152, .0722)))
    a, b = sorted((luminance(fg), luminance(bg)))
    return (b + .05) / (a + .05)


@pytest.mark.parametrize("dark", [False, True])
def test_rendered_palma_palette_has_readable_text(monkeypatch, dark):
    monkeypatch.setattr(settings, FLAG, True)
    page = _client().get("/admin").text
    selector = 'html[data-theme="dark"] .chat-palma' if dark else ".chat-palma"
    block = re.search(re.escape(selector) + r"\s*\{([^{}]+)\}", page).group(1)
    tokens = dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})", block))
    assert tokens["--wa-bg"] == ("#0B141A" if dark else "#ECE5DD")
    assert tokens["--wa-out"] == ("#005C4B" if dark else "#DCF8C6")
    for fg, bg in (
        ("--wa-txt", "--wa-in"), ("--wa-dim", "--wa-in"),
        ("--wa-txt", "--wa-out"), ("--m-meta", "--wa-out"), ("--m-label", "--wa-out"),
        ("--s-ink", "--s-brand-soft"), ("--b-meta", "--s-brand-soft"), ("--b-label", "--s-brand-soft"),
        ("--s-ink-3", "--s-surface"), ("--s-ink-3", "--s-surface-2"),
        ("--s-chip-ink", "--s-surface"), ("--s-on-brand", "--s-brand"),
        ("--s-danger", "--s-danger-soft"), ("--s-on-danger", "--s-danger"),
        ("--s-danger-on-bub", "--wa-out"), ("--s-hd-sub", "--s-hd-bg"),
    ):
        assert _contrast(tokens[fg], tokens[bg]) >= 4.5, (dark, fg, bg)
    for rule in (
        "background:var(--wa-in); color:var(--wa-txt)",
        "background:var(--wa-out); color:var(--wa-txt)",
        "background:var(--s-brand-soft); color:var(--s-ink)",
        "color:var(--wa-tick)",
    ):
        assert rule in page
    assert 'html:not([data-theme="light"]) .chat-palma' in page
    assert "prefers-reduced-motion:reduce" in page
