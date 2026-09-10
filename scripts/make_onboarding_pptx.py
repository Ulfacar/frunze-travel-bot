"""Сборка PPTX «Одна кнопка вечером» — онбординг менеджеров по турам.

Для Даулета, Гриши и менеджеров (Адеми, Айсина). Аудитория не техническая, и главная
задача — НЕ напугать: от менеджера требуется ровно одно действие, всё остальное бот
делает сам. Поэтому никакой внутренней кухни, никаких слов «лид», «воронка», «конверсия»
без перевода на человеческий.

Отдельный повод: 10.09 заказчик прислал скриншот раздела «Сделки» со словами «не вижу
карточки по турам». Он смотрел в конвейер оплаченных туров (там их пять), а карточки
бота лежат в «Лидах» (их 719). Слайд 2 снимает ровно эту путаницу.

Все числа — замеры прода на 10.09.2026.
Переиспользует движок стилей из make_presentation.py.

Запуск:  python scripts/make_onboarding_pptx.py
Результат: C:\\Users\\alanb\\OneDrive\\Рабочий стол\\Frunze-онбординг-менеджеров-10-09.pptx
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

from make_presentation import (  # noqa: E402
    SAFE_L, SLIDE_H, SLIDE_W, Palette, add_bg, add_card, add_footer, add_shape, add_text,
    add_title, emu,
)

OUT = Path(r"C:\Users\alanb\OneDrive\Рабочий стол\Frunze-онбординг-менеджеров-10-09.pptx")


def _blank(prs):
    return prs.slides.add_slide(prs.slide_layouts[6])


# --- 1. Титул --------------------------------------------------------------------------
def slide_title(prs):
    s = _blank(prs)
    add_bg(s, dark=True)
    add_text(s, SAFE_L, 2.25, 8.0, 0.34, "FRUNZE TRAVEL · ТУРЫ · 10.09.2026", 11, True,
             Palette.muted_dark)
    add_text(s, SAFE_L, 2.7, 11.5, 1.0, "Одна кнопка вечером", 42, True, Palette.white)
    add_shape(s, MSO_SHAPE.RECTANGLE, SAFE_L, 3.95, 2.6, 0.07, Palette.teal, label="line")
    add_text(s, SAFE_L, 4.3, 11.0, 0.6,
             "Что бот уже делает сам и что нужно от менеджера", 17, False, Palette.muted_dark)
    add_text(s, SAFE_L, 5.35, 11.0, 0.4,
             "Спойлер: от менеджера — одно нажатие в день. Битриксу учиться не нужно.",
             13, False, Palette.teal)
    add_footer(s, 1, dark=True)


# --- 2. Где что лежит ------------------------------------------------------------------
def slide_where(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Где искать карточки по турам", kicker="Самая частая путаница")

    add_card(s, SAFE_L, 2.05, 5.9, 3.15, Palette.green_soft, Palette.teal)
    add_text(s, SAFE_L + 0.4, 2.3, 5.1, 0.32, "ЛИДЫ — здесь работает бот", 12, True,
             Palette.teal_dark)
    add_text(s, SAFE_L + 0.4, 2.7, 5.1, 0.8, "719", 44, True, Palette.teal_dark)
    add_text(s, SAFE_L + 0.4, 3.55, 5.1, 0.34, "карточек создано ботом", 14, True, Palette.ink)
    add_text(s, SAFE_L + 0.4, 3.95, 5.1, 1.1,
             "Каждый, кто написал в WhatsApp, получает карточку.\n"
             "Бот сам её заполняет и двигает по колонкам.\n"
             "486 карточек он уже передвинул, в 478 написал сводку.",
             12, False, Palette.slate)

    add_card(s, 6.85, 2.05, 5.85, 3.15, Palette.amber_soft, Palette.amber)
    add_text(s, 7.25, 2.3, 5.05, 0.32, "СДЕЛКИ FRUNZETRAVEL — только оплаченные", 12, True,
             Palette.ink)
    add_text(s, 7.25, 2.7, 5.05, 0.8, "5", 44, True, Palette.amber)
    add_text(s, 7.25, 3.55, 5.05, 0.34, "сделок за три месяца", 14, True, Palette.ink)
    add_text(s, 7.25, 3.95, 5.05, 1.1,
             "Первая колонка называется «Оплата получено».\n"
             "Сюда тур попадает ПОСЛЕ оплаты — это конвейер\n"
             "уже купленного тура, а не заявок.",
             12, False, Palette.slate)

    add_card(s, SAFE_L, 5.45, 12.1, 0.95, Palette.grey_soft, Palette.line)
    add_text(s, SAFE_L + 0.35, 5.6, 11.4, 0.32,
             "Если открыть «Сделки» и не увидеть заявок — всё правильно, они не там.",
             15, True, Palette.ink)
    add_text(s, SAFE_L + 0.35, 5.95, 11.4, 0.32,
             "Карточки бота — в верхнем меню «Лиды», слева от «Сделок».",
             13, False, Palette.slate)
    add_footer(s, 2)


# --- 3. Что бот делает сам -------------------------------------------------------------
def slide_bot_does(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Что бот делает сам", kicker="От менеджера здесь не нужно ничего")

    items = [
        ("Заводит карточку", "Клиент написал — карточка создана, номер и источник внутри."),
        ("Расспрашивает", "Куда, когда, сколько человек, бюджет — записывает в карточку."),
        ("Подбирает туры", "Ищет варианты и присылает клиенту подборку с ценами."),
        ("Двигает по колонкам", "Карточка сама переезжает по мере разговора."),
        ("Пишет сводку", "В карточке появляется «Досье бота» — о чём договорились."),
        ("Молчит, когда вы вмешались", "Взяли диалог на себя — бот замолкает и не мешает."),
    ]
    x, y = SAFE_L, 2.05
    for i, (title, body) in enumerate(items):
        col = i % 2
        row = i // 2
        left = SAFE_L + col * 6.25
        top = y + row * 1.5
        add_card(s, left, top, 5.85, 1.3, Palette.white, Palette.line)
        add_shape(s, MSO_SHAPE.OVAL, left + 0.3, top + 0.42, 0.42, 0.42, Palette.teal,
                  label="tick")
        add_text(s, left + 0.3, top + 0.47, 0.42, 0.32, "✓", 15, True, Palette.white,
                 PP_ALIGN.CENTER)
        add_text(s, left + 0.95, top + 0.28, 4.7, 0.34, title, 15, True, Palette.ink)
        add_text(s, left + 0.95, top + 0.66, 4.7, 0.5, body, 11.5, False, Palette.slate)
    add_footer(s, 3)


# --- 4. Где рвётся ---------------------------------------------------------------------
def slide_gap(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "И одно звено, которое рвётся", kicker="Это не про лень, это про удобство")

    steps = [
        ("Клиент написал", "бот завёл карточку", True),
        ("Бот выяснил запрос", "двигает, пишет сводку", True),
        ("Менеджер продал тур", "нажать «Оплатил» — НЕ НАЖИМАЕТ", False),
        ("Владелец смотрит отчёт", "видит «Продано: 0»", False),
    ]
    y = 2.1
    for title, body, ok in steps:
        accent = Palette.teal if ok else Palette.red
        soft = Palette.green_soft if ok else Palette.red_soft
        add_card(s, SAFE_L, y, 7.4, 0.92, soft, accent)
        add_text(s, SAFE_L + 0.35, y + 0.14, 3.5, 0.32, title, 14, True, Palette.ink)
        add_text(s, SAFE_L + 0.35, y + 0.5, 6.6, 0.3, body, 12, False, Palette.slate)
        add_text(s, SAFE_L + 6.6, y + 0.25, 0.6, 0.4, "✓" if ok else "✕", 20, True, accent,
                 PP_ALIGN.RIGHT)
        y += 1.05

    add_card(s, 8.4, 2.1, 4.3, 4.2, Palette.navy, Palette.navy)
    add_text(s, 8.7, 2.4, 3.7, 0.3, "ЧТО ЭТО ЗНАЧИТ", 11, True, Palette.muted_dark)
    add_text(s, 8.7, 2.85, 3.7, 0.6, "251", 38, True, Palette.white)
    add_text(s, 8.7, 3.5, 3.7, 0.32, "обращение за неделю", 13, False, Palette.muted_dark)
    add_text(s, 8.7, 4.05, 3.7, 0.6, "0", 38, True, Palette.red)
    add_text(s, 8.7, 4.7, 3.7, 0.32, "продаж в отчёте", 13, False, Palette.muted_dark)
    add_text(s, 8.7, 5.25, 3.7, 0.9,
             "Кнопка «Оплатил» в панели есть с июля.\nЗа 90 дней её нажали 1–3 раза:\n"
             "в момент продажи менеджер в WhatsApp,\nа не в админке.",
             11, False, Palette.muted_dark)
    add_footer(s, 4)


# --- 5. Что меняется -------------------------------------------------------------------
def slide_change(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Что меняется для менеджера", kicker="Ровно одна вещь")

    add_card(s, SAFE_L, 2.05, 12.1, 1.5, Palette.green_soft, Palette.teal)
    add_text(s, SAFE_L + 0.45, 2.3, 11.2, 0.45,
             "Вечером в 18:00 приходит одно сообщение в Telegram.", 22, True, Palette.teal_dark)
    add_text(s, SAFE_L + 0.45, 2.85, 11.2, 0.5,
             "В нём до пяти ваших клиентов. По каждому — три ссылки. Нажали одну — готово.",
             15, False, Palette.ink)

    add_text(s, SAFE_L, 3.85, 12.1, 0.35, "Всё остальное остаётся как было:", 15, True,
             Palette.ink)
    same = [
        "Работаете в WhatsApp, как привыкли",
        "В Битрикс заходить не нужно",
        "Ничего не заполняете руками",
        "Взяли диалог на себя — бот молчит",
    ]
    y = 4.3
    for text in same:
        add_shape(s, MSO_SHAPE.OVAL, SAFE_L + 0.05, y + 0.09, 0.13, 0.13, Palette.grey,
                  label="dot")
        add_text(s, SAFE_L + 0.35, y, 11.5, 0.32, text, 14, False, Palette.slate)
        y += 0.42

    add_card(s, SAFE_L, 6.15, 12.1, 0.75, Palette.amber_soft, Palette.amber)
    add_text(s, SAFE_L + 0.35, 6.32, 11.4, 0.42,
             "Не ответили — ничего страшного. Про этот диалог больше не спросим, "
             "напоминать каждый вечер не будем.", 13, True, Palette.ink)
    add_footer(s, 5)


# --- 6. Как выглядит сообщение ---------------------------------------------------------
def slide_message(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Как выглядит сообщение", kicker="Настоящее, с боевых данных")

    add_card(s, SAFE_L, 2.05, 7.3, 4.3, Palette.white, Palette.line)
    lines = [
        ("Добрый вечер! Отметьте, чем закончилось — одно касание:", 12, True, Palette.ink),
        ("", 6, False, Palette.ink),
        ("1. …0767 · Вьетнам · вчера", 12, True, Palette.ink),
        ("     вы: «AQUASUN HOTEL PHU QUOC 4⭐ Бишкек ➡ Фукуок…»", 10.5, False, Palette.slate),
        ("     ✅ Оплатил: frunzetravel.kg/sale/LTMwX0Z5eX…", 10.5, False, Palette.teal_dark),
        ("     ❌ Не сложилось: frunzetravel.kg/sale/LTMwX0Z5eX…", 10.5, False, Palette.slate),
        ("     ⏳ Ещё думает: frunzetravel.kg/sale/LTMwX0Z5eX…", 10.5, False, Palette.slate),
        ("", 6, False, Palette.ink),
        ("2. …3478 · Турция · вчера", 12, True, Palette.ink),
        ("     вы: «Добрый день, рассмотрели ли вы варианты…»", 10.5, False, Palette.slate),
        ("     ✅ Оплатил   ❌ Не сложилось   ⏳ Ещё думает", 10.5, False, Palette.teal_dark),
    ]
    y = 2.28
    for text, size, bold, color in lines:
        if text:
            add_text(s, SAFE_L + 0.35, y, 6.7, 0.3, text, size, bold, color)
        y += 0.33 if text else 0.14

    add_card(s, 8.25, 2.05, 4.45, 4.3, Palette.grey_soft, Palette.line)
    add_text(s, 8.6, 2.3, 3.8, 0.32, "ЧТО В СТРОКЕ", 11, True, Palette.teal_dark)
    hints = [
        ("…0767", "последние 4 цифры номера — весь номер не пишем"),
        ("Вьетнам", "куда собирался клиент"),
        ("вчера", "когда был последний разговор"),
        ("«…»", "последняя реплика и кто её сказал"),
    ]
    y = 2.8
    for key, body in hints:
        add_text(s, 8.6, y, 3.8, 0.3, key, 13, True, Palette.ink)
        add_text(s, 8.6, y + 0.3, 3.8, 0.55, body, 11, False, Palette.slate)
        y += 0.92
    add_footer(s, 6)


# --- 7. Страница: сверить и подтвердить ------------------------------------------------
def slide_page(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Нажали ссылку — сверили — подтвердили",
              kicker="Само нажатие ссылки ничего не записывает")

    add_card(s, SAFE_L, 2.05, 5.6, 4.3, Palette.white, Palette.line)
    add_text(s, SAFE_L + 0.35, 2.3, 4.9, 0.38, "Клиент оплатил", 18, True, Palette.ink)
    add_text(s, SAFE_L + 0.35, 2.72, 4.9, 0.3, "…0767 · Вьетнам · вчера", 12, False,
             Palette.slate)
    add_card(s, SAFE_L + 0.35, 3.12, 4.9, 1.75, Palette.grey_soft, Palette.line)
    add_text(s, SAFE_L + 0.6, 3.28, 4.4, 0.28, "Бот записал так — проверьте:", 11, True,
             Palette.teal_dark)
    facts = [("направление", "Вьетнам, Фукуок"), ("даты", "5–12 ноября"),
             ("туристы", "2 взрослых"), ("бюджет", "до $2000")]
    y = 3.62
    for key, val in facts:
        add_text(s, SAFE_L + 0.6, y, 1.9, 0.26, key, 10.5, False, Palette.slate)
        add_text(s, SAFE_L + 2.5, y, 2.5, 0.26, val, 10.5, True, Palette.ink)
        y += 0.29
    add_shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, SAFE_L + 0.35, 5.02, 4.9, 0.55,
              Palette.teal_dark, label="btn")
    add_text(s, SAFE_L + 0.35, 5.16, 4.9, 0.3, "Подтвердить", 14, True, Palette.white,
             PP_ALIGN.CENTER)
    add_text(s, SAFE_L + 0.35, 5.72, 4.9, 0.3, "Открыть карточку в Битриксе", 11, False,
             Palette.teal_dark, PP_ALIGN.CENTER)

    add_text(s, 6.75, 2.15, 5.95, 0.34, "Здесь и происходит проверка", 17, True, Palette.ink)
    add_text(s, 6.75, 2.55, 5.95, 0.9,
             "Прежде чем подтвердить, вы видите всё, что бот записал по клиенту. "
             "Если он что-то понял неправильно — это видно сразу, до нажатия, "
             "и в Битрикс заходить не нужно.", 13, False, Palette.slate)

    rows = [
        ("✅ Оплатил", "Продажа идёт в отчёт, карточка уезжает в «Подписан».", Palette.teal,
         Palette.green_soft),
        ("❌ Не сложилось", "Отмечаем, что не купил. Карточку не трогаем.", Palette.grey,
         Palette.grey_soft),
        ("⏳ Ещё думает", "Ничего не записываем, спросим снова через 3 дня.", Palette.amber,
         Palette.amber_soft),
    ]
    y = 3.65
    for title, body, accent, soft in rows:
        add_card(s, 6.75, y, 5.95, 0.85, soft, accent)
        add_text(s, 7.05, y + 0.13, 5.4, 0.3, title, 13, True, Palette.ink)
        add_text(s, 7.05, y + 0.45, 5.4, 0.3, body, 11.5, False, Palette.slate)
        y += 0.95
    add_footer(s, 7)


# --- 8. Если что-то не так -------------------------------------------------------------
def slide_fix(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Если бот ошибся или вы нажали не то",
              kicker="Ничего необратимого здесь нет")

    cases = [
        ("Бот записал неверное направление или даты",
         "Видно прямо на странице, до нажатия.",
         "Откройте карточку в Битриксе по ссылке снизу и поправьте поле руками. "
         "Бот ваши правки не перезатирает.", Palette.teal, Palette.green_soft),
        ("Нажали «Оплатил», а клиент не платил",
         "Отметку можно сменить.",
         "Зайдите в панель, откройте диалог и поставьте правильный исход. "
         "Карточку в Битриксе при этом верните руками — бот её назад не двигает.",
         Palette.amber, Palette.amber_soft),
        ("Клиент в списке, но вы его не помните",
         "Так бывает: диалог мог вести бот целиком.",
         "Нажмите «Ещё думает» — вопрос вернётся через три дня. "
         "Или не отвечайте вовсе: повторно не спросим.", Palette.grey, Palette.grey_soft),
    ]
    y = 2.05
    for title, lead, body, accent, soft in cases:
        add_card(s, SAFE_L, y, 12.1, 1.36, soft, accent)
        add_text(s, SAFE_L + 0.35, y + 0.16, 11.4, 0.32, title, 15, True, Palette.ink)
        add_text(s, SAFE_L + 0.35, y + 0.52, 11.4, 0.28, lead, 12, True, Palette.teal_dark)
        add_text(s, SAFE_L + 0.35, y + 0.83, 11.4, 0.42, body, 12, False, Palette.slate)
        y += 1.48

    add_text(s, SAFE_L, 6.55, 12.1, 0.32,
             "Главное правило: решение всегда за человеком. Бот не ставит «Некачественный» "
             "и не отменяет ваших правок.", 13, True, Palette.ink)
    add_footer(s, 8)


# --- 9. План внедрения -----------------------------------------------------------------
def slide_rollout(prs):
    s = _blank(prs)
    add_bg(s)
    add_title(s, "Как включаем", kicker="Осторожно, на одном человеке")

    steps = [
        ("Неделя 1", "Только Адеми",
         "Вечерний вопрос приходит одной Адеми. У неё 30 накопившихся диалогов, "
         "по 5 в вечер — примерно шесть вечеров на разбор.", Palette.teal),
        ("Смотрим", "Сколько ответов из 30",
         "Это и есть проверка: если ссылками пользуются — включаем Айсину. "
         "Если нет — значит дело не в удобстве, и это уже разговор, а не код.",
         Palette.amber),
        ("Потом", "Все менеджеры + сделки",
         "Включаем остальных и автоматическое создание сделки: отмеченная продажа "
         "сама появляется в воронке FrunzeTravel.", Palette.navy),
    ]
    x = SAFE_L
    for label, title, body, accent in steps:
        add_card(s, x, 2.15, 3.9, 3.1, Palette.white, Palette.line)
        add_shape(s, MSO_SHAPE.RECTANGLE, x, 2.15, 3.9, 0.09, accent, label="cap")
        add_text(s, x + 0.32, 2.5, 3.3, 0.3, label.upper(), 11, True, accent)
        add_text(s, x + 0.32, 2.9, 3.3, 0.66, title, 18, True, Palette.ink)
        add_text(s, x + 0.32, 3.7, 3.3, 1.35, body, 12, False, Palette.slate)
        x += 4.1

    add_card(s, SAFE_L, 5.55, 12.1, 0.95, Palette.green_soft, Palette.teal)
    add_text(s, SAFE_L + 0.35, 5.72, 11.4, 0.32,
             "Что увидит владелец: строка «Продано» в еженедельной сводке перестанет быть нулём.",
             14, True, Palette.ink)
    add_text(s, SAFE_L + 0.35, 6.08, 11.4, 0.3,
             "Бот не увеличивает продажи — он их записывает. Цифра станет настоящей, "
             "какой бы она ни была.", 12, False, Palette.slate)
    add_footer(s, 9)


# --- 10. Итог --------------------------------------------------------------------------
def slide_summary(prs):
    s = _blank(prs)
    add_bg(s, dark=True)
    add_text(s, SAFE_L, 1.35, 8.0, 0.32, "ЧТО НУЖНО ОТ МЕНЕДЖЕРА", 11, True, Palette.muted_dark)
    add_text(s, SAFE_L, 1.8, 11.6, 0.85, "Одно нажатие вечером", 36, True, Palette.white)
    add_shape(s, MSO_SHAPE.RECTANGLE, SAFE_L, 2.85, 2.4, 0.06, Palette.teal, label="line")

    points = [
        ("Битриксу учиться не нужно", "карточки бот заполняет и двигает сам"),
        ("Заходить никуда не нужно", "сообщение приходит в Telegram, ответ — одна ссылка"),
        ("Проверить бота можно там же", "на странице видно всё, что он записал"),
        ("Ошибиться не страшно", "исход меняется, правки человека бот не трогает"),
    ]
    y = 3.35
    for title, body in points:
        add_shape(s, MSO_SHAPE.OVAL, SAFE_L + 0.02, y + 0.11, 0.15, 0.15, Palette.teal,
                  label="dot")
        add_text(s, SAFE_L + 0.42, y, 11.3, 0.32, title, 16, True, Palette.white)
        add_text(s, SAFE_L + 0.42, y + 0.33, 11.3, 0.3, body, 12.5, False, Palette.muted_dark)
        y += 0.78

    add_text(s, SAFE_L, 6.55, 11.6, 0.34,
             "Если после недели ссылками не пользуются — скажем прямо, а не будем "
             "докручивать интерфейс.", 13, True, Palette.teal)
    add_footer(s, 10, dark=True)


def main() -> None:
    prs = Presentation()
    prs.slide_width = emu(SLIDE_W)
    prs.slide_height = emu(SLIDE_H)
    for builder in (slide_title, slide_where, slide_bot_does, slide_gap, slide_change,
                    slide_message, slide_page, slide_fix, slide_rollout, slide_summary):
        builder(prs)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"готово: {OUT}  ({len(prs.slides.__iter__.__self__._sldIdLst)} слайдов)")


if __name__ == "__main__":
    main()
