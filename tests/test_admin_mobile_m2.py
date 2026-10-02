"""ГЕЙТ M2: админка на телефоне.

Зачем. Менеджеры работают с телефона, а панель до 02.10.2026 была рассчитана только на
мышь и широкий экран. Четыре вещи, оставленные долгом в M1 (handoff 2026-10-01-1840):

  1. канбан жил в горизонтальном скролле — половина стадий всегда за краем экрана;
  2. кнопки карточки (архив, выбор) проявлялись по `:hover` — на тач-экране наведения
     нет, то есть до них нельзя дотянуться вообще;
  3. переписка на узком экране становилась блоком ПОД доской: чтобы её увидеть, надо
     было проскроллить мимо всех карточек;
  4. перетаскивание карточек на тач отбирало жест прокрутки — доску нельзя было просто
     пролистать.

Проверяем правила и каскад, а не внешний вид: «выглядит нормально» тестом не ловится.
Отдельно закреплено, что десктоп не изменился — лист и крестик живут только под
`@media (max-width: 760px)`.

Вид на настоящем телефоне менеджера этот гейт не заменяет: это приёмка человеком.
"""
import re
from pathlib import Path

import app.admin.router as admin_router

TEMPLATES = Path(admin_router.__file__).parent / "templates"
BOARDS = (TEMPLATES / "boards.html").read_text(encoding="utf-8")
CONVERSATION = (TEMPLATES / "_conversation.html").read_text(encoding="utf-8")

PHONE = "max-width: 760px"


def _media_block(css: str, condition: str) -> str:
    """Тело `@media (<condition>)` с учётом вложенных скобок.

    Простым регэкспом не обойтись: внутри блока есть вложенный
    `@media (prefers-reduced-motion: reduce)`, и нежадный поиск до первой `}`
    отрезал бы половину правил, а жадный — захватил бы весь файл.
    """
    start = css.find("@media (%s)" % condition)
    assert start != -1, "нет @media (%s)" % condition
    open_brace = css.index("{", start)
    depth, i = 0, open_brace
    while i < len(css):
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_brace + 1:i]
        i += 1
    raise AssertionError("незакрытый @media (%s)" % condition)


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def _drop_nested_media(block: str) -> str:
    """Вложенные `@media` выкидываем: иначе `#chat { transition: none }` из блока
    prefers-reduced-motion выдаёт себя за правило телефона."""
    out, i = [], 0
    while True:
        start = block.find("@media", i)
        if start == -1:
            out.append(block[i:])
            return "".join(out)
        out.append(block[i:start])
        depth, j = 0, block.index("{", start)
        while j < len(block):
            if block[j] == "{":
                depth += 1
            elif block[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1


def _rule(block: str, selector: str) -> str:
    """Объявления одного правила внутри блока. Селектор ищем как отдельный."""
    clean = _drop_nested_media(_strip_comments(block))
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", clean):
        selectors = [s.strip() for s in match.group(1).split(",")]
        if selector in selectors:
            return match.group(2)
    raise AssertionError("в блоке нет правила для %r" % selector)


# --- A. Канбан без горизонтального скролла ----------------------------------

def test_phone_board_stacks_columns_instead_of_scrolling_sideways():
    phone = _media_block(BOARDS, PHONE)
    board = _rule(phone, ".board")
    assert "flex-direction: column" in board, "колонки канбана не выстроены лентой вниз"
    assert "overflow-x: visible" in board, "горизонтальный скролл доски не снят"
    # Колонка шириной 282px в столбце дала бы узкую полосу у края экрана.
    cols = _rule(phone, ".col")
    assert "width: auto" in cols, "колонка осталась фиксированной ширины"


def test_desktop_board_keeps_horizontal_scroll():
    """Широкий экран не трогаем: там горизонтальная доска — это и есть канбан."""
    base = BOARDS[:BOARDS.find("@media (%s)" % PHONE)]
    assert "overflow-x: auto" in _rule(base, ".board")


# --- B. Кнопки карточки без наведения ---------------------------------------

def test_card_buttons_are_visible_where_there_is_no_hover():
    no_hover = _media_block(BOARDS, "hover: none")
    for selector in (".card-archive", ".card-select"):
        assert "opacity: 1" in _rule(no_hover, selector), (
            "%s остаётся невидимым на тач-экране" % selector)


def test_card_buttons_stay_hover_revealed_on_desktop():
    """На мыши кнопки по-прежнему проявляются по наведению — вид не изменился."""
    assert ".card:hover .card-archive" in BOARDS
    assert ".card:hover .card-select" in BOARDS


# --- C. Переписка листом поверх списка --------------------------------------

def test_phone_chat_is_a_sheet_over_the_list():
    phone = _media_block(BOARDS, PHONE)
    chat = _rule(phone, "#chat")
    assert "position: fixed" in chat, "чат не поднят над списком"
    assert "bottom: 0" in chat, "лист не прижат к низу экрана"
    assert "transform: translateY(102%)" in chat, "лист не спрятан, пока диалог не выбран"
    assert "transform: none" in _rule(phone, "body.chat-open #chat"), \
        "выбранный диалог не поднимает лист"


def test_phone_rules_come_after_the_1180_breakpoint():
    """Каскад, а не косметика: правило 1180px делает `#chat { position: static }`.

    Стоя ВЫШЕ нашего блока, оно проигрывает по порядку — и лист работает. Переставь
    блоки местами, и на телефоне чат снова ляжет под доску, хотя оба правила на месте.
    """
    assert BOARDS.find("@media (max-width: 1180px)") < BOARDS.find("@media (%s)" % PHONE)


def test_sheet_can_be_closed():
    assert "function closeChatSheet()" in BOARDS, "лист нечем закрыть"
    assert "closeChatSheet()" in CONVERSATION, "в шапке переписки нет крестика"
    assert 'class="sheet-close"' in CONVERSATION
    # Esc и тап по затемнению — те же две двери, что у любого модального листа.
    assert "'Escape'" in BOARDS


def test_close_button_is_hidden_on_desktop():
    """Крестик появляется только на телефоне: рядом стоящую панель закрывать не от чего.

    Порядок здесь важнее наличия: `display: none` той же специфичности, поставленный
    ПОСЛЕ медиа-блока, молча погасил бы крестик и на телефоне тоже.
    """
    base = BOARDS[:BOARDS.find("@media (%s)" % PHONE)]
    assert "display: none" in _rule(base, ".sheet-close"), \
        "базовое правило крестика стоит не до медиа-блока — на телефоне его не будет"
    assert "display: inline-flex" in _rule(_media_block(BOARDS, PHONE), ".sheet-close")


def test_empty_chat_does_not_raise_the_sheet():
    """Пустое состояние (`.panel-empty`) — это «диалог не выбран», лист поднимать нечем."""
    assert "querySelector('.panel-empty')" in BOARDS


def test_closed_sheet_survives_the_chat_autorefresh():
    """Открытая переписка опрашивает сервер каждые 4с и каждый раз доезжает до
    `htmx:afterSettle`. Без памяти о закрытии лист всплывал бы обратно сам."""
    assert "_chatSheetDismissed" in BOARDS
    body = BOARDS[BOARDS.find("function closeChatSheet()"):]
    body = body[:body.find("});", body.find("htmx:afterSettle"))]
    assert "_chatSheetDismissed = true" in body, "крестик не запоминает закрытие"
    assert "if (_chatSheetDismissed) return;" in body, "автообновление поднимет лист обратно"
    assert "_chatSheetDismissed = false" in body, "выбор следующей карточки не снимает память"


# --- D. Перетаскивание на тач -----------------------------------------------

def test_touch_drag_waits_before_stealing_the_scroll():
    cfg = BOARDS[BOARDS.find("Sortable.create(col, {"):]
    cfg = cfg[:cfg.find("});")]
    assert "delayOnTouchOnly: true" in cfg, "задержка применена и к мыши — десктоп замедлится"
    delay = re.search(r"\bdelay:\s*(\d+)", cfg)
    assert delay and int(delay.group(1)) > 0, "нет задержки — палец утащит карточку вместо прокрутки"
    assert "touchStartThreshold" in cfg, "нет порога дрожания пальца"
