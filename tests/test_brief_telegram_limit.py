"""ГЕЙТ: длинный бриф доходит целиком, а не отбрасывается Telegram.

Написан ДО правки, исполнителем не редактируется.

## Как нашли

11.08, отправка примера владельцу: `отправлено: False | длина: 5292`. У Telegram жёсткий
лимит 4096 символов на сообщение — всё, что длиннее, отвергается целиком, и менеджер не
получает НИЧЕГО. Не обрезанный бриф, а пустоту.

Бриф Медины в этот день: 12 задач-звонков + 8 ночных заявок. До 11.08 он умещался, а после
того как в блок «Звонки» добавилась ссылка на карточку Битрикса (+~60 знаков на клиента),
перерос лимит. То есть полезная правка молча ломала доставку — ровно тот класс аварий,
из-за которого в процессе появился закон «калибруй на реальных данных до прода».

## Что закрепляем

1. Длинный бриф разрезается на части, каждая влезает в лимит.
2. Режем по строкам: карточка клиента (телефон, ссылки) не рвётся посередине.
3. Порядок частей сохраняется, ничего не теряется.
4. Короткий бриф остаётся ОДНИМ сообщением — прежнее поведение не меняется.
"""
from __future__ import annotations

from app.core.calendar_brief import TELEGRAM_LIMIT, split_for_telegram


def _brief(cards: int) -> str:
    """Бриф той же формы, что уходит менеджеру."""
    head = "📅 План на 12.08 · Медина\nЗадач сегодня: %d\n\n📞 Звонки" % cards
    block = ("• без времени · +996 700 24 09 70\n"
             "    Автозадача: перезвонить по ночной заявке\n"
             "    💬 https://wa.me/996700240970\n"
             "    🗂 https://getvisakg.bitrix24.kz/crm/lead/details/185693/\n"
             "    https://frunzetravel.kg/admin/conversation/getvisa:996700240970")
    return head + "\n" + "\n".join([block] * cards)


def test_short_brief_stays_one_message():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: пока влезает — ничего не меняем."""
    text = _brief(3)
    assert len(text) < TELEGRAM_LIMIT
    assert split_for_telegram(text) == [text]


def test_long_brief_is_split():
    text = _brief(30)
    parts = split_for_telegram(text)
    assert len(parts) > 1
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts), [len(p) for p in parts]


def test_nothing_is_lost():
    """Каждая строка исходника обязана оказаться ровно в одной части."""
    text = _brief(30)
    parts = split_for_telegram(text)
    assert "\n".join(parts).splitlines() == text.splitlines()


def test_client_card_is_not_torn():
    """Телефон и его ссылки не должны разъехаться по разным сообщениям."""
    text = _brief(30)
    for part in split_for_telegram(text):
        lines = part.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("• без времени"):
                tail = "\n".join(lines[i:i + 5])
                assert "🗂" in tail, f"карточка оборвана:\n{tail}"


def test_single_huge_line_still_sent():
    """Одна строка длиннее лимита (гигантский комментарий) — режем, но не теряем."""
    text = "x" * (TELEGRAM_LIMIT + 500)
    parts = split_for_telegram(text)
    assert all(len(p) <= TELEGRAM_LIMIT for p in parts)
    assert "".join(parts) == text


def test_empty_input():
    assert split_for_telegram("") == []
    assert split_for_telegram("   ") == []
