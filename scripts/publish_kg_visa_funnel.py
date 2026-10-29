#!/usr/bin/env python3
"""Публикация процесса въездной визовой услуги по PDF 14.2–14.3 (V01–V25, X01–X15).

Черновик: `knowledge/kg_entry/processes_v1_1/visa-funnel-draft.json` — НЕ опубликован.
Публикует только это действие и только по слову владельца (Гриша/Алан):

    python scripts/publish_kg_visa_funnel.py                 # сухой режим: проверка и план
    python scripts/publish_kg_visa_funnel.py --yes           # публикация
    python scripts/publish_kg_visa_funnel.py --yes --dsn sqlite+aiosqlite:///x.db

Что делает с `--yes`:
  1. создаёт продукт из черновика, если его нет (direction=visa);
  2. публикует версию процесса (code, name, transitions из черновика) — она становится
     текущей у продукта; опубликованная версия неизменяема (AC-17);
  3. повторный запуск с тем же черновиком НЕ создаёт вторую версию: если текущая
     версия продукта совпадает с черновиком по этапам и переходам — ничего не пишет.

Что НЕ делает: не трогает существующие услуги, не меняет другие продукты, не включает
флаги. Ответственный/SLA/автозадачи из черновика в механизм версий не попадают
(у него нет таких полей) — они для сверки с PDF и для человека.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRAFT = ROOT / "knowledge" / "kg_entry" / "processes_v1_1" / "visa-funnel-draft.json"
FORMAT = "kg-entry-visa-funnel-draft/1"
STAGE_KEYS = {"code", "name", "pdf_page", "responsible", "sla", "auto"}


class DraftInvalid(ValueError):
    pass


def load_draft(path: Path = DRAFT) -> dict:
    """Черновик с проверкой формы. Не ходит в базу."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("format") != FORMAT:
        raise DraftInvalid(f"format must be {FORMAT}")
    if doc.get("status") != "draft_unpublished":
        raise DraftInvalid("status must be draft_unpublished")
    product = doc.get("product") or {}
    if not {"code", "name", "direction"} <= set(product) or product["direction"] != "visa":
        raise DraftInvalid("product requires code, name and direction=visa")
    stages = doc.get("stages")
    if not isinstance(stages, list) or not stages:
        raise DraftInvalid("stages must be a non-empty list")
    codes: list[str] = []
    for stage in stages:
        if not isinstance(stage, dict) or not {"code", "name", "pdf_page"} <= set(stage) \
                or not set(stage) <= STAGE_KEYS:
            raise DraftInvalid(f"bad stage: {stage!r}")
        if not isinstance(stage["pdf_page"], int) or stage["pdf_page"] <= 0:
            raise DraftInvalid(f"{stage['code']}: pdf_page must be a positive page number")
        codes.append(stage["code"])
    if len(codes) != len(set(codes)):
        raise DraftInvalid("duplicate stage codes")
    expected = [f"V{i:02d}" for i in range(1, 26)] + [f"X{i:02d}" for i in range(1, 16)]
    if codes != expected:
        raise DraftInvalid("stage codes must be exactly V01–V25 and X01–X15 in PDF order")
    transitions = doc.get("transitions")
    if not isinstance(transitions, dict) or set(transitions) != set(codes):
        raise DraftInvalid("transitions must list every stage exactly once")
    for source, targets in transitions.items():
        if not isinstance(targets, list) or any(t not in codes for t in targets) \
                or source in targets or len(targets) != len(set(targets)):
            raise DraftInvalid(f"bad transitions for {source}")
    # Та же проверка, что применит механизм при публикации.
    from app.domain.service_cases import _validate_workflow
    _validate_workflow(workflow_stages(doc), transitions)
    return doc


def workflow_stages(doc: dict) -> list[dict]:
    """Этапы в форме механизма: только code и name (см. docstring модуля)."""
    return [{"code": s["code"], "name": s["name"]} for s in doc["stages"]]


def same_as_published(version, doc: dict) -> bool:
    return (version is not None and version.published_at is not None
            and list(version.stages) == workflow_stages(doc)
            and dict(version.transitions) == dict(doc["transitions"]))


async def plan(dsn: str, doc: dict) -> dict:
    """Что будет сделано. Только чтение."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.domain.models import Product, WorkflowVersion
    engine = create_async_engine(dsn)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s:
            product = await s.scalar(select(Product).where(Product.code == doc["product"]["code"]))
            current = (await s.get(WorkflowVersion, product.current_version_id)
                       if product is not None and product.current_version_id else None)
            return {"product_exists": product is not None,
                    "product_id": product.id if product else None,
                    "current_version": current.version if current else None,
                    "already_published": same_as_published(current, doc)}
    finally:
        await engine.dispose()


async def publish(dsn: str, doc: dict, *, published_by: str) -> dict:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.domain.models import Product, WorkflowVersion
    from app.domain.permissions import Actor
    from app.domain.service_cases import create_product, publish_version
    actor = Actor(published_by, is_full_admin=True)
    engine = create_async_engine(dsn)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as s, s.begin():
            product = await s.scalar(select(Product).where(Product.code == doc["product"]["code"])
                                     .with_for_update())
            created = False
            if product is None:
                product = await create_product(s, code=doc["product"]["code"],
                                               name=doc["product"]["name"],
                                               direction="visa", by=actor)
                created = True
            current = (await s.get(WorkflowVersion, product.current_version_id)
                       if product.current_version_id else None)
            if same_as_published(current, doc):
                return {"created_product": created, "published": False,
                        "version": current.version, "reason": "already published, unchanged"}
            version = await publish_version(s, product.id, workflow_stages(doc),
                                            dict(doc["transitions"]), published_by, by=actor)
            return {"created_product": created, "published": True, "version": version.version}
    finally:
        await engine.dispose()


def run(argv: list[str] | None = None, stdout=None) -> int:
    p = argparse.ArgumentParser(description="Публикация процесса въездной визовой услуги (PDF 14.2–14.3)")
    p.add_argument("--yes", action="store_true", help="опубликовать (без флага — только проверка и план)")
    p.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""), help="строка подключения (по умолчанию DATABASE_URL)")
    p.add_argument("--draft", default=str(DRAFT))
    p.add_argument("--by", default=os.environ.get("ADMIN_USER", "admin"), help="кто публикует (полный админ)")
    args = p.parse_args(argv)
    say = (lambda m: print(m, file=stdout)) if stdout is not None else print
    try:
        doc = load_draft(Path(args.draft))
    except (DraftInvalid, OSError, ValueError) as exc:
        say(f"ЧЕРНОВИК НЕВАЛИДЕН: {exc}")
        return 2
    say(f"Черновик: {len(doc['stages'])} этапов, {sum(len(v) for v in doc['transitions'].values())} переходов, "
        f"продукт {doc['product']['code']} «{doc['product']['name']}»")
    if not args.dsn:
        say("Нет базы: задайте DATABASE_URL или --dsn.")
        return 2
    info = asyncio.run(plan(args.dsn, doc))
    say(f"  продукт в базе: {'есть, id=' + str(info['product_id']) if info['product_exists'] else 'нет — будет создан'}; "
        f"текущая версия: {info['current_version'] or 'нет'}; "
        f"{'уже опубликована без изменений' if info['already_published'] else 'будет опубликована новая версия'}")
    if not args.yes:
        say("СУХОЙ РЕЖИМ — в базу ничего не записано. Опубликовать: добавьте --yes (по слову владельца).")
        return 0
    result = asyncio.run(publish(args.dsn, doc, published_by=args.by))
    if result["published"]:
        say(f"ОПУБЛИКОВАНО: версия {result['version']}"
            + (" (продукт создан)" if result["created_product"] else ""))
    else:
        say(f"Без изменений: версия {result['version']} уже совпадает с черновиком.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
