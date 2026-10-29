"""Поток ux, 3-й заход (30.10.2026): правки ВИДА договора, оплаты и экранов клиента
не меняют ни одной POST-формы.

Что сравнивается. Для каждой формы, которая уходит POST'ом (`method="post"` или
`hx-post`), — её открывающий тег и открывающие теги всех полей внутри (`input`,
`select`, `option`, `textarea`, `button`) со ВСЕМИ атрибутами, по порядку. Это и есть то,
что получает сервер: имена полей, скрытые ключи идемпотентности, адреса, типы,
обязательность, ограничения. Подписи и тексты вокруг полей сюда не входят — их и меняли.

Значения, которые сервер рендерит заново на каждый запрос (ключи идемпотентности,
csrf, подпись формы, текущее время), заменены маской, а сам атрибут остаётся: пропажа
или переименование скрытого ключа всё равно ловится.

Эталон `fixtures/ux_forms_golden.json` снят на интеграции `8de0842` ДО правок вида
(`UX_FORMS_GOLDEN_WRITE=1 pytest tests/test_ux_forms_unchanged.py`). Сравнение —
байт-в-байт по сериализованной строке.
"""
import asyncio
import json
import os
from html.parser import HTMLParser
from pathlib import Path

import pytest

import app.admin.router as admin_router
import app.config

import test_admin_clients as tc
import test_admin_contracts as tk
import test_admin_workday as tw
from test_admin_contracts import env as contract_env  # noqa: F401 — фикстура
from test_admin_clients import env as clients_env  # noqa: F401 — фикстура

GOLDEN = Path(__file__).parent / "fixtures" / "ux_forms_golden.json"
WRITE = os.environ.get("UX_FORMS_GOLDEN_WRITE") == "1"
DYNAMIC = {"idempotency_key", "csrf_token", "key_signature", "request_key", "signature",
           "note_key", "signed_at", "send_key"}
CONTROLS = {"input", "select", "option", "textarea", "button"}


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms: list[list[str]] = []
        self._cur: list[str] | None = None
        self._depth = 0

    @staticmethod
    def _tag(tag, attrs):
        name = dict(attrs).get("name", "")
        parts = []
        for k, v in attrs:
            if k == "value" and name in DYNAMIC:
                v = "<dynamic>"
            parts.append(f'{k}="{v}"' if v is not None else k)
        return f"<{tag} " + " ".join(parts) + ">"

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            if self._cur is not None:
                self._depth += 1
                return
            if (a.get("method") or "").lower() == "post" or "hx-post" in a:
                self._cur = [self._tag(tag, attrs)]
                self._depth = 0
            return
        if self._cur is not None and tag in CONTROLS:
            self._cur.append(self._tag(tag, attrs))

    def handle_endtag(self, tag):
        if tag == "form" and self._cur is not None:
            if self._depth:
                self._depth -= 1
                return
            self.forms.append(self._cur)
            self._cur = None


def forms_of(html: str) -> list[str]:
    parser = _Forms()
    parser.feed(html)
    return ["\n".join(f) for f in parser.forms]


def _check(key: str, html: str):
    got = forms_of(html)
    assert got, f"{key}: на странице нет POST-форм — проверка была бы пустой"
    data = json.loads(GOLDEN.read_text("utf-8")) if GOLDEN.exists() else {}
    if WRITE:
        data[key] = got
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
        return
    assert key in data, f"нет эталона для {key}"
    assert got == data[key], f"{key}: POST-формы изменились"


@pytest.fixture(params=[True, False], ids=["simple", "plain"])
def simple(request, monkeypatch):
    monkeypatch.setattr(app.config.settings, "panel_simple_mode_enabled", request.param,
                        raising=False)
    admin_router._look_cache["key"] = None
    return request.param


# ---------------- договор ----------------
def test_contract_form_is_unchanged(contract_env, simple):  # noqa: F811
    sm, conv, ids, client = contract_env
    r = client.get(tk.URL)
    assert r.status_code == 200
    _check(f"contract/{'simple' if simple else 'plain'}", r.text)


# ---------------- карточка услуги: этапы, деньги, задачи ----------------
def _case_env(monkeypatch, tmp_path):
    tw._clear(); tw._managers(monkeypatch); tw._on(monkeypatch)
    sm = tw._make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    return sm


@pytest.mark.parametrize("tab", ["path", "money", "tasks"])
def test_manager_case_forms_are_unchanged(monkeypatch, tmp_path, simple, tab):
    sm = _case_env(monkeypatch, tmp_path)
    from datetime import datetime, timedelta, timezone
    case = tw._seed_case(sm, reference="UX-FORMS",
                         task_at=datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc) + timedelta(days=1))
    html = tw._login(tw.MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}?tab={tab}").text
    _check(f"case-manager/{tab}/{'simple' if simple else 'plain'}", html)


def test_admin_money_forms_with_a_payment_are_unchanged(monkeypatch, tmp_path, simple):
    sm = _case_env(monkeypatch, tmp_path)
    case = tw._admin_case(sm, monkeypatch, tmp_path, reference="UX-ADM")
    client = tw._login()
    r = client.post(f"/admin/case/{case['case_id']}/money/payment",
                    data={"amount": "100.00", "currency": "KGS", "idempotency_key": "ux-forms-1"})
    assert r.headers.get("X-Action-Outcome") == "recorded"
    html = client.get(f"/admin/case/{case['case_id']}?tab=money").text
    _check(f"case-admin/money/{'simple' if simple else 'plain'}", html)


# ---------------- новый клиент, заметки ----------------
def test_new_client_form_is_unchanged(clients_env, simple):  # noqa: F811
    tc._on("panel_manual_lead_enabled", "panel_client_card_enabled")
    html = tc._client("medina").get("/admin/clients/new").text
    _check(f"client-new/{'simple' if simple else 'plain'}", html)


def test_chat_note_form_is_unchanged(clients_env, simple):  # noqa: F811
    tc._on("panel_client_card_enabled")
    tc._seed(tc.VISA_UID)
    html = tc._client("medina").get(f"/admin/conversation/{tc.VISA_UID}").text
    notes = [f for f in forms_of(html) if "/notes" in f.split("\n")[0]]
    assert notes, "в чате нет формы заметки"
    _check(f"chat-note/{'simple' if simple else 'plain'}", html.split('<details class="chat-dossier chat-notes"')[1].split("</details>")[0])
