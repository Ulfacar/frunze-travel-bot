"""Упрощённый вид въездной CRM для визового менеджера (PM-ревью 30.10, задача 4).

Написан ДО реализации. Правило: всё только при `kg_entry_manager_access_enabled` и
только для НЕ-админа; админский вид не меняется ни на байт в проверяемых местах.

1. Анкета: страны — русскими названиями (или английскими из ISO-справочника), код в
   `value` как раньше; поиск по списку; главные поля шага (ТЗ 3.4) сверху, остальное под
   «Остальные вопросы».
2. Навигация `kg_*`: менеджеру — минимальный набор, прочие экраны под «Для специалиста».
3. Документы: менеджеру один вход («Полный комплект»), «прежний реестр» — под специалиста.
"""
import asyncio
import re
from pathlib import Path

import pytest

import app.admin.router as ar
import app.config
from tests.test_kg_entry_manager_access import env, _flag, _url, _login  # noqa: F401

SPECIALIST = "Для специалиста"
REST = "Остальные вопросы"


def _page(login, path, status=200):
    client = _login(login)
    try:
        page = client.get(path)
        assert page.status_code == status, (path, page.status_code)
        return page.text
    finally:
        client.close()


def _application(env, login="medina"):
    """Заявитель + черновик заявки в своей услуге (через реальные формы)."""
    client = _login(login)
    try:
        url = _url(env, "mine") + "/applications"
        html = client.get(url).text
        def hidden(form_id):
            block = html[html.index(f'id="{form_id}"'):]
            block = block[:block.index("</form>")]
            return dict(re.findall(r'name="([^"]+)" value="([^"]*)"', block))
        client.post(url, data=dict(hidden("kg-applicant-form"), role="primary"))
        html = client.get(url).text
        client.post(url, data=dict(hidden("kg-application-form"), applicant_id="1", procedure="visa"))
        return url + "?application_id=1"
    finally:
        client.close()


# --- 1. Анкета ----------------------------------------------------------------------

def test_manager_sees_country_names_not_bare_codes(env, monkeypatch):
    _flag(monkeypatch, True)
    html = _page("medina", _url(env, "mine"))
    block = html[html.index('id="kg-citizenship"'):]
    block = block[:block.index("</select>")]
    options = re.findall(r'<option value="([A-Z]{3})"[^>]*>([^<]*)</option>', block)
    assert options, "список стран пуст"
    bare = [code for code, title in options if title.strip() == code]
    assert not bare, f"коды без названия: {bare[:5]}"
    # Названия — русские (из алиасов базы) или английские (из ISO-справочника), код в скобках.
    assert all(title.endswith(f"({code})") for code, title in options), options[:5]
    assert all(title[:-len(f"({code})")].strip() != code for code, title in options)
    assert 'id="kg-country-search"' in html or 'class="kg-country-search"' in html


def test_admin_form_unchanged_by_manager_view(env, monkeypatch):
    """Админ видит прежний список (коды без русского алиаса — как были) и прежний порядок."""
    _flag(monkeypatch, True)
    html = _page("admin", _url(env, "mine"))
    assert SPECIALIST not in html and REST not in html
    assert 'id="kg-country-search"' not in html
    # Прежняя шапка со всеми ссылками.
    assert "Проверка черновых процессов" in html and "Черновой чек-лист документов" in html


def test_manager_form_key_fields_first_rest_collapsed(env, monkeypatch):
    _flag(monkeypatch, True)
    html = _page("medina", _url(env, "mine"))
    assert REST in html
    main_block = html[:html.index(REST)]
    rest_block = html[html.index(REST):]
    # Главное (ТЗ 3.4): гражданство, тип документа, где сейчас, цель, даты, приглашающая сторона.
    for name in ("citizenship", 'name="document_type"', 'name="current_location"', 'name="purpose"',
                 'name="entry_date"', 'name="exit_date"', 'name="inviting_party.exists"',
                 'name="previous_refusals_kg"', 'name="violations.overstay"'):
        assert name in main_block, name
    # Второстепенное — под сворачиваемым блоком.
    for name in ('name="entry_point"', 'name="tickets_bought"', 'name="escalation.complaint"',
                 'name="inviting_party.has_portal_cabinet"'):
        assert name not in main_block and name in rest_block, name
    # Каждое поле ровно один раз: форма отправляется как прежде.
    assert html.count('name="purpose"') == 1 and html.count('name="citizenship"') == 1


def test_manager_form_submits_like_before(env, monkeypatch):
    _flag(monkeypatch, True)
    client = _login("medina")
    try:
        html = client.get(_url(env, "mine")).text
        block = html[html.index('id="kg-entry-form"'):]
        data = dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', block))
        data.update({"language": "ru", "citizenship": ["IND"], "purpose": "business_meeting",
                     "document_type": "ordinary", "current_location": "abroad"})
        r = client.post(_url(env, "mine"), data=data, follow_redirects=False)
        assert r.status_code == 303, r.text[-500:]
        page = client.get(_url(env, "mine")).text
        assert 'value="IND" selected' in page or 'value="IND"  selected' in page or "IND" in page
    finally:
        client.close()


# --- 2/3. Навигация и документы ------------------------------------------------------

def test_manager_navigation_is_collapsed_admin_is_not(env, monkeypatch):
    _flag(monkeypatch, True)
    manager = _page("medina", _url(env, "mine"))
    assert SPECIALIST in manager
    head = manager[:manager.index(SPECIALIST)]
    assert "Проверка черновых процессов" not in head and "Черновики сообщений" not in head
    assert "Заявители и подачи" in head
    admin = _page("admin", _url(env, "mine"))
    assert SPECIALIST not in admin


def test_manager_application_links_minimal_documents_single_entry(env, monkeypatch):
    _flag(monkeypatch, True)
    url = _application(env)
    manager = _page("medina", url)
    section = manager[manager.index('id="kg-application-title"'):]
    section = section[:section.index('id="kg-application-status"')]
    assert SPECIALIST in section
    head = section[:section.index(SPECIALIST)]
    tail = section[section.index(SPECIALIST):]
    assert "document-package" in head and "Сроки заявки" in head
    assert "/documents\"" not in head and "прежний реестр" not in head
    assert "/documents\"" in tail and "quotes" in tail and "notification-drafts" in tail
    # Экран документов: у менеджера ссылка на прежний реестр спрятана под специалиста.
    dp = _page("medina", url.split("?")[0] + "/1/document-package")
    assert "Прежний реестр" not in dp[:dp.index(SPECIALIST)] if SPECIALIST in dp else "Прежний реестр" not in dp
    admin = _page("admin", url)
    assert SPECIALIST not in admin and "прежний реестр" in admin


def test_flag_off_leaves_admin_view_as_base(env, monkeypatch):
    _flag(monkeypatch, False)
    admin = _page("admin", _url(env, "mine"))
    assert SPECIALIST not in admin and REST not in admin and 'id="kg-country-search"' not in admin
    _page("medina", _url(env, "mine"), status=403)


CHANGED_TEMPLATES = ("kg_entry.html", "_kg_entry_field.html", "kg_applications.html",
                     "kg_document_package.html")


def _render_with_templates(client, path, searchpath):
    loader = ar.templates.env.loader
    old = list(loader.searchpath)
    loader.searchpath[:] = [str(searchpath)]
    ar.templates.env.cache.clear()
    try:
        page = client.get(path); assert page.status_code == 200
        return page.text
    finally:
        loader.searchpath[:] = old
        ar.templates.env.cache.clear()


@pytest.mark.parametrize("flag", [False, True])
def test_admin_pages_render_as_on_base_templates(env, monkeypatch, tmp_path, flag):
    """Админ при любом значении флага видит то же, что рендерили шаблоны базы 74ba9b5.

    Сравнение по живому HTTP-рендеру: каталог шаблонов подменяется копией, в которой
    четыре изменённых шаблона взяты из `git show 74ba9b5:…`. Отличия только в пустых
    строках от `{% if kg_simple %}` — пробелы нормализуются; всё прочее — регрессия.
    """
    import shutil
    import subprocess
    _flag(monkeypatch, flag)
    src = Path(ar.templates.env.loader.searchpath[0])
    base_dir = tmp_path / "base"
    shutil.copytree(src, base_dir)
    for name in CHANGED_TEMPLATES:
        text = subprocess.run(["git", "show", f"74ba9b5:app/admin/templates/{name}"],
                              capture_output=True, text=True, check=True).stdout
        assert text != (src / name).read_text(encoding="utf-8"), f"{name} не менялся"
        (base_dir / name).write_text(text, encoding="utf-8")
    url = _application(env, login="admin")
    pages = [_url(env, "mine"), url, url.split("?")[0] + "/1/document-package"]
    client = _login("admin")
    try:
        norm = lambda t: re.sub(r"\s+", " ", t).replace("> <", "><").strip()
        for path in pages:
            now = _render_with_templates(client, path, src)
            base = _render_with_templates(client, path, base_dir)
            # Подписи форм (ключи/CSRF) меняются между запросами — вырезаем их.
            scrub = lambda t: re.sub(r'value="[0-9a-f]{32,64}"', 'value="~"', t)
            assert norm(scrub(base)) == norm(scrub(now)), path
    finally:
        client.close()
