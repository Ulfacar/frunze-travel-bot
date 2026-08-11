"""ГЕЙТ: ответ про рабочую визу за границу не заканчивается тупиком.

Написан ДО правки, исполнителем не редактируется.

## Что происходит сейчас (живой диалог с прода, getvisa:996708011087)

    клиент: В Америку рабочую визу делаете?
    бот:    Рабочими визами мы не занимаемся — для них нужно приглашение от работодателя,
            это отдельная услуга. Помогаем с туристическими, гостевыми, деловыми и учебными
            визами (например, США — B1/B2, F1, M1) по нашим направлениям.

Формально верно — и разговор кончается. Со встречи 11.08, Даулет дословно: «Мы можем
сказать, что нет, но есть другие способы уехать… и тогда пригласить на консультацию», и там
же: «Просто уже третий, четвёртый человек приходит».

## Что закрепляем

1. Обещания рабочей визы за границу нет ни в одном варианте ответа.
2. Ответ не обрывается отказом: клиенту назван реальный следующий шаг — консультация по тем
   визам, которые фирма правда делает.
3. Ложноположительный контур: обычные визовые ответы этой правкой не задеты.
"""
from __future__ import annotations

import asyncio
import re

from app.agent.validator import SAFE_WORKVISA_REPLY, validate_reply
from app.core import faq

_WORK_VISA = re.compile(r"рабоч\w*\s+виз", re.IGNORECASE)
_DENIAL = re.compile(r"\bне\b|\bнет\b|к сожалению|нельзя", re.IGNORECASE)
_NEXT_STEP = re.compile(r"консультац|подберём|подберем|разбер|посмотрим|подскаж|запис",
                        re.IGNORECASE)


def _promises_work_visa(text: str) -> bool:
    """Есть ли предложение, где рабочая виза упомянута БЕЗ отрицания.

    Проверять одной регуляркой «глагол рядом с рабочей визой» нельзя: «рабочие визы мы НЕ
    оформляем» попадает в неё так же, как «оформим рабочую визу». Различает их только
    отрицание, поэтому смотрим по предложениям — ровно как это делает сам валидатор.
    """
    for sentence in re.split(r"[.!?\n]+", text):
        if _WORK_VISA.search(sentence) and not _DENIAL.search(sentence):
            return True
    return False


def _work_visa_faq_answer() -> str:
    """Ответ так, как он попадёт на прод: засеиваем правила тем же кодом, что и приложение."""
    async def _seed():
        faq.reset()
        await faq.seed_defaults()
        return await faq.get_faq_store().list(include_disabled=True)

    for entry in asyncio.run(_seed()):
        if getattr(entry, "title", "") == "Рабочие визы":
            return entry.answer
    raise AssertionError("правило FAQ «Рабочие визы» исчезло — гейт обязан это заметить")


def test_safe_reply_promises_no_foreign_work_visa():
    assert not _promises_work_visa(SAFE_WORKVISA_REPLY)


def test_safe_reply_offers_a_next_step():
    """Главное изменение: после честного «нет» обязан идти следующий ход, а не точка."""
    assert _NEXT_STEP.search(SAFE_WORKVISA_REPLY), SAFE_WORKVISA_REPLY


def test_safe_reply_names_what_we_actually_do():
    assert re.search(r"туристич|гостев|делов|учебн", SAFE_WORKVISA_REPLY, re.IGNORECASE)


def test_faq_answer_matches_the_same_rules():
    """FAQ отвечает раньше LLM — расхождение между ними и есть источник разнобоя."""
    answer = _work_visa_faq_answer()
    assert not _promises_work_visa(answer)
    assert _NEXT_STEP.search(answer), answer


def test_validator_still_replaces_a_work_visa_promise():
    """Модель пообещала рабочую визу — подменяем на безопасный ответ."""
    text, violations = validate_reply(
        "Да, конечно, мы оформим вам рабочую визу в США за две недели.", "visa")
    assert "work_visa_offer_blocked" in violations
    assert not _promises_work_visa(text)
    assert _NEXT_STEP.search(text)


def test_validator_keeps_honest_refusal_intact():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: честный отказ подменять незачем — он уже правильный."""
    # Без тире: « — » валидатор штатно заменяет на «. » во всех ответах, и это к рабочим
    # визам отношения не имеет.
    honest = ("Рабочие визы за границу мы не оформляем, но можем посмотреть учебную или "
              "деловую, приходите на консультацию.")
    text, violations = validate_reply(honest, "visa")
    assert "work_visa_offer_blocked" not in violations
    assert text.strip() == honest


def test_ordinary_visa_answer_is_untouched():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: туристическая виза — обычный ответ, правка его не касается."""
    plain = "По США делаем туристическую B1/B2: поможем с анкетой и подготовим к интервью."
    text, violations = validate_reply(plain, "visa")
    assert text.strip() == plain
    assert "work_visa_offer_blocked" not in violations
