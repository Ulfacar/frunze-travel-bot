"""Source search: existing gates precede loading; escaped output; no SQL access."""
import pytest
from fastapi.testclient import TestClient

import app.admin.kg_knowledge as ui
import app.admin.router as ar
import app.main as main
from app.knowledge.retrieval import RetrievalError
from tests.test_admin_kg_entry import env
from tests.test_admin_workday import _login

URL = "/admin/kg-entry/knowledge"


def test_search_native_empty_results_filters_and_source_no_db(env, monkeypatch):
    def forbidden(): raise AssertionError("DB not needed")
    monkeypatch.setattr(ar, "_domain_sessionmaker", forbidden)
    client = env["client"]
    assert 'id="kg-search-empty"' in client.get(URL).text
    page = client.get(URL, params={"q": "семья", "block": "10"})
    assert page.status_code == 200 and "KG.KB.10.0" in page.text and "БЛОК 10. Семья" in page.text
    assert "черновик для проверки специалистом" in page.text and "выдача клиенту не разрешена" in page.text
    assert page.headers["cache-control"] == "no-store" and page.headers["referrer-policy"] == "no-referrer"
    assert 'id="kg-search-none"' in client.get(URL, params={"q": "quuxxyz"}).text


@pytest.mark.parametrize("login", [None, "ademi", "medina"])
def test_unauthorized_before_source(env, monkeypatch, login):
    def forbidden(): raise AssertionError("source accessed")
    monkeypatch.setattr(ui, "load_review_index", forbidden)
    client = _login(login) if login else TestClient(main.app, base_url="https://testserver")
    try:
        assert client.get(URL).status_code == (401 if login is None else 403)
    finally:
        client.close()


@pytest.mark.parametrize("flag", ["admin_kg_entry_enabled", "admin_workday_enabled"])
def test_disabled_before_source(env, monkeypatch, flag):
    def forbidden(): raise AssertionError("source accessed")
    monkeypatch.setattr(ui, "load_review_index", forbidden)
    monkeypatch.setattr(ar.settings, flag, False)
    assert env["client"].get(URL).status_code == 404


@pytest.mark.parametrize("params", [{"q": "a" * 201}, {"q": "x\n"}, {"block": "3"},
                                    [("q", "a"), ("q", "b")], {"source": "../../.env"}])
def test_invalid_query(env, monkeypatch, params):
    def forbidden(): raise AssertionError("source accessed")
    monkeypatch.setattr(ui, "load_review_index", forbidden)
    response = env["client"].get(URL, params=params)
    assert response.status_code == 422 and 'role="alert"' in response.text


def test_corrupt_source_error_and_xss_query(env, monkeypatch):
    query = '<script>alert("x")</script>'
    page = env["client"].get(URL, params={"q": query})
    assert page.status_code == 200 and query not in page.text and "&lt;script&gt;" in page.text
    def unavailable(): raise RetrievalError("source_hash_mismatch")
    monkeypatch.setattr(ui, "load_review_index", unavailable)
    error = env["client"].get(URL, params={"q": query})
    assert error.status_code == 503 and "проверку целостности" in error.text and query not in error.text
    assert error.headers["cache-control"] == "no-store"
