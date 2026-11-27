"""Доска: не больше N карточек в колонке — замер 27.11.2026.

Доска виз под Гришей весила 6.5 МБ (2692 карточки одной страницей) и перерисовывалась
опросом каждые 15 секунд — «панель лагает» на показе. Закреплено:
1. Без обрезки (флаг OFF) — колонки те же, что были: все карточки, без «ещё».
2. С обрезкой — в колонке первые N по текущей сортировке, total и hidden честные.
3. Метрики и раскладка по колонкам от обрезки не меняются.
4. Шаблон: счётчик колонки полный, кнопка «показать все» есть только у обрезанной,
   URL опроса без флага прежний, с ?all=1 — сохраняет all=1.
5. Тумблер зарегистрирован, дефолт OFF.
"""
from datetime import datetime, timedelta, timezone

import app.config
from app.admin import router as r
from app.integrations.panel.store import ConversationView

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def _convs(n):
    return [ConversationView(user_id=f"getvisa:{i}", funnel="visa", stage="greeting",
                             last_message_at=NOW - timedelta(minutes=i), last_sender="client",
                             last_text="x") for i in range(n)]


def _col(columns, key="greeting"):
    return next(c for c in columns if c["key"] == key)


def test_no_cap_keeps_everything():
    cols, _ = r._build_board(_convs(120), NOW)
    g = _col(cols)
    assert len(g["cards"]) == 120 and g["total"] == 120 and g["hidden"] == 0


def test_cap_shows_first_n_after_sort_and_counts_rest():
    full, _ = r._build_board(_convs(120), NOW, fresh_first=True)
    capped, _ = r._build_board(_convs(120), NOW, fresh_first=True, column_cap=50)
    g = _col(capped)
    assert len(g["cards"]) == 50 and g["total"] == 120 and g["hidden"] == 70
    # первые N — ровно голова полной колонки (самые свежие при fresh_first)
    assert [c["user_id"] for c in g["cards"]] == \
        [c["user_id"] for c in _col(full)["cards"]][:50]
    assert g["cards"][0]["user_id"] == "getvisa:0"


def test_cap_does_not_change_metrics_or_layout():
    a_cols, a_m = r._build_board(_convs(120), NOW)
    b_cols, b_m = r._build_board(_convs(120), NOW, column_cap=10)
    assert a_m == b_m
    assert [(c["key"], c["total"], c["is_empty"]) for c in a_cols] == \
        [(c["key"], c["total"], c["is_empty"]) for c in b_cols]


def test_small_column_is_not_marked_hidden():
    cols, _ = r._build_board(_convs(5), NOW, column_cap=50)
    g = _col(cols)
    assert len(g["cards"]) == 5 and g["hidden"] == 0


def _render(columns, metrics, **extra):
    tpl = r.templates.env.get_template("_board.html")
    ctx = {"funnel": "visa", "columns": columns, "metrics": metrics, "mine": 0,
           "crm_bot_mode": False, "standalone_crm": False}
    ctx.update(extra)
    return tpl.render(**ctx)


def test_template_flag_off_poll_url_unchanged_and_no_more_button():
    cols, m = r._build_board(_convs(120), NOW)
    html = _render(cols, m)
    assert 'hx-get="/admin/board/visa" hx-trigger' in html
    assert "показать все" not in html
    assert '<span class="count">120</span>' in html


def test_template_capped_shows_full_count_and_more_button():
    cols, m = r._build_board(_convs(120), NOW, column_cap=50)
    html = _render(cols, m, cap_on=True, show_all=0)
    assert '<span class="count">120</span>' in html          # полный счётчик, не 50
    assert "Ещё 70 · показать все" in html
    assert 'hx-get="/admin/board/visa?mine=0&amp;all=1"' in html \
        or 'hx-get="/admin/board/visa?mine=0&all=1"' in html
    assert html.count('class="card"') == 50


def test_template_show_all_keeps_all_in_poll_url():
    cols, m = r._build_board(_convs(120), NOW)
    html = _render(cols, m, cap_on=True, show_all=1)
    assert 'hx-get="/admin/board/visa?all=1" hx-trigger' in html
    html_mine = _render(cols, m, cap_on=True, show_all=1, mine=1)
    assert 'hx-get="/admin/board/visa?mine=1&amp;all=1" hx-trigger' in html_mine \
        or 'hx-get="/admin/board/visa?mine=1&all=1" hx-trigger' in html_mine


def test_needs_reply_filter_survives_poll_swap():
    """Фильтр «Требуют ответа» помнится в localStorage и возвращается после замены доски."""
    js = open("app/admin/templates/boards.html", encoding="utf-8").read()
    start = js.index("function toggleNeedsReply")
    body = js[start:js.index("function toggleNoise")]
    assert "_lsSet('onlyNeeds'" in body
    assert "_lsGet('onlyNeeds')" in js
    assert "classList.toggle('only-needs', needs)" in js


def test_flag_registered_with_default_off():
    assert app.config.Settings.model_fields["panel_board_column_cap_enabled"].default is False
    assert app.config.Settings.model_fields["panel_board_column_cap"].default == 50
    assert r.FEATURE_FLAGS["panel_board_column_cap_enabled"]["default"]() is False


# --- ревью 27.11 (Claude, без кросс-вендора): FIX_REQUIRED пп.1–6 ---------------------

def test_cap_keeps_needs_reply_cards_beyond_the_cut():
    """Фильтр «Требуют ответа» не должен видеть пустую колонку при ждущих за обрезкой."""
    convs = _convs(120)
    cols, _ = r._build_board(convs, NOW, fresh_first=True, column_cap=10)
    g = _col(cols)
    full, _ = r._build_board(convs, NOW, fresh_first=True)
    need_full = [c["user_id"] for c in _col(full)["cards"] if c["needs_reply"]]
    need_shown = [c["user_id"] for c in g["cards"] if c["needs_reply"]]
    assert need_shown == need_full                       # ни одного ждущего не потеряли
    assert g["hidden"] == g["total"] - len(g["cards"])   # счётчик «ещё» честный
    order = [c["user_id"] for c in _col(full)["cards"]]
    assert [c["user_id"] for c in g["cards"]] == [u for u in order if u in
                                                  {c["user_id"] for c in g["cards"]}]


def test_template_show_all_buttons_keep_all_and_offer_collapse():
    cols, m = r._build_board(_convs(120), NOW)
    html = _render(cols, m, cap_on=True, show_all=1)
    assert '?mine=1&amp;all=1"' in html or '?mine=1&all=1"' in html   # «Мои лиды» не теряет all
    assert "Свернуть колонки" in html
    off = _render(cols, m)
    assert "Свернуть колонки" not in off


def test_js_redraws_keep_board_url():
    js = open("app/admin/templates/boards.html", encoding="utf-8").read()
    moved = js[js.index("async function onCardMoved"):js.index("(Пере)инициализируем DnD")]
    assert "board.getAttribute('hx-get')" in moved
    active = js[js.index("function _activeBoardUrl"):js.index("function refreshCurrentList")]
    assert "getAttribute('hx-get')" in active
    assert "localStorage.setItem('onlyNeeds'" not in js   # только через безопасную обёртку
    assert "function _lsSet" in js


def _client(monkeypatch, cap_on):
    from fastapi.testclient import TestClient
    import app.main as main
    from app.config import ManagerConfig
    from app.integrations.panel import store as ps
    from app.core import flags
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True)], raising=False)
    monkeypatch.setattr(app.config.settings, "panel_board_column_cap_enabled", cap_on, raising=False)
    monkeypatch.setattr(app.config.settings, "panel_board_column_cap", 10, raising=False)
    for c in _convs(40):
        ps._memory_store._conv[c.user_id] = c
    cl = TestClient(main.app, base_url="https://testserver")
    cl.post("/admin/login", data={"login": "admin", "password": "frunze"})
    return cl


def test_endpoint_flag_off_ignores_all_and_renders_everything(monkeypatch):
    cl = _client(monkeypatch, cap_on=False)
    for url in ("/admin/board/visa", "/admin/board/visa?all=1"):
        html = cl.get(url).text
        assert html.count('class="card"') == 40, url
        assert "показать все" not in html and "Свернуть колонки" not in html
        assert 'hx-get="/admin/board/visa" hx-trigger' in html


def test_endpoint_flag_on_caps_and_all_uncaps(monkeypatch):
    cl = _client(monkeypatch, cap_on=True)
    capped = cl.get("/admin/board/visa").text
    assert "показать все" in capped
    assert capped.count('class="card"') < 40
    full = cl.get("/admin/board/visa?all=1").text
    assert full.count('class="card"') == 40
    assert 'hx-get="/admin/board/visa?all=1" hx-trigger' in full
    assert "Свернуть колонки" in full
