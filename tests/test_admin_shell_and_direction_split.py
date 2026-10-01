"""ГЕЙТ M1: единый каркас админки + разделение направлений (туры / визы).

Написан ДО реализации и исполнителем НЕ редактируется.

Зачем. Панель становится рабочим местом менеджеров (ТЗ 01.10, заявлен отказ от Bitrix),
а каркаса в ней нет вообще: 10 страниц — 10 самостоятельных `<!doctype html>` со своим
`<head>`, своим `:root` и своим топбаром. Отсюда 5 вариантов плитки-числа, 7 вариантов
бейджа, 6 вариантов кнопки и битая ссылка `/admin/boards`, которой нет в роутах.

Второе требование Алана 01.10 дословно: «лучше разделить туры и визы, невозможно читать».
Разделение опирается на СУЩЕСТВУЮЩИЙ `manager_scope.bot_scope_for`, новых правил доступа
не вводим: менеджер видит только своё направление и переключателя не имеет, полный админ
переключает направление явно, и выбор запоминается в сессии.

Контракт направления, который фиксирует этот гейт:
  POST /admin/direction  (form: direction=visa|tours|tickets)
    - полный админ: принимается, запоминается в сессии, доска отдаёт это направление;
    - менеджер со скоупом: 403, направление остаётся его собственным;
    - неизвестное значение: 400.
"""
import asyncio
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

TEMPLATES = Path(admin_router.__file__).parent / "templates"
SHELL = "base.html"

VISA_USER = "getvisa:996700111111"
TOUR_USER = "frunze_tours:996700222222"
TOUR_TEXT = "хочу тур в Турцию"
VISA_TEXT = "нужна виза в США"


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _seed_both():
    """Один визовый лид и один туровый — чтобы проверять именно разделение."""
    store = get_conversation_store()

    async def _s():
        await store.add_message(VISA_USER, "client", VISA_TEXT, channel="whatsapp",
                                bot_id="getvisa", phone="996700111111")
        await store.update_meta(VISA_USER, funnel="visa")
        await store.add_message(TOUR_USER, "client", TOUR_TEXT, channel="whatsapp",
                                bot_id="frunze_tours", phone="996700222222")
        await store.update_meta(TOUR_USER, funnel="tours")
    asyncio.run(_s())


def _managers(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login="medina", name="Медина", password="pw"),   # скоуп getvisa
        ManagerConfig(login="ademi", name="Адеми", password="pw"),     # скоуп frunze_tours
    ], raising=False)


def _login(login, password):
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": login, "password": password}).status_code == 200
    return client


def _static_get_paths():
    """GET-роуты админки без параметров пути."""
    out = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.startswith("/admin") and "GET" in methods and "{" not in path:
            out.append(path)
    return sorted(set(out))


def _template_files():
    return sorted(TEMPLATES.glob("*.html"))


def _pages():
    return [p for p in _template_files() if p.name != SHELL and not p.name.startswith("_")]


# --- A. Каркас: одна оболочка на всю панель ---------------------------------

def test_shell_template_exists():
    assert (TEMPLATES / SHELL).is_file(), "нет единой оболочки base.html"


def test_doctype_is_declared_only_in_the_shell():
    """10 самостоятельных <!doctype> — это и есть отсутствие каркаса."""
    offenders = [p.name for p in _template_files()
                 if p.name != SHELL and "<!doctype" in p.read_text(encoding="utf-8").lower()]
    assert offenders == [], "страницы объявляют свой документ вместо extends: %s" % offenders


def test_design_tokens_live_only_in_the_shell():
    """:root в каждом файле = расползание палитры (5 плиток, 7 бейджей, 6 кнопок)."""
    offenders = [p.name for p in _template_files()
                 if p.name != SHELL and ":root" in p.read_text(encoding="utf-8")]
    assert offenders == [], "свои токены вне оболочки: %s" % offenders


def test_fonts_are_loaded_once():
    offenders = [p.name for p in _template_files()
                 if p.name != SHELL and "fonts.googleapis.com" in p.read_text(encoding="utf-8")]
    assert offenders == [], "шрифты грузятся повторно: %s" % offenders


def test_pages_extend_the_shell():
    missing = [p.name for p in _pages() if "{% extends" not in p.read_text(encoding="utf-8")]
    assert missing == [], "страницы без extends: %s" % missing


def test_dead_turquoise_fallbacks_are_gone():
    """Остатки прежней бирюзовой темы в фолбэках переменных."""
    bad = [p.name for p in _template_files() if "#00767d" in p.read_text(encoding="utf-8")]
    assert bad == [], "мёртвая бирюза: %s" % bad


def test_brand_token_is_declared_in_the_shell():
    """`var(--brand)` раньше нигде не объявлялась и молча падала в фолбэк.
    Запрещать её использование неверно — токен должен существовать в одном месте."""
    shell = (TEMPLATES / SHELL).read_text(encoding="utf-8")
    assert "--brand:" in shell and "--brand-soft:" in shell
    with_fallback = [p.name for p in _template_files()
                     if re.search(r"var\(--brand(-soft)?\s*,", p.read_text(encoding="utf-8"))]
    assert with_fallback == [], "токен подстрахован фолбэком, значит не уверены в нём: %s" % with_fallback


def test_internal_links_point_to_existing_routes():
    """Ловит cards.html -> /admin/boards, которого в роутах нет."""
    known = {k.rstrip("/") for k in _static_get_paths()} | {"/admin"}
    broken = []
    for p in _template_files():
        for href in re.findall(r'href="(/admin[^"?#]*)"', p.read_text(encoding="utf-8")):
            if "{" in href:
                continue
            if href.rstrip("/") not in known:
                broken.append(p.name + " -> " + href)
    assert broken == [], "битые ссылки: %s" % broken


# --- B. Каркас не ломает существующие страницы ------------------------------

def test_every_page_answers_for_full_admin(monkeypatch):
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("admin", "frunze")
    bad = {}
    for path in _static_get_paths():
        if path.endswith("/login"):
            continue
        code = client.get(path).status_code
        if code != 200:
            bad[path] = code
    assert bad == {}, "страницы не отвечают полному админу: %s" % bad


def test_every_page_answers_or_forbids_for_scoped_manager(monkeypatch):
    """Менеджеру — 200 или честный 403. Пятисотки недопустимы."""
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("medina", "pw")
    bad = {}
    for path in _static_get_paths():
        if path.endswith("/login"):
            continue
        code = client.get(path).status_code
        if code not in (200, 403):
            bad[path] = code
    assert bad == {}, "неожиданные ответы менеджеру: %s" % bad


# --- C. Разделение направлений ----------------------------------------------

def test_visa_manager_does_not_see_tour_leads_on_the_board(monkeypatch):
    """Проверять `/admin` бессмысленно: он отдаёт пустой `#board`, а карточки грузит
    htmx (`boards.html`: hx-trigger="load" -> /admin/inbox). Такая проверка была бы
    зелёной всегда и не доказывала ничего. Спрашиваем тот эндпоинт, где есть данные."""
    _clear(); _managers(monkeypatch); _seed_both()
    body = _login("medina", "pw").get("/admin/board/tours").text
    assert TOUR_TEXT not in body, "визовый менеджер видит туровый лид на доске"


def test_visa_manager_does_not_see_tour_leads_in_inbox(monkeypatch):
    _clear(); _managers(monkeypatch); _seed_both()
    body = _login("medina", "pw").get("/admin/inbox").text
    assert TOUR_TEXT not in body, "туровый лид протёк в инбокс визового менеджера"


def test_visa_manager_does_not_see_tour_leads_in_search(monkeypatch):
    """Искать сам номер нельзя: шаблон печатает запрос в заголовке
    (`_attention.html`: «Поиск: «{{ query }}»»), и проверка поймала бы свою же строку.
    Признак утечки — текст чужого лида и непустая выдача."""
    _clear(); _managers(monkeypatch); _seed_both()
    body = _login("medina", "pw").get("/admin/search", params={"q": "996700222222"}).text
    assert TOUR_TEXT not in body, "поиск отдал чужое направление"
    assert "— 0" in body, "поиск нашёл чужой лид: выдача не пуста"


def test_tour_manager_does_not_see_visa_leads(monkeypatch):
    """Симметрия: дыра в обе стороны одинаково опасна."""
    _clear(); _managers(monkeypatch); _seed_both()
    body = _login("ademi", "pw").get("/admin/board/visa").text
    assert VISA_TEXT not in body, "туровый менеджер видит визовый лид"


def test_counters_are_scoped_to_the_direction(monkeypatch):
    """/admin/stats кормит бейдж и звук — он тоже обязан считать только своё."""
    _clear(); _managers(monkeypatch); _seed_both()
    mine = _login("medina", "pw").get("/admin/stats").json()
    everything = _login("admin", "frunze").get("/admin/stats").json()
    assert mine != everything, "счётчики менеджера совпали с общими — скоуп не применён"


def test_manager_has_no_direction_switcher(monkeypatch):
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("medina", "pw")
    assert 'action="/admin/direction"' not in client.get("/admin").text
    assert client.post("/admin/direction", data={"direction": "tours"}).status_code == 403


def test_full_admin_switches_direction_and_it_is_remembered(monkeypatch):
    """Содержимое смотрим в `/admin/inbox` — это то, что htmx грузит в доску по загрузке.
    Выбор обязан переживать отдельный запрос, то есть лежать в сессии, а не в URL."""
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("admin", "frunze")

    assert client.post("/admin/direction", data={"direction": "tours"},
                       follow_redirects=False).status_code in (200, 204, 303)
    assert 'action="/admin/direction"' in client.get("/admin").text, "нет переключателя у админа"
    tours = client.get("/admin/inbox").text
    assert TOUR_TEXT in tours and VISA_TEXT not in tours, "направление «туры» не применилось"

    assert client.post("/admin/direction", data={"direction": "visa"},
                       follow_redirects=False).status_code in (200, 204, 303)
    visa = client.get("/admin/inbox").text
    assert VISA_TEXT in visa and TOUR_TEXT not in visa, "направление «визы» не применилось"


def test_unknown_direction_is_rejected(monkeypatch):
    _clear(); _managers(monkeypatch)
    client = _login("admin", "frunze")
    assert client.post("/admin/direction", data={"direction": "ломаем"}).status_code == 400


# --- D. Регрессия: поведение доски не изменилось ----------------------------

def test_manual_stage_move_still_works(monkeypatch):
    """Ручной перенос менеджера главнее бота — правило не должно пострадать."""
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("admin", "frunze")
    assert client.post("/admin/conversation/%s/stage" % VISA_USER,
                       data={"stage": "office"}).status_code == 200

    async def _read():
        return await get_conversation_store().get(VISA_USER)
    assert asyncio.run(_read()).stage == "office"


def test_silent_column_is_still_refused(monkeypatch):
    """«Молчат» вычисляется, а не хранится — перенос туда по-прежнему 400."""
    _clear(); _managers(monkeypatch); _seed_both()
    client = _login("admin", "frunze")
    assert client.post("/admin/conversation/%s/stage" % VISA_USER,
                       data={"stage": "silent"}).status_code == 400
