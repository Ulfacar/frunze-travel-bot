#!/usr/bin/env python3
"""Публикация визовых воронок в реестр услуг: въездной и шенгенской.

Черновики (оба НЕ опубликованы):
  * `knowledge/kg_entry/processes_v1_1/visa-funnel-draft.json` — въездная виза,
    PDF 14.2–14.3 (V01–V25, X01–X15) плюс добавленный заказчиком V26 «Попросить отзыв»;
  * `knowledge/funnels/schengen-funnel-draft.json` — шенген после договора
    (SCH-01–SCH-11 + исключения), по стенограмме встречи 30.10.2026.

Обе воронки едут одним механизмом (`service_cases.publish_version`): версия процесса
привязана к продукту, поэтому выездному продукту он подходит без изменений.

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

# Закрытый список полей этапа: опечатка в имени поля должна падать на проверке
# черновика, а не превращаться в молча проигнорированное правило. `pdf_page` — для
# этапов из PDF, `origin` — для добавленных заказчиком (чего в PDF нет).
STAGE_KEYS = {"code", "name", "pdf_page", "origin", "responsible", "sla", "auto"}

ENTRY_CODES = ([f"V{i:02d}" for i in range(1, 25)] + ["V26", "V25"]
               + [f"X{i:02d}" for i in range(1, 16)])
# 11.11.2026: было SCH-01..SCH-11. Пересобрано по письменным ответам Медины —
# добавлены «Предоплата получена», «Документы на рассмотрении», «Паспорт готов к
# выдаче» и выдача отдельной стадией, а список документов переехал ВПЕРЁД записи
# (её ответ на вопрос 9 отменил прежнее допущение). Замок обновлён вместе с
# данными осознанно: ради этого он и заведён.
SCHENGEN_CODES = ([f"SCH-{i:02d}" for i in range(1, 15)]
                  + ["X01", "X02", "X03", "X06", "X07"])
# Воронка США пересобрана 11.11.2026 по ответам Медины (вопросы 13 и 14). Прежняя
# версия в базе — девять линейных этапов из ТЗ 01.10 без единого исключения: отказ и
# отмена там не моделировались вовсе. Коды X общие с шенгеном, чтобы два визовых
# процесса читались одинаково.
USA_CODES = ([f"USA-{i:02d}" for i in range(1, 18)]
             + ["X01", "X02", "X03", "X06", "X07"])
# Общая визовая воронка: Китай, Корея, Япония (ответ Медины на вопрос 15 — «общая
# воронка с индивидуальными задачами для каждой страны»). Публикуется на каждый
# продукт ключом --product. Италия сюда не входит: она идёт по шенгенской.
GENERIC_CODES = ([f"VIS-{i:02d}" for i in range(1, 12)]
                 + ["X01", "X02", "X03", "X06", "X07"])

# Воронка = черновик + формат + ЗАМОК на состав и порядок кодов этапов. Замок нужен,
# чтобы добавление или потеря этапа были видны в диффе кода, а не проезжали молча
# вместе с правкой данных.
FUNNELS = {
    "entry": {
        "draft": ROOT / "knowledge" / "kg_entry" / "processes_v1_1" / "visa-funnel-draft.json",
        "format": "kg-entry-visa-funnel-draft/1",
        "codes": ENTRY_CODES,
    },
    "schengen": {
        "draft": ROOT / "knowledge" / "funnels" / "schengen-funnel-draft.json",
        "format": "visa-funnel-draft/1",
        "codes": SCHENGEN_CODES,
    },
    "usa": {
        "draft": ROOT / "knowledge" / "funnels" / "usa-funnel-draft.json",
        "format": "visa-funnel-draft/1",
        "codes": USA_CODES,
    },
    "generic": {
        "draft": ROOT / "knowledge" / "funnels" / "visa-generic-funnel-draft.json",
        "format": "visa-funnel-draft/1",
        "codes": GENERIC_CODES,
    },
}


class DraftInvalid(ValueError):
    pass


def load_draft(funnel: str = "entry", path: Path | None = None) -> dict:
    """Черновик воронки с проверкой формы. Не ходит в базу."""
    spec = FUNNELS[funnel]
    doc = json.loads(Path(path or spec["draft"]).read_text(encoding="utf-8"))
    if doc.get("format") != spec["format"]:
        raise DraftInvalid(f"format must be {spec['format']}")
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
        if (not isinstance(stage, dict) or not {"code", "name"} <= set(stage)
                or not set(stage) <= STAGE_KEYS):
            raise DraftInvalid(f"bad stage: {stage!r}")
        page = stage.get("pdf_page")
        origin = str(stage.get("origin") or "").strip()
        if not origin and (not isinstance(page, int) or page <= 0):
            raise DraftInvalid(f"{stage['code']}: нужен pdf_page (этап из PDF)"
                               f" либо origin (этап не из PDF — откуда он)")
        codes.append(stage["code"])
    if len(codes) != len(set(codes)):
        raise DraftInvalid("duplicate stage codes")
    expected = spec["codes"]
    if codes != expected:
        raise DraftInvalid("состав и порядок кодов этапов должны совпадать с замком воронки " + funnel)
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
    p = argparse.ArgumentParser(description="Публикация визовых воронок (въездная, шенген)")
    p.add_argument("--yes", action="store_true", help="опубликовать (без флага — только проверка и план)")
    p.add_argument("--dsn", default=os.environ.get("DATABASE_URL", ""), help="строка подключения (по умолчанию DATABASE_URL)")
    p.add_argument("--funnel", choices=sorted(FUNNELS), default="entry",
                   help="какую воронку публиковать")
    p.add_argument("--draft", default="", help="путь к черновику (по умолчанию — из реестра)")
    p.add_argument("--product", default="",
                   help="опубликовать этот же процесс на ДРУГОЙ продукт (его код). "
                        "Нужен для стран, которые по ответу Медины (вопрос 15) идут по "
                        "общей воронке: один черновик — несколько продуктов, вместо "
                        "копий файла, которые разойдутся на первой же правке")
    p.add_argument("--by", default=os.environ.get("ADMIN_USER", "admin"), help="кто публикует (полный админ)")
    args = p.parse_args(argv)
    say = (lambda m: print(m, file=stdout)) if stdout is not None else print
    try:
        doc = load_draft(args.funnel, Path(args.draft) if args.draft else None)
    except (DraftInvalid, OSError, ValueError) as exc:
        say(f"ЧЕРНОВИК НЕВАЛИДЕН: {exc}")
        return 2
    if args.product:
        # Название берём из каталога продуктов, а не выдумываем: у одного продукта не
        # должно появиться двух имён (та же причина, что в note черновика).
        from app.domain.service_cases import INITIAL_PRODUCTS
        known = {code: (name, direction) for code, name, direction in INITIAL_PRODUCTS}
        if args.product not in known:
            say(f"НЕИЗВЕСТНЫЙ ПРОДУКТ: {args.product} (есть: {', '.join(sorted(known))})")
            return 2
        name, direction = known[args.product]
        if direction != doc["product"]["direction"]:
            say(f"НАПРАВЛЕНИЕ НЕ СОВПАДАЕТ: {args.product} это {direction}, "
                f"а воронка для {doc['product']['direction']}")
            return 2
        doc = {**doc, "product": {**doc["product"], "code": args.product, "name": name}}
        say(f"продукт переопределён ключом --product: {args.product} «{name}»")
    say(f"Воронка {args.funnel}: {len(doc['stages'])} этапов, "
        f"{sum(len(v) for v in doc['transitions'].values())} переходов, "
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
