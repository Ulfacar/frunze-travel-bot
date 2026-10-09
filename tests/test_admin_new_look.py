"""ГЕЙТ: новый визуальный язык панели за тумблером `admin_new_look_enabled`.

Написан ДО реализации и исполнителем НЕ редактируется.

Зачем. Требование Алана 02.10.2026 дословно: «редизайн — всё менять там, но чтобы
функционал тот же был». Опасность ровно в этом «но»: перекраска десяти экранов — самый
лёгкий способ незаметно потерять кнопку, ссылку или целый раздел. Поэтому гейт проверяет
не красоту (её тестом не поймать), а две вещи, которые красотой ломаются:

1. **Функционал не уменьшился.** Те же страницы отвечают, те же разделы в шапке, те же
   действия на доске, те же классы, на которые завязаны htmx и скрипты.
2. **Откат мгновенный.** Тумблер OFF отдаёт прежний вид дословно: тот же шрифт, та же
   палитра, тот же набор правил. Выключение не должно требовать выкатки.

Третье, что здесь закреплено, — корректность самой тёмной темы. Токен, объявленный
ТОЛЬКО внутри `@media (prefers-color-scheme: dark)` или `[data-theme]`, не существует для
посетителя с системной светлой темой, и экран показывает текст одной темы на фоне другой.
Это классическая ошибка, и ловится она только проверкой каскада.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store

TEMPLATES = Path(admin_router.__file__).parent / "templates"
SHELL = (TEMPLATES / "base.html")
BOARDS = (TEMPLATES / "boards.html")
FLAG = "admin_new_look_enabled"

# Классы и крючки, на которых держится поведение панели. Перекраска не имеет права
# переименовать ни один: по ним ходят htmx-запросы, drag-and-drop и обработчики кликов.
LOAD_BEARING = [
    "topbar", "brand", "tabs", "tab", "spacer", "nav-link", "me", "search",
    "panel", "btn", "btn-ghost", "btn-danger", "btn-brand", "badge", "tag",
    "board", "col", "card", "card-top", "card-foot", "inbox-list", "composer",
    "card-archive", "card-select", "bulk-checkbox", "msgs", "bubble",
]

NAV_LINKS = ["/admin", "/admin/buyers", "/admin/morning", "/admin/calendar",
             "/admin/faq", "/admin/analytics", "/admin/cards", "/admin/system", "/admin/audit"]


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch):
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
    ], raising=False)


def _look(monkeypatch, on: bool):
    monkeypatch.setattr(app.config.settings, FLAG, on, raising=False)


def _login():
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "admin", "password": "frunze"}).status_code == 200
    return client


# За тумблером — штатный 404, пока флаг выключен (экран «Фокус», 03.10).
FLAGGED_PATHS = {"/admin/focus", "/admin/work", "/admin/work/list",
                 "/admin/work/claims", "/admin/kg-entry/knowledge"}
# E5-01C: новая страница поиска тоже OFF по умолчанию. Её включённый экран,
# 404 до чтения источника и ограничения ролей проверяет test_admin_kg_knowledge.py.
# Исключение из «все страницы отвечают 200» не должно прятать регрессию:
# при ВКЛЮЧЁННОМ тумблере такая страница обязана отвечать (находка ревью 03.10).


def _pages():
    out = []
    for route in main.app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set()) or set()
        if path.startswith("/admin") and "GET" in methods and "{" not in path \
                and not path.endswith("/login") and path not in FLAGGED_PATHS:
            out.append(path)
    return sorted(set(out))


def _css_blocks(css: str, header: str) -> list[str]:
    """Тела всех блоков `header { … }` с учётом вложенности."""
    out, i = [], 0
    while True:
        start = css.find(header, i)
        if start == -1:
            return out
        open_brace = css.index("{", start)
        # Селектор должен совпасть ЦЕЛИКОМ. Правка гейта 02.10: прежний разбор принимал
        # `:root:not([data-theme="light"]) .theme-toggle .moon` за блок токенов и требовал
        # `color-scheme` внутри него — ломалось моё утверждение о разборе, не требование.
        if css[start + len(header):open_brace].strip():
            i = open_brace
            continue
        depth, j = 0, open_brace
        while j < len(css):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(css[open_brace + 1:j])
        i = j + 1


# --- A. Функционал не уменьшился ---------------------------------------------

def test_every_page_answers_with_the_new_look(monkeypatch):
    _clear(); _managers(monkeypatch); _look(monkeypatch, True)
    client = _login()
    bad = {p: client.get(p).status_code for p in _pages()
           if client.get(p).status_code != 200}
    assert bad == {}, f"с новым видом страницы перестали отвечать: {bad}"


def test_all_nav_links_survive_the_redesign(monkeypatch):
    """Девять разделов. Спрятать их за «ещё» можно, потерять — нет."""
    _clear(); _managers(monkeypatch); _look(monkeypatch, True)
    body = _login().get("/admin").text
    missing = [href for href in NAV_LINKS if f'href="{href}"' not in body]
    assert missing == [], f"из шапки пропали разделы: {missing}"


def test_load_bearing_classes_are_not_renamed():
    """htmx, drag-and-drop и обработчики кликов ходят по этим классам."""
    css = SHELL.read_text(encoding="utf-8") + BOARDS.read_text(encoding="utf-8")
    missing = [c for c in LOAD_BEARING if f".{c}" not in css]
    assert missing == [], f"перекраска переименовала рабочие классы: {missing}"


def test_board_actions_are_still_on_the_page(monkeypatch):
    """Кнопки доски — те же самые, с теми же обработчиками."""
    _clear(); _managers(monkeypatch); _look(monkeypatch, True)
    body = _login().get("/admin").text
    for hook in ("toggleNoise(", "selectVisibleInboxCards(", "archiveSelectedInbox(",
                 "archiveNoiseInbox(", "closeChatSheet(", "initBoardDnD"):
        assert hook in body, f"с доски пропал обработчик {hook}"


def test_shell_still_wraps_every_page(monkeypatch):
    """Каркас M1 не разъехался: ровно один документ и одна шапка на странице."""
    _clear(); _managers(monkeypatch); _look(monkeypatch, True)
    client = _login()
    for path in _pages():
        body = client.get(path).text
        if "<html" not in body:
            continue                      # htmx-фрагмент или JSON — не страница
        assert body.count("<html") == 1, f"{path}: не один документ"
        assert body.count('class="topbar"') == 1, f"{path}: не одна шапка"


# --- B. Откат мгновенный ------------------------------------------------------

def test_flag_off_renders_exactly_the_old_look(monkeypatch):
    _clear(); _managers(monkeypatch); _look(monkeypatch, False)
    body = _login().get("/admin").text
    assert "Fira Sans" in body, "при выключенном тумблере сменился шрифт"
    assert "#2563EB" in body, "при выключенном тумблере сменилась палитра"


def test_flag_on_actually_changes_the_look(monkeypatch):
    """Проверка от обратного: тумблер обязан что-то менять, иначе он бутафория."""
    _clear(); _managers(monkeypatch)
    _look(monkeypatch, False)
    old = _login().get("/admin").text
    _look(monkeypatch, True)
    new = _login().get("/admin").text
    assert old != new, "тумблер включён, а разметка не изменилась"


def test_flag_defaults_to_off():
    assert app.config.settings.admin_new_look_enabled is False


def test_flag_is_switchable_without_deploy():
    assert FLAG in admin_router.FEATURE_FLAGS


# --- C. Тёмная тема объявлена правильно --------------------------------------
#
# Все проверки ниже смотрят на ОТРЕНДЕРЕННУЮ страницу, а не на файл шаблона. Первая
# версия этого гейта читала `base.html` с диска и потому была вакуумной: текст внутри
# `{% if new_look %}` лежит в файле всегда, и подмена условия на `False` теста не роняла.
# Поймано проверкой вакуумности 02.10 — гейт ужесточён.

def _rendered(monkeypatch, on: bool) -> str:
    _clear(); _managers(monkeypatch); _look(monkeypatch, on)
    return _login().get("/admin").text


def test_dark_theme_reaches_the_page(monkeypatch):
    css = _rendered(monkeypatch, True)
    assert "prefers-color-scheme: dark" in css, "тёмной темы нет на странице"
    assert '[data-theme="dark"]' in css, "нет явного переключателя темы"


def test_old_look_has_no_dark_theme(monkeypatch):
    """Прежний вид тёмной темы не знал — тумблер OFF не должен её приносить."""
    assert '[data-theme="dark"]' not in _rendered(monkeypatch, False)


def test_dark_theme_only_redefines_tokens_declared_in_root(monkeypatch):
    """Токен, живущий только внутри тёмного блока, для светлой системы не существует —
    и экран показывает текст одной темы на фоне другой."""
    css = _rendered(monkeypatch, True)
    root = chr(10).join(_css_blocks(css, ":root {"))
    declared = set(re.findall(r"(--[\w-]+)\s*:", root))
    dark = chr(10).join(_css_blocks(css, ':root[data-theme="dark"]')
                     + _css_blocks(css, ':root:not([data-theme="light"])'))
    only_dark = {t for t in re.findall(r"(--[\w-]+)\s*:", dark)} - declared
    assert only_dark == set(), f"токены объявлены только в тёмной теме: {sorted(only_dark)}"


def test_explicit_choice_beats_the_system_theme(monkeypatch):
    """Светлая, выбранная руками, обязана перебивать тёмную системную.

    Проверяем именно БЛОК ТОКЕНОВ: тот же селектор встречается у мелких правил вроде
    `.theme-toggle .moon`, и поиска по подстроке мало — это поймала проверка вакуумности.
    """
    css = _rendered(monkeypatch, True)
    guarded = [b for b in _css_blocks(css, ':root:not([data-theme="light"])') if "--bg:" in b]
    assert guarded, "нет защищённого медиа-блока с токенами тёмной темы"


def test_dark_blocks_set_color_scheme(monkeypatch):
    """Без `color-scheme: dark` поля ввода и полосы прокрутки остаются светлыми."""
    css = _rendered(monkeypatch, True)
    blocks = (_css_blocks(css, ':root[data-theme="dark"]')
              + _css_blocks(css, ':root:not([data-theme="light"])'))
    assert blocks, "тёмных блоков на странице не нашлось вовсе"
    for block in blocks:
        assert "color-scheme: dark" in block, "в тёмном блоке нет color-scheme: dark"


def test_theme_choice_survives_reload(monkeypatch):
    """Выбор темы менеджер делает один раз, а не каждое утро."""
    page = _rendered(monkeypatch, True)
    assert "localStorage.getItem('frunze-theme')" in page, "тема не читается при загрузке"
    assert "localStorage.setItem('frunze-theme'" in page, "выбор темы не сохраняется"
    assert 'class="theme-toggle"' in page, "кнопки переключения темы нет в шапке"
    assert "function toggleTheme()" in page, "обработчик переключения темы не объявлен"


def test_new_palette_actually_reaches_the_page(monkeypatch):
    """Самое простое и самое важное: включённый тумблер меняет палитру и шрифт."""
    new = _rendered(monkeypatch, True)
    assert "#0E7C86" in new, "бирюза не доехала до страницы"
    assert "family=Onest" in new, "новый шрифт не подключился"
    # Ищем ПРИМЕНЁННЫЙ шрифт, а не слово в комментарии: правка гейта 02.10 — упоминание
    # «Fira Sans» законно остаётся в комментарии, описывающем прежний вид.
    assert "font-family: 'Onest'" in new, "body не переведён на новый шрифт"
    assert "font-family: 'Fira Sans'" not in new, "старый шрифт остался применённым"
    assert "family=Fira" not in new, "старый шрифт всё ещё загружается"
