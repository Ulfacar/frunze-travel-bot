"""Черновик процесса въездной визовой услуги (PDF 14.2–14.3) и его публикация.

Черновик не опубликован; публикует только `scripts/publish_kg_visa_funnel.py --yes`.
"""
import asyncio
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from scripts import publish_kg_visa_funnel as pub

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def dsn(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}"

    async def build():
        from app.domain.models import DomainBase
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)
        await engine.dispose()
    asyncio.run(build())
    return url


def _rows(dsn):
    from app.domain.models import Product, WorkflowVersion

    async def q():
        engine = create_async_engine(dsn, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as s:
                products = (await s.scalars(select(Product))).all()
                versions = (await s.scalars(select(WorkflowVersion).order_by(WorkflowVersion.id))).all()
                return ([(p.code, p.direction, p.current_version_id) for p in products],
                        [(v.product_id, v.version, v.published_at is not None, v.stages, v.transitions, v.id) for v in versions])
        finally:
            await engine.dispose()
    return asyncio.run(q())


# --- черновик ----------------------------------------------------------------------

def test_draft_is_valid_and_matches_pdf_codes():
    doc = pub.load_draft()
    assert doc["status"] == "draft_unpublished"
    codes = [s["code"] for s in doc["stages"]]
    assert codes == [f"V{i:02d}" for i in range(1, 26)] + [f"X{i:02d}" for i in range(1, 16)]
    assert all(62 <= s["pdf_page"] <= 64 for s in doc["stages"])
    # Явные переходы PDF 14.2 присутствуют.
    t = doc["transitions"]
    for src, dst in [("V01", "V02"), ("V02", "V04"), ("V02", "V03"), ("V03", "X08"), ("V04", "V06"),
                     ("V04", "V05"), ("V06", "V07"), ("V10", "V12"), ("V10", "X06"), ("V12", "V13"),
                     ("V13", "V12"), ("V15", "X09"), ("V17", "V20"), ("V17", "V18"), ("V17", "X01"),
                     ("V18", "V19"), ("V19", "V17"), ("V21", "X13"), ("V21", "X14"), ("V24", "V25"),
                     ("X05", "X04"), ("X08", "V04")]:
        assert dst in t[src], (src, dst)
    assert t["V25"] == [] and t["X15"] == []


def test_draft_does_not_contain_fields_the_mechanism_cannot_take():
    doc = pub.load_draft()
    for stage in pub.workflow_stages(doc):
        assert set(stage) == {"code", "name"}


@pytest.mark.parametrize("mutate", [
    lambda d: d["stages"].pop(),                                   # не хватает X15
    lambda d: d["transitions"].__setitem__("V25", ["V25"]),        # самопереход
    lambda d: d["transitions"].__setitem__("V01", ["ZZZ"]),        # неизвестный этап
    lambda d: d.__setitem__("status", "published"),
    lambda d: d["stages"][0].__setitem__("sla_minutes", 5),         # чужое поле
])
def test_invalid_drafts_are_rejected(tmp_path, mutate):
    doc = json.loads(pub.DRAFT.read_text(encoding="utf-8"))
    mutate(doc)
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(pub.DraftInvalid):
        pub.load_draft(path)


# --- публикация ---------------------------------------------------------------------

def test_dry_run_writes_nothing(dsn, capsys):
    rc = pub.run(["--dsn", dsn])
    out = capsys.readouterr().out
    assert rc == 0 and "СУХОЙ РЕЖИМ" in out and "будет создан" in out
    products, versions = _rows(dsn)
    assert products == [] and versions == []


def test_publish_creates_product_and_one_immutable_version(dsn, capsys):
    assert pub.run(["--dsn", dsn, "--yes", "--by", "admin"]) == 0
    assert "ОПУБЛИКОВАНО: версия 1" in capsys.readouterr().out
    products, versions = _rows(dsn)
    assert len(products) == 1 and products[0][:2] == ("kg_entry_visa", "visa")
    assert products[0][2] == versions[0][5]           # текущая версия продукта — опубликованная
    assert len(versions) == 1 and versions[0][1] == 1 and versions[0][2] is True
    assert [s["code"] for s in versions[0][3]][:3] == ["V01", "V02", "V03"]
    # Повтор — без второй версии.
    assert pub.run(["--dsn", dsn, "--yes", "--by", "admin"]) == 0
    assert "Без изменений" in capsys.readouterr().out
    assert len(_rows(dsn)[1]) == 1
    # Опубликованная версия неизменяема: повторная публикация той же версии отвергается.
    from app.domain.models import DomainError
    from app.domain.permissions import Actor
    from app.domain.service_cases import publish_version

    async def republish():
        engine = create_async_engine(dsn, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine)() as s, s.begin():
                from app.domain.models import WorkflowVersion
                version = await s.scalar(select(WorkflowVersion))
                doc = pub.load_draft()
                await publish_version(s, version.product_id, pub.workflow_stages(doc),
                                      dict(doc["transitions"]), "admin",
                                      by=Actor("admin", True), version_id=version.id)
        finally:
            await engine.dispose()
    with pytest.raises(DomainError):
        asyncio.run(republish())


def test_changed_draft_publishes_new_version_old_stays(dsn, tmp_path, capsys):
    assert pub.run(["--dsn", dsn, "--yes"]) == 0
    doc = json.loads(pub.DRAFT.read_text(encoding="utf-8"))
    doc["transitions"]["X15"] = ["V01"]            # владелец добавил возврат
    path = tmp_path / "draft2.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    assert pub.run(["--dsn", dsn, "--yes", "--draft", str(path)]) == 0
    products, versions = _rows(dsn)
    assert [v[1] for v in versions] == [1, 2]
    assert versions[0][4]["X15"] == [] and versions[1][4]["X15"] == ["V01"]
    assert products[0][2] == versions[1][5]           # текущая версия продукта — новая
