"""B2a (14.10): файлы в панели бота — отправка менеджером и просмотр файлов клиента.

Синтетика: фейковый адаптер и httpx.MockTransport, ни одного обращения к Wappi.
"""
import asyncio
import base64
import json

import httpx
import pytest

import app.admin.router as admin_router
from app.channels import wappi
from app.channels.wappi import WappiAdapter
from app.config import BotConfig
from app.core import flags
from app.core.bots import BotRegistry
from app.integrations.panel.store import get_conversation_store
from tests.test_live_authz import USER_ID, _client, _conv, _setup

PDF = b"%PDF-1.4\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 200


@pytest.fixture
def media(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    import app.core.bots as bots
    monkeypatch.setattr(bots, "registry", BotRegistry([BotConfig(id="getvisa", scenario="visa",
                                                                 wappi_profile_id="prof-visa")]))
    monkeypatch.setattr(admin_router.settings, "panel_send_media_max_mb", 1)
    asyncio.run(flags.set_flag("panel_send_media_enabled", True))
    asyncio.run(flags.set_flag("panel_media_view_enabled", True))
    calls = []
    behaviour = {"mode": "ok"}

    async def fake_send_file(self, chat_id, data, *, filename, mime, caption=""):
        calls.append(dict(profile=self._profile_id, filename=filename, mime=mime, size=len(data), caption=caption))
        if behaviour["mode"] == "timeout":
            raise httpx.ReadTimeout("slow")
        if behaviour["mode"] == "fail":
            raise RuntimeError("rejected")
        return f"wappi-file-{len(calls)}"

    async def fake_download(self, message_id):
        calls.append(dict(download=message_id, profile=self._profile_id))
        return PNG, "image/png"

    monkeypatch.setattr(WappiAdapter, "send_file", fake_send_file)
    monkeypatch.setattr(WappiAdapter, "download_media", fake_download)
    return dict(calls=calls, behaviour=behaviour)


def _post_file(client, data=PDF, name="passport-list.pdf", caption=""):
    return client.post(f"/admin/conversation/{USER_ID}/send-file",
                       files={"upload": (name, data, "application/octet-stream")}, data={"caption": caption})


def _manager_messages():
    return [(m.text, m.status) for m in _conv().messages if m.sender == "manager"]


def test_flags_off_hide_both_routes(media):
    asyncio.run(flags.set_flag("panel_send_media_enabled", False))
    asyncio.run(flags.set_flag("panel_media_view_enabled", False))
    c = _client("medina", "m1")
    assert _post_file(c).status_code == 404
    assert c.get(f"/admin/conversation/{USER_ID}/media/1").status_code == 404
    assert media["calls"] == []


def test_owner_sends_pdf_with_profile_of_dialog_bot(media):
    c = _client("medina", "m1")
    r = _post_file(c, caption="список документов")
    assert r.headers["X-Action-Outcome"] == "sent"
    assert media["calls"] == [dict(profile="prof-visa", filename="passport-list.pdf", mime="application/pdf",
                                   size=len(PDF), caption="список документов")]
    assert _manager_messages() == [("📎 passport-list.pdf", "sent")]
    assert _conv().intercepted is True and _conv().assigned_to == "medina"
    audit = asyncio.run(get_conversation_store().list_audit())
    assert any(a["action"] == "send_file" for a in audit)


def test_colleagues_dialog_is_denied(media):
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    r = _post_file(_client("eliza", "e1"))
    assert r.headers["X-Action-Outcome"] == "denied"
    assert media["calls"] == []


def test_too_big_file_is_refused(media):
    r = _post_file(_client("medina", "m1"), data=b"%PDF-" + b"z" * (1024 * 1024 + 10))
    assert r.headers["X-Action-Outcome"] == "denied"
    assert media["calls"] == [] and _manager_messages() == []


@pytest.mark.parametrize("name,data", [("virus.pdf", b"MZ\x90\x00" + b"q" * 50),
                                       ("script.exe", b"MZ\x90\x00"), ("notes.txt", b"hello"),
                                       ("fake.webp", b"RIFF1234AVI " + b"q" * 20)])
def test_wrong_type_by_signature_is_refused(media, name, data):
    r = _post_file(_client("medina", "m1"), data=data, name=name)
    assert r.headers["X-Action-Outcome"] == "denied"
    assert media["calls"] == []


def test_provider_timeout_is_unknown_and_not_retried(media):
    media["behaviour"]["mode"] = "timeout"
    c = _client("medina", "m1")
    assert _post_file(c).headers["X-Action-Outcome"] == "unknown"
    assert _manager_messages() == [("📎 passport-list.pdf", "unknown")]
    assert len(media["calls"]) == 1
    # «Повторить» для файла недоступно: байты мы не храним, а исход неизвестен.
    mid = next(m.id for m in _conv().messages if m.sender == "manager")
    assert c.post(f"/admin/conversation/{USER_ID}/resend/{mid}").headers["X-Action-Outcome"] == "denied"
    assert len(media["calls"]) == 1


def test_failed_file_cannot_be_resent_blindly(media):
    media["behaviour"]["mode"] = "fail"
    c = _client("medina", "m1")
    assert _post_file(c).headers["X-Action-Outcome"] == "failed"
    mid = next(m.id for m in _conv().messages if m.sender == "manager")
    assert c.post(f"/admin/conversation/{USER_ID}/resend/{mid}").headers["X-Action-Outcome"] == "denied"
    assert len(media["calls"]) == 1


def test_same_file_twice_within_two_minutes_is_sent_once(media):
    c = _client("medina", "m1")
    assert _post_file(c).headers["X-Action-Outcome"] == "sent"
    assert _post_file(c).headers["X-Action-Outcome"] == "duplicate"
    assert len(media["calls"]) == 1


def _client_file(provider_id="WAPPI-IN-1", text="🖼 Фото/скриншот"):
    store = get_conversation_store()
    return asyncio.run(store.add_message(USER_ID, "client", text, channel="whatsapp", bot_id="getvisa",
                                         phone="996700123456", provider_msg_id=provider_id))


def test_manager_opens_client_photo(media):
    mid = _client_file()
    r = _client("medina", "m1").get(f"/admin/conversation/{USER_ID}/media/{mid}")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert media["calls"] == [dict(download="WAPPI-IN-1", profile="prof-visa")]


def test_media_view_refuses_non_client_or_idless_messages(media):
    c = _client("medina", "m1")
    assert c.get(f"/admin/conversation/{USER_ID}/media/{_client_file(provider_id='')}").status_code == 404
    store = get_conversation_store()
    bot_mid = asyncio.run(store.add_message(USER_ID, "bot", "ответ", channel="whatsapp", bot_id="getvisa",
                                            phone="996700123456", provider_msg_id="WAPPI-OUT-1"))
    assert c.get(f"/admin/conversation/{USER_ID}/media/{bot_mid}").status_code == 404
    assert media["calls"] == []


def test_media_view_respects_team_scope(media, monkeypatch):
    """Менеджер туров не открывает файл визового клиента."""
    from app.config import ManagerConfig
    from tests.test_live_authz import MANAGERS
    monkeypatch.setattr(admin_router.settings, "managers", MANAGERS + [ManagerConfig(login="ademi", name="Адеми", password="a1")])
    mid = _client_file()
    assert _client("ademi", "a1").get(f"/admin/conversation/{USER_ID}/media/{mid}").status_code == 404
    assert media["calls"] == []


def test_card_shows_open_link_only_with_flag(media):
    mid = _client_file()
    c = _client("medina", "m1")
    assert f"/media/{mid}" in c.get(f"/admin/conversation/{USER_ID}").text
    asyncio.run(flags.set_flag("panel_media_view_enabled", False))
    from app.admin import router as r
    r._look_cache["at"] = 0.0
    assert f"/media/{mid}" not in c.get(f"/admin/conversation/{USER_ID}").text


# --- запросы к Wappi строятся по документации (без сети) ---

def _adapter(handler):
    bot = BotConfig(id="getvisa", scenario="visa", wappi_profile_id="prof-visa")
    a = WappiAdapter(bot=bot, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    a._token = "SYNTHETIC-token"
    return a


def test_send_file_uses_document_endpoint_with_plain_base64():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, params=dict(request.url.params), body=json.loads(request.content))
        return httpx.Response(200, json={"status": "done", "message_id": "3EB0ABC"})
    mid = asyncio.run(_adapter(handler).send_file("996700123456@c.us", PDF, filename="a.pdf",
                                                  mime="application/pdf", caption="c"))
    assert mid == "3EB0ABC"
    assert seen["path"] == "/api/sync/message/document/send"
    assert seen["params"]["profile_id"] == "prof-visa"
    assert seen["body"]["b64_file"] == base64.b64encode(PDF).decode() and not seen["body"]["b64_file"].startswith("data:")
    assert seen["body"]["file_name"] == "a.pdf" and seen["body"]["caption"] == "c"


def test_send_file_uses_img_endpoint_for_pictures():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message_id": "3EB0DEF"})
    asyncio.run(_adapter(handler).send_file("996700123456@c.us", PNG, filename="p.png", mime="image/png"))
    assert seen["path"] == "/api/sync/message/img/send" and "file_name" not in seen["body"]


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(200, content=PNG, headers={"content-type": "image/png"}), (PNG, "image/png")),
    (httpx.Response(200, json={"file": base64.b64encode(PDF).decode(), "mimetype": "application/pdf"}), (PDF, "application/pdf")),
])
def test_download_media_accepts_raw_or_base64(response, expected):
    assert asyncio.run(_adapter(lambda r: response).download_media("X1")) == expected


def test_download_media_unknown_shape_raises():
    with pytest.raises(ValueError):
        asyncio.run(_adapter(lambda r: httpx.Response(200, json={"status": "ok"})).download_media("X1"))


# --- входящий файл клиента сохраняет id провайдера ---

def test_incoming_non_text_keeps_provider_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=False)
    from app.channels.base import Message
    from app.core.orchestrator import Orchestrator
    o = Orchestrator(channel=WappiAdapter(bot=BotConfig(id="getvisa", scenario="visa", wappi_profile_id="p")),
                     bot=BotConfig(id="getvisa", scenario="visa", wappi_profile_id="p"))
    msg = Message(channel="whatsapp", user_id="996700123456", chat_id="996700123456@c.us", text="",
                  kind="non_text", media_type="image", raw={"id": "WAPPI-IN-9", "type": "image"})
    asyncio.run(o._log_in(msg, "🖼 Фото/скриншот"))
    client_msgs = [m for m in _conv().messages if m.sender == "client"]
    assert client_msgs[-1].provider_msg_id == "WAPPI-IN-9"
