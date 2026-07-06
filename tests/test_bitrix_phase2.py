"""Тесты Bitrix Фазы 2: адаптер Открытых линий (parse/send/nest_form) и Bitrix24Crm.

REST мокаем через httpx.MockTransport — проверяем метод, URL и payload, без портала.
Структура события imbot — по документации ONIMBOTMESSAGEADD; на реальном портале
форму подтверждаем, но nest_form/parse устойчивы к ней.
"""
import asyncio
import json

import httpx

from app.channels.base import Message
from app.channels.bitrix_openlines import (
    BitrixOpenLinesAdapter,
    bot_id_from_event,
    nest_form,
)
from app.config import BotConfig
from app.integrations.crm.bitrix24 import Bitrix24Crm

WEBHOOK = "https://portal.example/rest/1/abctoken"


def _recording_client(calls, result=42):
    """httpx.AsyncClient на MockTransport: пишет (path, body) и отдаёт {result}."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        return httpx.Response(200, json={"result": result})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------- nest_form / parse ----------------
def test_nest_form_flattens_bitrix_keys():
    flat = [
        ("data[PARAMS][DIALOG_ID]", "chat123"),
        ("data[PARAMS][MESSAGE]", "привет"),
        ("data[PARAMS][FROM_USER_ID]", "555"),
        ("data[BOT][77][BOT_ID]", "77"),
    ]
    event = nest_form(flat)
    assert event["data"]["PARAMS"]["DIALOG_ID"] == "chat123"
    assert event["data"]["PARAMS"]["MESSAGE"] == "привет"
    assert bot_id_from_event(event) == "77"


def test_nest_form_passthrough_nested_dict():
    """Уже вложенный dict (JSON) не ломается."""
    nested = {"data": {"PARAMS": {"DIALOG_ID": "x"}}}
    assert nest_form(nested) is nested


def test_parse_onimbotmessageadd():
    flat = [
        ("data[PARAMS][DIALOG_ID]", "chat9"),
        ("data[PARAMS][MESSAGE]", "хочу тур в Турцию"),
        ("data[PARAMS][FROM_USER_ID]", "1001"),
    ]
    adapter = BitrixOpenLinesAdapter()
    msg = asyncio.run(adapter.parse(nest_form(flat)))
    assert isinstance(msg, Message)
    assert msg.chat_id == "chat9"
    assert msg.user_id == "1001"
    assert msg.text == "хочу тур в Турцию"
    assert msg.kind == "text"


def test_parse_non_text_attachment():
    event = {"data": {"PARAMS": {"DIALOG_ID": "c1", "FROM_USER_ID": "2", "FILES": {"0": {"id": 1}}}}}
    msg = asyncio.run(BitrixOpenLinesAdapter().parse(event))
    assert msg.kind == "non_text"
    assert msg.text == ""


# ---------------- send() через imbot.message.add ----------------
def test_send_calls_imbot_message_add(monkeypatch):
    from app.channels import bitrix_openlines as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)
    calls = []
    bot = BotConfig(id="frunze_tours_1", scenario="tours", bitrix_bot_id="77")
    adapter = BitrixOpenLinesAdapter(bot=bot, client=_recording_client(calls))

    asyncio.run(adapter.send("chat9", "Здравствуйте!"))

    assert len(calls) == 1
    path, body = calls[0]
    assert path.endswith("/imbot.message.add.json")
    assert body == {"DIALOG_ID": "chat9", "MESSAGE": "Здравствуйте!", "BOT_ID": "77"}


def test_send_skipped_without_webhook_url(monkeypatch):
    from app.channels import bitrix_openlines as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", "")
    calls = []
    adapter = BitrixOpenLinesAdapter(bot=None, client=_recording_client(calls))
    asyncio.run(adapter.send("c", "x"))
    assert calls == []  # без URL не шлём


# ---------------- Bitrix24Crm REST (ЛИДЫ) ----------------
def test_create_lead_calls_lead_add_with_name_and_phone(monkeypatch):
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)
    calls = []
    crm = Bitrix24Crm(client=_recording_client(calls, result=321))

    lead_id = asyncio.run(crm.create_lead(
        {"user_id": "996700", "name": "Иван"}, "tours", {"destination": "Турция"}))

    assert lead_id == "321"
    path, body = calls[0]
    assert path.endswith("/crm.lead.add.json")          # ЛИД, не сделка
    assert body["fields"]["NAME"] == "Иван"
    assert body["fields"]["PHONE"] == [{"VALUE": "996700", "VALUE_TYPE": "WORK"}]
    assert "Турция" in body["fields"]["COMMENTS"]
    assert "CATEGORY_ID" not in body["fields"]           # лид не кладём в воронку оплативших


def test_find_lead_id_by_phone(monkeypatch):
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)

    def handler(request):
        return httpx.Response(200, json={"result": {"LEAD": [555]}})

    crm = Bitrix24Crm(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(crm.find_lead_id_by_phone("996700")) == "555"


def test_find_lead_id_by_phone_none(monkeypatch):
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)

    def handler(request):
        return httpx.Response(200, json={"result": {}})

    crm = Bitrix24Crm(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert asyncio.run(crm.find_lead_id_by_phone("996700")) == ""
    assert asyncio.run(crm.find_lead_id_by_phone("")) == ""


def test_update_stage_maps_to_lead_status_id(monkeypatch):
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)
    monkeypatch.setattr(mod.settings, "bitrix_stage_map", {"manager_handoff": "IN_PROCESS"})
    calls = []
    crm = Bitrix24Crm(client=_recording_client(calls))

    asyncio.run(crm.update_stage("321", "manager_handoff"))

    path, body = calls[0]
    assert path.endswith("/crm.lead.update.json")
    assert body == {"id": "321", "fields": {"STATUS_ID": "IN_PROCESS"}}


def test_update_stage_skips_unmapped(monkeypatch):
    """Нет STATUS_ID в карте → не шлём в портал несуществующую стадию."""
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)
    monkeypatch.setattr(mod.settings, "bitrix_stage_map", {})
    calls = []
    crm = Bitrix24Crm(client=_recording_client(calls))

    asyncio.run(crm.update_stage("321", "office_consultation"))
    assert calls == []


def test_add_note_calls_timeline_comment_on_lead(monkeypatch):
    from app.integrations.crm import bitrix24 as mod
    monkeypatch.setattr(mod.settings, "bitrix24_webhook_url", WEBHOOK)
    calls = []
    crm = Bitrix24Crm(client=_recording_client(calls))

    asyncio.run(crm.add_note("321", "клиент тёплый"))

    path, body = calls[0]
    assert path.endswith("/crm.timeline.comment.add.json")
    assert body["fields"]["ENTITY_ID"] == 321            # число, не строка
    assert body["fields"]["ENTITY_TYPE"] == "lead"        # ЛИД, не сделка
    assert body["fields"]["COMMENT"] == "клиент тёплый"
