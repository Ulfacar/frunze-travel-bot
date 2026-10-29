"""Страница «Архив Битрикса»: только чтение, только полный админ, флаг OFF.

Архив — синтетические JSONL в tmp (формат `scripts/bitrix_archive_export.py`).
"""
import json
import tracemalloc

import pytest
from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.core import flags
from app.integrations.crm import bitrix_archive as archive
from app.integrations.panel import store as panel_store

FLAG = "panel_bitrix_archive_enabled"


def _write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


@pytest.fixture
def arch(tmp_path):
    d = tmp_path / "arch"
    d.mkdir()
    _write(d / "contacts.jsonl", [{"ID": "7", "NAME": "Асель", "PHONE": [{"VALUE": "+996 555 111 222"}]}])
    _write(d / "leads.jsonl", [
        {"ID": "70", "TITLE": "Шенген Италия", "STATUS_ID": "NEW", "CONTACT_ID": "7",
         "COMMENTS": "<b>жирный</b>", "DATE_CREATE": "2026-06-01T10:00:00+06:00"},
        {"ID": "71", "TITLE": "Чужой лид", "PHONE": [{"VALUE": "0555999888"}]}])
    _write(d / "deals.jsonl", [{"ID": "700", "TITLE": "Виза", "LEAD_ID": "70", "OPPORTUNITY": "250",
                                "CURRENCY_ID": "USD", "STAGE_ID": "C1:WON"}])
    _write(d / "timeline.jsonl", [
        {"entity_type": "lead", "entity_id": 70, "comments": [
            {"ID": "1", "CREATED": "2026-06-01T10:05", "COMMENT": "<script>alert(1)</script><img src=x onerror=alert(2)>"},
            {"ID": "2", "CREATED": "2026-06-02T11:00", "COMMENT": "Перезвонить [b]завтра[/b]"}]}])
    return d


@pytest.fixture
def env(monkeypatch, arch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    admin_router._look_cache["key"] = None
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login="medina", name="Медина", password="m1"),
        ManagerConfig(login="aisina", name="Айсина", password="a1")])
    monkeypatch.setattr(app.config.settings, "admin_new_look_enabled", True)
    monkeypatch.setattr(app.config.settings, "bitrix_archive_dir", str(arch))
    yield monkeypatch
    flags.reset()
    admin_router._look_cache["key"] = None


def _on():
    import asyncio
    asyncio.run(flags.set_flag(FLAG, True))
    admin_router._look_cache["key"] = None


def _client(login="admin", pw=None):
    pw = pw or {"admin": "frunze", "medina": "m1", "aisina": "a1"}[login]
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/admin/login", data={"login": login, "password": pw}).status_code == 200
    return c


def test_flag_off_404_and_no_menu(env):
    c = _client()
    assert c.get("/admin/bitrix-archive").status_code == 404
    assert "/admin/bitrix-archive" not in c.get("/admin/calendar").text


def test_admin_finds_client_in_any_phone_format(env):
    _on()
    c = _client()
    assert "/admin/bitrix-archive" in c.get("/admin/calendar").text      # пункт в «Ещё»
    for q in ("0555 111 222", "+996555111222", "555-111-222", "996 (555) 11-12-22"):
        r = c.get("/admin/bitrix-archive", params={"phone": q})
        assert r.status_code == 200
        assert "Асель" in r.text and "Лид #70" in r.text and "Сделка #700" in r.text
        assert "250 USD" in r.text and "комментариев 2" in r.text
        assert "Чужой лид" not in r.text
    audit = [a for a in panel_store._memory_store._audit if a["action"] == "bitrix_archive"]
    assert len(audit) == 4 and all(a["detail"] == "…1222" for a in audit)   # не весь номер


@pytest.mark.parametrize("login", ["medina", "aisina"])
def test_managers_are_forbidden(env, login):
    _on()
    c = _client(login)
    assert c.get("/admin/bitrix-archive", params={"phone": "0555111222"}).status_code == 403
    assert "/admin/bitrix-archive" not in c.get("/admin/calendar").text


def test_archive_text_is_escaped(env):
    _on()
    html = _client().get("/admin/bitrix-archive", params={"phone": "0555111222"}).text
    assert "<script>alert(1)" not in html and "<img src=x" not in html and "<b>жирный" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html and "&lt;b&gt;жирный" in html


def test_missing_archive_explains_what_to_do(env, tmp_path):
    _on()
    env.setattr(app.config.settings, "bitrix_archive_dir", str(tmp_path / "nope"))
    r = _client().get("/admin/bitrix-archive", params={"phone": "0555111222"})
    assert r.status_code == 200 and "Архив не найден" in r.text and "BITRIX_ARCHIVE_DIR" in r.text
    env.setattr(app.config.settings, "bitrix_archive_dir", "")
    assert "Архив не найден" in _client().get("/admin/bitrix-archive").text


def test_short_and_unknown_numbers(env):
    _on()
    c = _client()
    assert "не меньше 7 цифр" in c.get("/admin/bitrix-archive", params={"phone": "12345"}).text
    assert "ничего нет" in c.get("/admin/bitrix-archive", params={"phone": "0700000000"}).text


def test_large_archive_is_streamed_not_loaded(tmp_path):
    """60 000 лидов (~10 МБ): пик памяти поиска — доли файла, не весь архив."""
    d = tmp_path / "big"
    d.mkdir()
    with open(d / "leads.jsonl", "w", encoding="utf-8") as fh:
        for i in range(60_000):
            fh.write(json.dumps({"ID": str(i), "TITLE": "x" * 80, "COMMENTS": "y" * 60,
                                 "PHONE": [{"VALUE": f"+996 700 {i:06d}"}]}) + "\n")
    (d / "contacts.jsonl").write_text("")
    size = (d / "leads.jsonl").stat().st_size
    tracemalloc.start()
    found = archive.search(d, "0700 012 345")
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert [x["ID"] for x in found["leads"]] == ["12345"]
    assert size > 9_000_000 and peak < size / 10, (size, peak)


def test_result_count_is_capped(tmp_path):
    d = tmp_path / "many"
    d.mkdir()
    _write(d / "leads.jsonl", [{"ID": str(i), "PHONE": [{"VALUE": "0555000000"}]} for i in range(300)])
    found = archive.search(d, "0555000000", limit=50)
    assert len(found["leads"]) == 50 and found["truncated"] is True
