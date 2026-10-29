"""Поток ux, 3-й заход (30.10.2026, на интеграции): замечания ревью потока bitrix и PM.

1. Админ в простом режиме на диалоге, который закреплён за менеджером, но не перехвачен,
   не видел ни «Взять себе», ни «Перехватить» (ревью bitrix, NEEDS_HUMAN_DECISION низкое).
2. В «Напомнить» нельзя было отметить «Важно».
3. Поиск в «Диалогах» не срабатывал на вставленный номер: триггер `keyup` не приходит
   при вставке мышью или долгим нажатием на телефоне (приёмка PM).
"""
import re

from test_panel_simple_manager_day import VISA, _client, _seed, _setup


def _strip(page: str) -> str:
    return re.search(r'<div class="chat-who.*?</details>', page, flags=re.S).group(0)


def test_admin_can_take_a_client_pinned_to_a_manager(monkeypatch):
    _setup(monkeypatch); _seed(assigned_to="medina", intercepted=False)
    strip = _strip(_client("admin", "frunze").get(f"/admin/conversation/{VISA}").text)
    assert "Клиента ведёт Медина" in strip
    assert f'hx-post="/admin/conversation/{VISA}/takeover"' in strip and "Взять себе" in strip


def test_manager_still_has_no_takeover_on_a_colleagues_client(monkeypatch):
    _setup(monkeypatch); _seed(assigned_to="eliza", intercepted=False)
    strip = _strip(_client().get(f"/admin/conversation/{VISA}").text)
    assert "/takeover" not in strip and "/release" not in strip


def test_remind_can_be_marked_important_and_default_stays_server_side(monkeypatch):
    _setup(monkeypatch); _seed()
    page = _client().get(f"/admin/conversation/{VISA}").text
    form = re.search(r'<form class="chat-remind-form".*?</form>', page, flags=re.S).group(0)
    assert re.findall(r'name="priority"[^>]*', form) == ['name="priority" value="high"'], \
        "одна галочка «Важно»; без неё поле не уходит и сервер ставит normal"
    assert 'type="checkbox" name="priority" value="high"' in form and "Важно" in form


def test_search_fires_on_paste_not_only_on_keyup(monkeypatch):
    for simple in (True, False):
        _setup(monkeypatch, simple=simple)
        page = _client().get("/admin").text
        tag = re.search(r'<input type="search" name="q"[^>]*>', page, flags=re.S).group(0)
        assert 'hx-trigger="input changed delay:300ms, search"' in tag, tag


# ---------------- экраны потока bitrix в простом режиме (только вид) ----------------
import app.config  # noqa: E402
import test_admin_clients as tc  # noqa: E402
import test_admin_workday as tw  # noqa: E402
from test_admin_clients import env as clients_env  # noqa: E402,F401
import app.admin.router as admin_router  # noqa: E402


def _simple(monkeypatch, on=True):
    monkeypatch.setattr(app.config.settings, "panel_simple_mode_enabled", on, raising=False)
    admin_router._look_cache["key"] = None


def test_new_client_is_a_button_in_dialogs_not_a_sixth_nav_item(clients_env, monkeypatch):  # noqa: F811
    _simple(monkeypatch)
    tc._on("panel_manual_lead_enabled")
    page = tc._client("medina").get("/admin").text
    nav = re.search(r'<nav class="main-nav".*?</nav>', page, flags=re.S).group(0)
    assert "/admin/clients/new" not in nav
    assert '<a class="tab new-client" href="/admin/clients/new">' in page
    # Админ и выключенный простой режим — как сделал поток bitrix: пункт в меню.
    _simple(monkeypatch, False)
    plain = tc._client("medina").get("/admin").text
    assert "/admin/clients/new" in re.search(r'<nav class="main-nav".*?</nav>', plain, flags=re.S).group(0)


def test_client_card_speaks_plainly_in_simple_mode(clients_env, monkeypatch):  # noqa: F811
    _simple(monkeypatch)
    tc._on("panel_client_card_enabled")
    tc._seed(tc.VISA_UID, owner="medina", name="Асель")
    card = tc._client("medina").get(f"/admin/client/{tc.PHONE}").text
    assert "+996 555 12 34 56" in card and "getvisa ·" not in card and "· getvisa" not in card
    assert "Договоры (0)" in card and "Открыть переписку" in card and "ничей" not in card
    chat = tc._client("medina").get(f"/admin/conversation/{tc.VISA_UID}").text
    menu = re.search(r'<details class="chat-menu".*?</details>', chat, flags=re.S).group(0)
    assert f"/admin/client/{tc.PHONE}" in menu, "карточка клиента — в меню ⋮"
    notes = chat.split('<details class="chat-dossier chat-notes"')[1].split("</details>")[0]
    assert "/admin/client/" not in notes and "Заметки для коллег" in notes


def test_case_card_shows_bishkek_time_and_a_pay_button(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    tw._clear(); tw._managers(monkeypatch); tw._on(monkeypatch)
    sm = tw._make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = tw._seed_case(sm, reference="UX2-T", task_at=datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc))
    _simple(monkeypatch)
    page = tw._login(tw.MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}").text
    assert "02.11 10:30" in page and "время Бишкека" in page, "04:30 UTC = 10:30 Бишкек"
    assert "UTC" not in page.split('id="case-panel"')[1].split("</main>")[0]
    assert 'href="?tab=money#pay"' in page and "Внести оплату" in page
    assert "пояснение, не запрет" not in page and "Дальше:" in page
    money = tw._login(tw.MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}?tab=money").text
    assert 'href="?tab=money#pay"' not in money and 'id="pay-sheet"' in money, \
        "во вкладке «Деньги» одна кнопка «Внести оплату», не две" 
    _simple(monkeypatch, False)
    plain = tw._login(tw.MANAGER_LOGIN).get(f"/admin/case/{case['case_id']}").text
    assert "ближайшая задача · UTC" in plain and 'href="?tab=money#pay"' not in plain


# ---------------- ревью потока pdf 30.10, раздел 2 ----------------
def _case_with_usd_payment(monkeypatch, tmp_path):
    tw._clear(); tw._managers(monkeypatch); tw._on(monkeypatch)
    sm = tw._make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = tw._seed_case(sm, reference="UX2-USD", amount="250.00")
    client = tw._login(tw.MANAGER_LOGIN)
    r = client.post(f"/admin/case/{case['case_id']}/money/payment",
                    data={"amount": "5.00", "currency": "USD", "idempotency_key": "ux2-usd-1"})
    assert r.headers.get("X-Action-Outcome") == "recorded"
    return case, client


def test_unconverted_payment_is_flagged_next_to_the_pay_button(monkeypatch, tmp_path):
    _simple(monkeypatch)
    case, client = _case_with_usd_payment(monkeypatch, tmp_path)
    page = client.get(f"/admin/case/{case['case_id']}?tab=path").text
    cta = page.index('href="?tab=money#pay"')
    note = page.index("Есть незачтённая оплата 5.00 USD")
    assert 0 < note - cta < 600, "пометка стоит рядом с кнопкой «Внести оплату»"


def test_money_times_say_bishkek_and_form_comes_first_in_the_dom(monkeypatch, tmp_path):
    _simple(monkeypatch)
    case, client = _case_with_usd_payment(monkeypatch, tmp_path)
    money = client.get(f"/admin/case/{case['case_id']}?tab=money").text
    assert "по Бишкеку · записал(а)" in money
    ops = money.split('class="cs-ops"')[1]
    assert "Оплата записана" in ops and "Оплата зачтена" not in ops, "платёж без курса не зачтён"

    path = client.get(f"/admin/case/{case['case_id']}?tab=path").text
    assert "История договора · время по Бишкеку" in path
    pane = money.split('id="pane-money"')[1].split('id="pane-tasks"')[0]
    assert pane.index('id="pay-sheet"') < pane.index("Оплаты и возвраты") < pane.index('class="cs-ops"'), \
        "простой режим: форма оплаты под суммами и в разметке, не только визуально"
    _simple(monkeypatch, False)
    plain = client.get(f"/admin/case/{case['case_id']}?tab=money").text.split('id="pane-money"')[1]
    assert plain.index('class="cs-ops"') < plain.index('id="pay-sheet"'), "без простого режима — как было"
