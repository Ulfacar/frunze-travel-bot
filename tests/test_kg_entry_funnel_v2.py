# -*- coding: utf-8 -*-
"""Въездная воронка после устных правок Гриши 05.11.2026.

Он убрал три этапа прямо в разговоре. Эти правки месяц лежали неприменёнными, и
главный риск теперь обратный: кто-нибудь сверит рабочую версию с PDF, увидит «не
хватает трёх этапов» и вернёт их как потерю. Поэтому тест держит обе стороны —
и что убранного нет в рабочей версии, и что исходный черновик по PDF не тронут.
"""
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAFT = ROOT / "knowledge" / "kg_entry" / "processes_v1_1" / "visa-funnel-draft.json"
WORK = ROOT / "knowledge" / "kg_entry" / "visa-funnel-work-v2.json"

REMOVED = {"V08", "V11", "V15"}


def _load(path):
    if not path.exists():
        pytest.skip(f"нет файла {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def work():
    return _load(WORK)


@pytest.fixture(scope="module")
def draft():
    return _load(DRAFT)


def test_the_three_stages_he_removed_are_gone(work):
    codes = {s["code"] for s in work["stages"]}
    assert not (codes & REMOVED), "этап, который Гриша убрал, вернулся в рабочую версию"


def test_each_removed_stage_keeps_his_own_words(work):
    """Цитата важнее кода: по ней правку можно перепроверить в записи."""
    retired = {r["code"]: r["quote"] for r in work["retired_codes"]}
    assert set(retired) == REMOVED
    assert "без счёта" in retired["V08"].lower()
    assert "приглашающую сторону" in retired["V11"].lower()
    assert "черновик" in retired["V15"].lower()


def test_the_other_codes_keep_their_numbers(work, draft):
    """Перенумерация молча перенаправила бы ссылки из 13–20 файлов на другой этап."""
    was = {s["code"]: s["name"] for s in draft["stages"]}
    for stage in work["stages"]:
        assert stage["code"] in was, f"код {stage['code']} появился из ниоткуда"
        assert stage["name"] == was[stage["code"]], (
            f"{stage['code']} сменил название при переносе")


def test_the_pdf_draft_itself_is_untouched(draft):
    """Черновик по PDF — добросовестный перенос документа, его правят только по документу."""
    codes = {s["code"] for s in draft["stages"]}
    assert REMOVED <= codes, "из черновика по PDF убрали этапы — так нельзя"
    assert len(draft["stages"]) == 41


def test_both_modes_of_movement_are_recorded(work):
    """Его слова: «она будет сама двигать, либо автоматически», можно перепрыгивать."""
    movement = work["movement"]
    assert movement["manual"] and movement["auto"]
    assert movement["skip_allowed"] is True


def test_the_work_version_is_not_marked_published(work):
    """Публикация в боевую CRM — отдельное решение владельца, не побочный эффект сборки."""
    assert work["status"] == "work_draft_unpublished"


def test_the_exceptions_survived_in_full(work):
    """Пятнадцать исключений X01–X15 он подтвердил целиком, их трогать не просили."""
    x = sorted(s["code"] for s in work["stages"] if s["code"].startswith("X"))
    assert x == [f"X{i:02d}" for i in range(1, 16)]


def test_the_work_funnel_is_copied_into_the_image():
    """Без строки COPY файл не доедет до контейнера, а /health останется зелёным.

    В Dockerfile про это стоит предупреждение рядом с черновиком: публикация тогда
    падает на «черновик невалиден», и причина не видна. Проверено на выкате 13.11:
    файла в образе не было.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "visa-funnel-work-v2.json" in dockerfile
