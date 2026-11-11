"""ГЕЙТ: визовые воронки в реестре услуг — въездная и шенгенская.

Данные воронок лежат в черновиках, а решения заказчика о спорных переходах — вещь,
которую легко потерять при следующей правке данных. Поэтому они закреплены здесь:
каждый тест называет решение, а не просто сверяет число.

Источники:
  * въездная — PDF 14.2–14.3 плюс таблица согласований заказчика (встреча 30.10.2026,
    передана 05.11.2026);
  * шенгенская — стенограмма той же встречи; в PDF её нет вообще.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import NullPool, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain import service_cases as sc
from app.domain.models import Contact, DomainBase, Product, WorkflowVersion
from app.domain.permissions import Actor

ROOT = Path(__file__).resolve().parents[1]
ADMIN = Actor("admin", is_full_admin=True)
MEDINA = Actor("medina", allowed_directions=("visa",))


@pytest.fixture(scope="module")
def publisher():
    spec = importlib.util.spec_from_file_location(
        "publish_kg_visa_funnel", ROOT / "scripts" / "publish_kg_visa_funnel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def entry(publisher):
    return publisher.load_draft("entry")


@pytest.fixture(scope="module")
def schengen(publisher):
    return publisher.load_draft("schengen")


def _sm(tmp_path: Path):
    """Доменная БД на файле: NullPool, иначе падает на смене цикла событий."""
    url = "sqlite+aiosqlite:///" + (tmp_path / "funnels.db").as_posix()
    engine = create_async_engine(url, poolclass=NullPool)

    async def build():
        async with engine.begin() as connection:
            await connection.run_sync(DomainBase.metadata.create_all)

    asyncio.run(build())
    return url, async_sessionmaker(engine, expire_on_commit=False)


# --- A. Въездная воронка: решения заказчика ----------------------------------

def test_the_entry_draft_is_valid_and_names_the_service(entry):
    """Название услуги — ответ заказчика 3.1 от 05.11.2026."""
    assert entry["product"]["name"] == "Въездная виза"
    assert entry["product"]["direction"] == "visa"
    assert len(entry["stages"]) == 41


def test_the_review_stage_comes_before_closing(entry):
    """«Попросить отзыв» — добавление заказчика, и стоит ПЕРЕД «Завершено».

    Решение Алана 05.11.2026: отзыв просят, когда виза уже получена, потом закрытие.
    Одинаково в обеих воронках. В PDF этапа нет, поэтому у него `origin`, а не страница.
    """
    codes = [s["code"] for s in entry["stages"]]
    assert codes.index("V26") == codes.index("V25") - 1
    v26 = next(s for s in entry["stages"] if s["code"] == "V26")
    assert v26["name"] == "Попросить отзыв"
    assert "pdf_page" not in v26 and v26["origin"].strip()
    assert entry["transitions"]["V24"] == ["V26", "X10", "X11"]
    assert entry["transitions"]["V26"] == ["V25"]
    assert entry["transitions"]["V25"] == []


def test_a_new_application_is_not_a_transition(entry):
    """X01, X09, X14 терминальны: заказчик сказал про них «новая заявка», не «вернуть».

    Разница с X05 и X13 умышленная: там сказано «вернуть»/«обратно», и переходы есть.
    Прежний черновик выражал «новую заявку» переходом внутри той же заявки
    (X01 вёл в V04/V10, X09 и X14 — в V14), то есть терял связь со старой заявкой.
    """
    for code in ("X01", "X09", "X14"):
        assert entry["transitions"][code] == [], code
    assert entry["transitions"]["X05"] == ["X04", "V15"]
    assert entry["transitions"]["X13"] == ["V20"]


def test_flag_exceptions_return_to_review(entry):
    """X10 и X12 — пометки: «после них заявка возвращается в На рассмотрении» (V17)."""
    assert entry["transitions"]["X10"] == ["V17"]
    assert entry["transitions"]["X12"] == ["V17"]


def test_duplicate_and_silence_are_reachable_before_submission(entry):
    """X15 «дубль» и X07 «не отвечает» доступны из любого этапа до подачи (V16)."""
    for i in range(1, 16):
        code = "V%02d" % i
        assert "X07" in entry["transitions"][code], code
        assert "X15" in entry["transitions"][code], code
    # После подачи их нет: заявка уже в работе у госоргана.
    for code in ("V16", "V17", "V20", "V25"):
        assert "X15" not in entry["transitions"][code], code


def test_cancellation_matches_the_owner_table(entry):
    """X02 — из V06–V10 и V14; X03 — из V16–V18; X06 — из V10, V11, V13."""
    for code in ["V06", "V07", "V08", "V09", "V10", "V14"]:
        assert "X02" in entry["transitions"][code], code
    for code in ["V16", "V17", "V18"]:
        assert "X03" in entry["transitions"][code], code
    for code in ["V10", "V11", "V13"]:
        assert "X06" in entry["transitions"][code], code
    # «дальше закрыть или вернуть в сбор»
    assert entry["transitions"]["X06"] == ["X07", "V10"]


def test_entry_codes_and_names_match_the_pdf_catalog(entry):
    """Воронка и каталог PDF не должны разойтись молча.

    Каталог — машинное прочтение PDF 14.2–14.3; воронка — то, что увидит менеджер.
    Единственное расхождение, которое разрешено, — добавленный заказчиком V26.
    """
    catalog = json.loads((ROOT / "knowledge" / "kg_entry" / "processes_v1_1"
                          / "catalog.json").read_text(encoding="utf-8"))
    from_pdf = {s["code"]: s["name"] for s in catalog["stages"]
                if s["code"][0] in "VX" and not s["code"].startswith("VX")}
    in_funnel = {s["code"]: s["name"] for s in entry["stages"]}
    assert set(in_funnel) - set(from_pdf) == {"V26"}
    assert set(from_pdf) - set(in_funnel) == set()
    # Пробелы нормализуем: в каталоге имя V11 вышло из PDF как «(флаг/ подстатус)»,
    # в воронке — «(флаг/подстатус)». Это оформление, а не другой этап.
    def tidy(text: str) -> str:
        return " ".join(text.replace("/ ", "/").split())

    for code, name in from_pdf.items():
        assert tidy(in_funnel[code]) == tidy(name), code


# --- B. Шенгенская воронка ---------------------------------------------------

def test_the_schengen_draft_keeps_the_owner_words(schengen):
    """Лист ожидания и запись — две стадии с перескоком; подготовка — одна стадия.

    Прямые цитаты со встречи 30.10: «первой воронкой идёт лист ожидания, второй —
    клиент записан; если сразу записала, то через воронку она прыгает» и «это всё в
    одной воронке может быть, да? Вот в одной воронке».

    11.11.2026 воронка пересобрана по письменным ответам Медины, и перескок переехал:
    список документов она отдаёт СРАЗУ после договора и предоплаты, «независимо от
    того, записан он на подачу или ещё ожидает свободную дату» (вопрос 9). Поэтому
    развилка «лист ожидания или сразу запись» теперь стоит после SCH-03, а не после
    договора. Обе цитаты заказчика при этом сохранены — они и проверяются здесь.
    """
    assert schengen["product"]["code"] == "visa_schengen"
    work = [s for s in schengen["stages"] if s["code"].startswith("SCH-")]
    assert len(work) == 14
    # Перескок: из сбора документов можно в лист ожидания, а можно прямо в запись.
    assert schengen["transitions"]["SCH-03"][:2] == ["SCH-04", "SCH-05"]
    assert schengen["transitions"]["SCH-04"][0] == "SCH-05"
    # Список документов стоит ДО записи — ответ Медины отменил прежнее допущение.
    names = [s["name"] for s in work]
    assert names.index("Список документов передан клиенту, клиент собирает") \
        < names.index("Клиент записан на подачу документов")
    # Брони, страховка, переводы и анкета — одна стадия, а не четыре.
    six = next(s for s in work if s["code"] == "SCH-06")
    assert six["name"] == "Подготовка документов"
    assert "бронирование отеля" in six["origin"].lower()
    assert [s["name"] for s in work[-2:]] == ["Попросить отзыв", "Завершено"]


def test_the_interview_stage_can_be_skipped(schengen):
    """Собеседование по шенгену Медина не называет — значит этап необязателен.

    В её воронке США собеседование есть двумя стадиями, а в шенгенской нет вовсе.
    Удалять этап по молчанию нельзя (на встрече 30.10 заказчик его называл), поэтому
    из финальной проверки разрешены оба пути: через SCH-08 и мимо него. Вопрос ей
    задан — до ответа держим обе дороги.
    """
    assert schengen["transitions"]["SCH-07"][:2] == ["SCH-08", "SCH-09"]
    assert "НЕТ" in next(s for s in schengen["stages"]
                         if s["code"] == "SCH-08")["origin"]


def test_every_schengen_stage_says_where_it_came_from(schengen):
    """В PDF воронки нет совсем, поэтому источник обязан быть у каждого этапа.

    Что откуда взято, должно читаться в данных, а не только в отчёте. После ответов
    Медины 11.11 источники разделились на три вида, и все три обязаны быть видны:
    слова заказчика со встречи, письменный ответ менеджера и то, что по-прежнему
    держится на реконструкции исполнителя.
    """
    for stage in schengen["stages"]:
        assert stage["origin"].strip(), stage["code"]
        assert "pdf_page" not in stage, stage["code"]
    by_manager = {s["code"] for s in schengen["stages"] if "Медины" in s["origin"]}
    # Этапы, которых в черновике 05.11 не было вовсе — они появились из её ответов.
    assert {"SCH-02", "SCH-10", "SCH-11"} <= by_manager
    guessed = {s["code"] for s in schengen["stages"]
               if "требует подтверждения" in s["origin"]}
    # Исключения она не описывала — они так и остались реконструкцией.
    assert {"X02", "X03", "X07"} <= guessed


# --- C. Публикация и проход заявки ------------------------------------------

def test_publishing_both_funnels_and_advancing_a_case(publisher, tmp_path):
    """Менеджер может провести заявку вперёд ровно разрешёнными переходами."""
    url, sm = _sm(tmp_path)
    entry_doc = publisher.load_draft("entry")
    result = asyncio.run(publisher.publish(url, entry_doc, published_by="admin"))
    assert result["published"] and result["created_product"]

    async def walk():
        async with sm() as session, session.begin():
            contact = Contact()
            session.add(contact)
            await session.flush()
            product = await session.scalar(
                select(Product).where(Product.code == "kg_entry_visa"))
            version = await session.get(WorkflowVersion, product.current_version_id)
            case = await sc.open_case(session, contact_id=contact.id,
                                      product_id=product.id, owner_login="medina",
                                      by=ADMIN)
            assert case.stage == "V01"
            seen = []
            for to_stage in ("V02", "V04", "V06"):
                case = await sc.advance(session, case.id, to_stage=to_stage, by=MEDINA)
                seen.append(case.stage)
            assert seen == ["V02", "V04", "V06"]
            plan = sc.stage_plan(version, case.stage)
            assert plan["index"] == 5 and plan["total"] == 41
            assert plan["name"] == "КП отправлено"
            with pytest.raises(sc.DomainError):
                await sc.advance(session, case.id, to_stage="V20", by=MEDINA)

    asyncio.run(walk())


def test_republishing_the_same_draft_does_not_create_a_second_version(publisher,
                                                                      tmp_path):
    """Повторный запуск не плодит версии: подписанные услуги держатся за свою (AC-17)."""
    url, sm = _sm(tmp_path)
    doc = publisher.load_draft("entry")
    assert asyncio.run(publisher.publish(url, doc, published_by="admin"))["published"]
    again = asyncio.run(publisher.publish(url, doc, published_by="admin"))
    assert again["published"] is False and again["version"] == 1

    async def count():
        async with sm() as session:
            return await session.scalar(select(func.count()).select_from(WorkflowVersion))

    assert int(asyncio.run(count())) == 1


def test_schengen_publishes_onto_the_product_that_already_exists(publisher, tmp_path):
    """Выездному продукту механизм подходит без изменений.

    `visa_schengen` уже заведён в INITIAL_PRODUCTS и живёт без версии процесса — то
    есть завести по нему заявку нельзя. Публикация не должна создавать второй продукт.
    """
    url, sm = _sm(tmp_path)

    async def seed():
        async with sm() as session, session.begin():
            await sc.seed_products(session, published_by="admin", by=ADMIN)
            product = await session.scalar(
                select(Product).where(Product.code == "visa_schengen"))
            assert product.current_version_id is None
            contact = Contact()
            session.add(contact)
            await session.flush()
            with pytest.raises(sc.DomainError):
                await sc.open_case(session, contact_id=contact.id,
                                   product_id=product.id, owner_login="medina",
                                   by=ADMIN)

    asyncio.run(seed())
    doc = publisher.load_draft("schengen")
    result = asyncio.run(publisher.publish(url, doc, published_by="admin"))
    assert result["published"] and result["created_product"] is False

    async def check():
        async with sm() as session, session.begin():
            count = await session.scalar(select(func.count()).select_from(Product)
                                         .where(Product.code == "visa_schengen"))
            assert int(count) == 1
            product = await session.scalar(
                select(Product).where(Product.code == "visa_schengen"))
            version = await session.get(WorkflowVersion, product.current_version_id)
            codes = [s["code"] for s in version.stages]
            assert codes[:3] == ["SCH-01", "SCH-02", "SCH-03"]
            contact = Contact()
            session.add(contact)
            await session.flush()
            case = await sc.open_case(session, contact_id=contact.id,
                                      product_id=product.id, owner_login="medina",
                                      by=ADMIN)
            # Договор → предоплата → список документов, затем перескок листа
            # ожидания: из сбора документов можно сразу в запись на подачу.
            case = await sc.advance(session, case.id, to_stage="SCH-02", by=MEDINA)
            case = await sc.advance(session, case.id, to_stage="SCH-03", by=MEDINA)
            case = await sc.advance(session, case.id, to_stage="SCH-05", by=MEDINA)
            assert case.stage == "SCH-05"

    asyncio.run(check())
