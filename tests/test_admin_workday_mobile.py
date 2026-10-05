"""E2-06 — телефон 360 px и дисциплина цветов (часть AC-34).

Проверки идут по ОТРЕНДЕРЕННОМУ ответу, а не по файлу шаблона: гейт, читающий
шаблон с диска, не заметит, если разметку обернут в `{% if False %}`.

Отдельная цель — не повторить ошибку `calendar.html`, где цвета захардкожены
литеральными хексами и в тёмной теме не адаптируются.
"""
from __future__ import annotations

import re

import pytest

from tests.test_admin_workday import (
    MANAGER_LOGIN, WORK, Rendered, _clear, _login, _make_domain_sm, _managers,
    _on, _seed_case,
)
import app.admin.router as admin_router

PHONE = "max-width: 760px"
NARROW = "max-width: 480px"
# Три фоллбэка допустимы: токенов --on-accent/--on-hot нет вне new_look.
ALLOWED_HEX = {"#fff", "#ffffff"}


def _styles(html: str) -> str:
    """Собрать весь CSS страницы: он приходит внутри ответа, а не из файла."""
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S))


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _media_block(css: str, condition: str) -> str:
    """Тело @media с учётом вложенных скобок."""
    out: list[str] = []
    for match in re.finditer(r"@media[^{]*" + re.escape(condition) + r"[^{]*\{", css):
        depth, index = 1, match.end()
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        out.append(css[match.end():index - 1])
    return "\n".join(out)


def _page(monkeypatch, tmp_path, url=WORK, *, with_case=False) -> str:
    _clear(); _managers(monkeypatch); _on(monkeypatch)
    sm = _make_domain_sm(tmp_path)
    monkeypatch.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    case = _seed_case(sm, reference="M-1") if with_case else {}
    target = url.format(case_id=case.get("case_id", 1)) if "{" in url else url
    return _login(MANAGER_LOGIN).get(target).text


NEW_TEMPLATES = ("work.html", "_work_list.html", "_work_claims.html",
                 "case.html", "_case_panel.html")


@pytest.mark.parametrize("name", NEW_TEMPLATES)
def test_no_literal_hex_colors_in_the_new_templates(name):
    """Цвета только токенами: иначе тёмная тема не адаптируется.

    Проверяется ФАЙЛ, а не рендер, и это осознанное исключение: в отрендеренной
    странице есть `base.html`, где токены и обязаны задаваться хексами. Здесь мы
    проверяем дисциплину автора нового шаблона — не захардкодил ли он цвет.
    В `calendar.html` захардкожены #DBEAFE, #B91C1C и ещё десяток, и там это уже
    болит: тёмная тема их не адаптирует.
    """
    from pathlib import Path
    path = Path("app/admin/templates") / name
    if not path.exists():
        pytest.skip(f"{name} ещё не создан")
    css = _strip_comments(path.read_text(encoding="utf-8"))
    hexes = {h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,8}\b", css)}
    assert hexes <= ALLOWED_HEX, f"{name}: литеральные цвета {sorted(hexes - ALLOWED_HEX)}"


def test_the_phone_breakpoint_exists_and_collapses_the_layout(monkeypatch, tmp_path):
    """На телефоне раскладка складывается, а не прокручивается боком."""
    css = _strip_comments(_styles(_page(monkeypatch, tmp_path)))
    phone = _media_block(css, PHONE) + "\n" + _media_block(css, NARROW)
    assert phone.strip(), "нет телефонной ветки @media"
    # Складывается любым из принятых способов: сетка в одну колонку, колоночный
    # flex или элемент на всю ширину строки.
    collapsed = (re.search(r"grid-template-columns\s*:\s*(1fr|none|repeat\(\s*1)", phone)
                 or re.search(r"flex-direction\s*:\s*column", phone)
                 or re.search(r"width\s*:\s*100%", phone))
    assert collapsed, "на телефоне раскладка не складывается"


def test_on_accent_tokens_are_used_with_a_fallback(monkeypatch, tmp_path):
    """`--on-accent` существует только при new_look — всегда с фоллбэком."""
    css = _styles(_page(monkeypatch, tmp_path))
    for token in ("--on-accent", "--on-hot"):
        for use in re.findall(r"var\(" + token + r"[^)]*\)", css):
            assert "," in use, f"{token} без фоллбэка: {use}"


def test_flex_rows_declare_min_width_zero(monkeypatch, tmp_path):
    """`min-width: 0` обязателен: длинный номер иначе растягивает всю страницу."""
    css = _strip_comments(_styles(_page(monkeypatch, tmp_path)))
    assert re.search(r"min-width\s*:\s*0", css), "нет min-width: 0 у flex-контейнеров"


def test_long_values_are_allowed_to_break(monkeypatch, tmp_path):
    """Номер договора и брони обязаны переноситься, а не распирать строку."""
    css = _strip_comments(_styles(_page(monkeypatch, tmp_path)))
    assert re.search(r"overflow-wrap\s*:\s*(anywhere|break-word)", css) or \
        re.search(r"word-break\s*:\s*break-\w+", css), \
        "длинные значения не переносятся"


def test_actions_are_tappable(monkeypatch, tmp_path):
    """Кнопки пальцем: минимальная высота объявлена."""
    css = _strip_comments(_styles(_page(monkeypatch, tmp_path)))
    assert re.search(r"min-height\s*:\s*4[0-9]px", css), \
        "у кнопок не объявлена высота под палец"


def test_reduced_motion_is_respected(monkeypatch, tmp_path):
    """Анимации гасятся, если человек их отключил."""
    html = _page(monkeypatch, tmp_path)
    assert "prefers-reduced-motion" in html


def test_the_page_has_no_horizontal_scroll_container_on_the_whole_body(
        monkeypatch, tmp_path):
    """Боковая прокрутка допустима только у полосы вкладок, не у страницы."""
    css = _strip_comments(_styles(_page(monkeypatch, tmp_path)))
    for match in re.finditer(r"([^{}]+)\{([^{}]*overflow-x\s*:\s*auto[^{}]*)\}", css):
        selector = match.group(1).strip()
        assert not re.search(r"\b(body|html)\b", selector), \
            f"боковая прокрутка у страницы: {selector}"


def test_filters_are_keyboard_reachable(monkeypatch, tmp_path):
    """Фильтры — настоящие кнопки с ролями, а не div с обработчиком."""
    page = Rendered(_page(monkeypatch, tmp_path))
    tabs = page.by_attr("role", "tab")
    assert tabs, "нет фильтров с role=tab"
    assert all(node["tag"] in {"button", "a"} for node in tabs), \
        "фильтр не кнопка и не ссылка"
