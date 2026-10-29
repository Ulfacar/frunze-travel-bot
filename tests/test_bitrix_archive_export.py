"""Архив Bitrix: выгрузка только чтением и поиск по телефону. Только фикстуры.

Реальный портал не трогаем: транспорт — фейковый портал в памяти, который умеет
пагинацию Битрикса (`start`, `next`, `total`, фильтр `>ID`), ночные 403, дубли
и сдвиг страниц. Номера синтетические (996555…).
"""
import io
import json
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bitrix_archive_export as exp   # noqa: E402
import bitrix_archive_search as srch  # noqa: E402

WEBHOOK = "https://portal.invalid/rest/1/secret-token"


class Crash(BaseException):
    """Процесс убили посреди выгрузки (не ловится `except Exception`)."""


class FakePortal:
    def __init__(self, n_leads=120, n_deals=7, n_contacts=60, comments_per_lead=0):
        self.data = {
            "lead": {i: {"ID": str(i), "TITLE": f"Лид {i}", "STATUS_ID": "NEW",
                         "PHONE": [{"VALUE": f"+996 555 {i:06d}", "VALUE_TYPE": "WORK"}],
                         "CONTACT_ID": str(i) if i <= n_contacts else None,
                         "DATE_CREATE": "2026-06-01T10:00:00+06:00"}
                     for i in range(1, n_leads + 1)},
            "deal": {i: {"ID": str(i), "TITLE": f"Сделка {i}", "LEAD_ID": str(i),
                         "CONTACT_ID": str(i), "STAGE_ID": "C27:WON", "OPPORTUNITY": "1500",
                         "CURRENCY_ID": "USD"} for i in range(1, n_deals + 1)},
            "contact": {i: {"ID": str(i), "NAME": f"Клиент{i}",
                            "PHONE": [{"VALUE": f"0555{i:06d}"}]} for i in range(1, n_contacts + 1)},
        }
        self.comments = {("lead", i): [{"ID": str(i * 1000 + k), "CREATED": "2026-06-01T10:00",
                                        "COMMENT": f"реплика {k}"} for k in range(comments_per_lead)]
                         for i in range(1, n_leads + 1)}
        self.calls = []
        self.faults = {}         # номер вызова → список (status, body) по очереди
        self.crash_at = None
        self.hook = None         # вызывается перед каждым ответом (сдвиг данных)
        self.dup_in_page = False

    def __call__(self, url, payload):
        method = url.rsplit("/", 1)[-1].removesuffix(".json")
        assert url.startswith(WEBHOOK)
        self.calls.append((method, payload))
        n = len(self.calls)
        if self.crash_at is not None and n == self.crash_at:
            raise Crash()
        queue = self.faults.get(n)
        if queue:
            status, body = queue.pop(0)
            if queue:
                self.faults[n + 1] = queue      # следующая попытка — следующий вызов
            return status, body
        if self.hook:
            self.hook(self, method, payload)
        if method == "crm.timeline.comment.list":
            f = payload["filter"]
            items = self.comments.get((f["ENTITY_TYPE"], int(f["ENTITY_ID"])), [])
            start = int(payload.get("start") or 0)
            page = items[start:start + 50]
            body = {"result": page, "total": len(items)}
            if start + 50 < len(items):
                body["next"] = start + 50
            return 200, body
        kind = {"crm.lead.list": "lead", "crm.deal.list": "deal", "crm.contact.list": "contact"}[method]
        rows = [self.data[kind][k] for k in sorted(self.data[kind])]
        if payload.get("start") == -1:
            last = int(payload["filter"][">ID"])
            page = [r for r in rows if int(r["ID"]) > last][:50]
            if self.dup_in_page and page:
                page = page + [page[0]]
            return 200, {"result": page}
        start = int(payload.get("start") or 0)
        body = {"result": rows[start:start + 50], "total": len(rows)}
        if start + 50 < len(rows):
            body["next"] = start + 50
        return 200, body


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def _run(tmp_path, portal, *args, clock=None, monkeypatch=None):
    clock = clock or Clock()
    out = io.StringIO()
    os.environ["BITRIX24_WEBHOOK_URL"] = WEBHOOK
    try:
        code = exp.run(["--out", str(tmp_path / "arch"), *args], transport=portal,
                       sleep=clock.sleep, clock=clock.now, stdout=out)
    finally:
        os.environ.pop("BITRIX24_WEBHOOK_URL", None)
    return code, out.getvalue(), clock


def _ids(tmp_path, name):
    p = tmp_path / "arch" / name
    if not p.exists():
        return []
    return [int(json.loads(line)["ID"]) for line in p.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------- только чтение / сухой режим ----------------------------

def test_dry_run_counts_and_writes_nothing(tmp_path):
    portal = FakePortal()
    code, text, _ = _run(tmp_path, portal)
    assert code == 0
    assert "СУХОЙ РЕЖИМ" in text and "lead: 120 записей → 3 запросов" in text
    assert "contact: 60 записей" in text and "deal: 7 записей" in text
    assert not (tmp_path / "arch").exists()
    assert len(portal.calls) == 3
    assert all(p["select"] == ["ID"] for _, p in portal.calls)
    assert WEBHOOK not in text and "secret-token" not in text


def test_client_refuses_any_write_method():
    api = exp.ReadOnlyBitrix(base=WEBHOOK, transport=lambda *a: pytest.fail("сеть"),
                             sleep=lambda s: None, clock=lambda: 0.0)
    for method in ("crm.lead.add", "crm.lead.update", "crm.timeline.comment.add",
                   "crm.lead.delete", "imbot.message.add", "batch"):
        with pytest.raises(exp.ForbiddenMethod):
            api.call(method, {})


def test_full_export_uses_only_list_methods_and_secure_files(tmp_path):
    portal = FakePortal(comments_per_lead=2)
    code, text, _ = _run(tmp_path, portal, "--yes")
    assert code == 0, text
    assert {m for m, _ in portal.calls} <= exp.ALLOWED_METHODS
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 121))
    assert _ids(tmp_path, "deals.jsonl") == list(range(1, 8))
    assert _ids(tmp_path, "contacts.jsonl") == list(range(1, 61))
    timeline = [json.loads(l) for l in (tmp_path / "arch" / "timeline.jsonl").read_text().splitlines()]
    assert len(timeline) == 127 and sum(len(t["comments"]) for t in timeline) == 240
    assert stat.S_IMODE(os.stat(tmp_path / "arch").st_mode) == 0o700
    for f in ("leads.jsonl", "timeline.jsonl", "cursor.json"):
        assert stat.S_IMODE(os.stat(tmp_path / "arch" / f).st_mode) == 0o600


def test_second_run_is_a_no_op(tmp_path):
    portal = FakePortal()
    _run(tmp_path, portal, "--yes", "--only", "lead,contact")
    before = (tmp_path / "arch" / "leads.jsonl").read_bytes()
    portal.calls.clear()
    code, _, _ = _run(tmp_path, portal, "--yes", "--only", "lead,contact")
    assert code == 0
    assert (tmp_path / "arch" / "leads.jsonl").read_bytes() == before
    assert len(portal.calls) == 2            # по одной пустой странице на тип


# ---------------------------- обрыв и продолжение ----------------------------

def test_crash_mid_export_then_resume_without_duplicates(tmp_path):
    portal = FakePortal(n_leads=230)
    portal.crash_at = 3                       # третья страница лидов
    with pytest.raises(Crash):
        _run(tmp_path, portal, "--yes", "--only", "lead")
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 101))
    # Обрыв посреди записи строки: хвост без перевода строки.
    with open(tmp_path / "arch" / "leads.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"ID":"101","TITLE":"обрыв')
    portal.crash_at = None
    code, _, _ = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == 0
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 231))


def test_resume_trusts_file_over_stale_cursor(tmp_path):
    portal = FakePortal(n_leads=100)
    _run(tmp_path, portal, "--yes", "--only", "lead", "--limit", "50")
    (tmp_path / "arch" / "cursor.json").write_text("{}")      # курсор потерян
    _run(tmp_path, portal, "--yes", "--only", "lead")
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 101))


def test_timeline_crash_resumes_per_entity(tmp_path):
    portal = FakePortal(n_leads=5, n_deals=0, n_contacts=0, comments_per_lead=120)
    _run(tmp_path, portal, "--yes", "--only", "lead")
    portal.calls.clear()
    portal.crash_at = 5             # посреди второго лида (по 3 страницы на лид)
    with pytest.raises(Crash):
        _run(tmp_path, portal, "--yes", "--only", "timeline")
    portal.crash_at = None
    portal.calls.clear()
    _run(tmp_path, portal, "--yes", "--only", "timeline")
    recs = [json.loads(l) for l in (tmp_path / "arch" / "timeline.jsonl").read_text().splitlines()]
    assert [r["entity_id"] for r in recs] == [1, 2, 3, 4, 5]
    assert all(len(r["comments"]) == 120 for r in recs)
    assert len({c["ID"] for r in recs for c in r["comments"]}) == 600


# ---------------------------- портал сопротивляется ----------------------------

def test_night_403_is_waited_out(tmp_path):
    portal = FakePortal(n_leads=60, n_deals=0, n_contacts=0)
    portal.faults[2] = [(403, {"error": "QUERY_LIMIT_EXCEEDED"})] * 4
    code, text, clock = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == 0, text
    assert [s for s in clock.sleeps if s >= 5] == [5, 15, 30, 60]
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 61))


@pytest.mark.parametrize("status,body", [(429, None), (503, {"error": "OPERATION_TIME_LIMIT"}),
                                         (200, {"error": "QUERY_LIMIT_EXCEEDED"})])
def test_rate_limit_answers_are_retried(tmp_path, status, body):
    portal = FakePortal(n_leads=10, n_deals=0, n_contacts=0)
    portal.faults[1] = [(status, body)]
    code, _, _ = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == 0 and _ids(tmp_path, "leads.jsonl") == list(range(1, 11))


def test_gives_up_keeps_progress_and_resumes_next_morning(tmp_path):
    portal = FakePortal(n_leads=120, n_deals=0, n_contacts=0)
    portal.faults[3] = [(403, {"error": "ACCESS_DENIED"})] * (len(exp.BACKOFF) + 1)
    code, text, clock = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == exp.EXIT_GAVE_UP and "Курсор сохранён" in text
    assert _ids(tmp_path, "leads.jsonl") == list(range(1, 101))
    assert sum(s for s in clock.sleeps if s >= 5) == sum(exp.BACKOFF)
    code, _, _ = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == 0 and _ids(tmp_path, "leads.jsonl") == list(range(1, 121))


def test_bad_webhook_is_not_retried(tmp_path):
    portal = FakePortal()
    portal.faults[1] = [(401, {"error": "INVALID_CREDENTIALS"})]
    code, text, clock = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == exp.EXIT_HTTP and "INVALID_CREDENTIALS" in text
    assert len(portal.calls) == 1 and not [s for s in clock.sleeps if s >= 5]


def test_rps_is_respected(tmp_path):
    portal = FakePortal(n_leads=200, n_deals=0, n_contacts=0)
    code, _, clock = _run(tmp_path, portal, "--yes", "--only", "lead", "--rps", "0.5")
    assert code == 0
    assert len(portal.calls) == 5 and clock.t >= 4 * 2.0       # 5 запросов, шаг 2 с


def test_empty_portal(tmp_path):
    portal = FakePortal(n_leads=0, n_deals=0, n_contacts=0)
    code, text, _ = _run(tmp_path, portal, "--yes")
    assert code == 0
    assert _ids(tmp_path, "leads.jsonl") == []
    assert json.loads((tmp_path / "arch" / "cursor.json").read_text())["lead"]["done"] is True


def test_shifting_pages_give_no_duplicates_and_no_misses(tmp_path):
    """Пока идёт выгрузка, менеджеры заводят и удаляют лиды."""
    portal = FakePortal(n_leads=150, n_deals=0, n_contacts=0)

    def churn(p, method, payload):
        n = len(p.calls)
        if n == 2:
            p.data["lead"].pop(10)                 # удалили уже выгруженный
            p.data["lead"].pop(70)                 # удалили ещё не выгруженный
            p.data["lead"][151] = {"ID": "151", "TITLE": "новый", "PHONE": []}
    portal.hook = churn
    portal.dup_in_page = True                      # и портал отдаёт запись дважды
    code, _, _ = _run(tmp_path, portal, "--yes", "--only", "lead")
    ids = _ids(tmp_path, "leads.jsonl")
    assert code == 0
    assert len(ids) == len(set(ids))
    assert 151 in ids and 70 not in ids and 10 in ids
    assert set(range(1, 152)) - {70} == set(ids)


def test_stale_page_stops_instead_of_silently_finishing(tmp_path):
    portal = FakePortal(n_leads=60, n_deals=0, n_contacts=0)
    calls = {"n": 0}
    real = portal.__call__

    def stale(url, payload):
        calls["n"] += 1
        if calls["n"] == 2:
            return 200, {"result": [portal.data["lead"][1]]}   # только старое
        return real(url, payload)
    code, text, _ = _run(tmp_path, stale, "--yes", "--only", "lead")
    assert code == exp.EXIT_HTTP and "без новых ID" in text
    assert json.loads((tmp_path / "arch" / "cursor.json").read_text())["lead"]["done"] is False


def test_requires_webhook_from_env_and_sane_rps(tmp_path):
    out = io.StringIO()
    assert exp.run(["--out", str(tmp_path / "a")], transport=FakePortal(), stdout=out) == exp.EXIT_USAGE
    os.environ["BITRIX24_WEBHOOK_URL"] = WEBHOOK
    try:
        assert exp.run(["--out", str(tmp_path / "a"), "--rps", "5"], transport=FakePortal(),
                       stdout=out) == exp.EXIT_USAGE
    finally:
        os.environ.pop("BITRIX24_WEBHOOK_URL", None)


# ---------------------------- поиск по архиву ----------------------------

@pytest.fixture
def archive(tmp_path):
    portal = FakePortal(n_leads=12, n_deals=3, n_contacts=10, comments_per_lead=2)
    portal.data["lead"][12]["PHONE"] = [{"VALUE": "+7 701 123 45 67"}]
    code, _, _ = _run(tmp_path, portal, "--yes")
    assert code == 0
    return tmp_path / "arch"


def _search(archive, *args):
    out = io.StringIO()
    code = srch.main(["--dir", str(archive), *args], stdout=out)
    return code, out.getvalue()


@pytest.mark.parametrize("query", ["0555 000 003", "+996555000003", "555000003", "996 (555) 00-00-03"])
def test_search_finds_lead_contact_deal_in_any_format(archive, query):
    code, text = _search(archive, query)
    assert code == 0
    assert "Контакт #3: Клиент3" in text and "Лид #3: Лид 3" in text
    assert "Сделка #3" in text and "1500 USD" in text and "комментариев 2" in text


def test_search_full_prints_comments(archive):
    code, text = _search(archive, "0555000003", "--full")
    assert code == 0 and "реплика 0" in text and "реплика 1" in text


def test_search_foreign_number_exact(archive):
    code, text = _search(archive, "+77011234567")
    assert code == 0 and "Лид #12" in text and "Лид #3" not in text


def test_search_not_found_and_too_short(archive):
    assert _search(archive, "0555999999")[0] == 1
    code, text = _search(archive, "12345")
    assert code == 2 and "не меньше 7 цифр" in text


def test_search_json_and_missing_archive(archive, tmp_path):
    code, text = _search(archive, "0555000004", "--json")
    data = json.loads(text)
    assert code == 0 and [x["ID"] for x in data["leads"]] == ["4"]
    assert srch.main(["--dir", str(tmp_path / "nope"), "0555000004"], stdout=io.StringIO()) == 2


def test_search_survives_truncated_line(archive):
    with open(archive / "leads.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"ID":"99","PHONE":[{"VALUE":"0555000099"')
    assert _search(archive, "0555000003")[0] == 0


# ---------------------------- замечания ревью потока pdf ----------------------------

@pytest.mark.parametrize("url", [
    "https://portal.invalid/rest/1/secret-token/crm.lead.list",     # с именем метода
    "https://portal.invalid/rest/1/secret-token/?auth=x",           # с query
    "http://portal.invalid/rest/1/secret-token/",                   # не https
    "https://portal.invalid/crm/lead/",                             # не вебхук
    "portal.invalid/rest/1/secret-token",                           # без схемы
])
def test_malformed_webhook_is_refused_without_echoing_it(tmp_path, url):
    out = io.StringIO()
    os.environ["BITRIX24_WEBHOOK_URL"] = url
    try:
        code = exp.run(["--out", str(tmp_path / "a")], transport=pytest.fail, stdout=out)
    finally:
        os.environ.pop("BITRIX24_WEBHOOK_URL", None)
    assert code == exp.EXIT_USAGE
    assert "secret-token" not in out.getvalue() and "portal.invalid" not in out.getvalue()


@pytest.mark.parametrize("url", ["https://portal.invalid/rest/1/secret-token",
                                 "https://portal.invalid/rest/155383/abc123def456/",
                                 "http://127.0.0.1:8799/rest/1/fake"])
def test_wellformed_webhooks_pass(url):
    assert exp.webhook_problem(url) == ""


def test_created_parent_dirs_are_private(tmp_path):
    portal = FakePortal(n_leads=3, n_deals=0, n_contacts=0)
    out = io.StringIO()
    os.environ["BITRIX24_WEBHOOK_URL"] = WEBHOOK
    try:
        code = exp.run(["--out", str(tmp_path / "a" / "b" / "c"), "--yes", "--only", "lead"],
                       transport=portal, sleep=lambda s: None, clock=lambda: 0.0, stdout=out)
    finally:
        os.environ.pop("BITRIX24_WEBHOOK_URL", None)
    assert code == 0
    for level in ("a", "a/b", "a/b/c"):
        assert stat.S_IMODE(os.stat(tmp_path / level).st_mode) == 0o700, level


def test_corrupt_line_in_the_middle_stops_with_clear_message(tmp_path):
    portal = FakePortal(n_leads=120, n_deals=0, n_contacts=0)
    _run(tmp_path, portal, "--yes", "--only", "lead", "--limit", "50")
    path = tmp_path / "arch" / "leads.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[10] = '{"ID":"11","TITLE":"битая\n'
    path.write_text("".join(lines), encoding="utf-8")
    before = path.read_bytes()
    code, text, _ = _run(tmp_path, portal, "--yes", "--only", "lead")
    assert code == exp.EXIT_CORRUPT and "leads.jsonl: строка 11 повреждена" in text
    assert path.read_bytes() == before


def test_corrupt_timeline_line_also_stops(tmp_path):
    portal = FakePortal(n_leads=3, n_deals=0, n_contacts=0, comments_per_lead=1)
    _run(tmp_path, portal, "--yes")
    path = tmp_path / "arch" / "timeline.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text(rows[0] + "мусор\n" + "".join(rows[1:]), encoding="utf-8")
    code, text, _ = _run(tmp_path, portal, "--yes", "--only", "timeline")
    assert code == exp.EXIT_CORRUPT and "timeline.jsonl: строка 2" in text
