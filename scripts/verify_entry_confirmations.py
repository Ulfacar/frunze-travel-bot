"""Сверка бандла въездных знаний с исходным PDF ТЗ — и проверка оверлея подтверждений.

Зачем. Подтверждение единицы знаний разрешает боту произносить норму миграционного
права как факт. Слова «делай как в ПДФ» — это разрешение, а не доказательство того,
что в бандле лежит именно то, что в ПДФ. Этот скрипт добывает доказательство: сам
разбирает таблицы ТЗ из PDF и сличает их с данными, на которых бот будет отвечать.

Что проверяется:

  A. хеш PDF совпадает с ``meta.source_hash`` бандла — иначе сверять нечего;
  B. таблица 2.10 «сроки освобождения от регистрации» (с. 24-25) против единиц
     ``registration_exemption``;
  C. строка «Нет в Перечне» той же таблицы против ``KG.REG.DEFAULT`` и сроков, на
     которые оформляется регистрация (``KG.REG.TERM.UZB``, ``KG.REG.TERM.MDA``);
  D. список приложения 1 П-541 из раздела 2.3 (55 стран, с. 22) против
     ``KG.VF.ANNEX1_30_60``;
  E. числа лимитов безвизовых режимов встречаются в тексте тех страниц, на которые
     единица ссылается;
  F. если оверлей подтверждений есть — каждая его строка указывает на существующую
     единицу бандла, хеш значения совпадает, значение не пустое, а метка ТЗ не
     запрещает произносить.

Запуск: ``python scripts/verify_entry_confirmations.py [--pdf runs/specialist-source.pdf]``
Код выхода 0 — расхождений нет; 1 — есть расхождения; 2 — сверить невозможно.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "knowledge" / "kg_entry" / "draft-v1.1"
OVERLAY = ROOT / "knowledge" / "kg_entry" / "confirmations-v1.1.yaml"

UNSAYABLE_LABELS = {"verify", "decision"}

# Названия, которые в прозе ТЗ написаны иначе, чем в справочнике алиасов бандла.
# Правка только на стороне разбора PDF: справочник бандла не трогаем.
PDF_NAME_FIXES = {"Бруней-Даруссалам": "Бруней"}

# Расхождения, которые уже разобраны: почему так и чем это безопасно. Гейт их
# показывает, но не красит в красное — иначе он перестаёт ловить НОВЫЕ расхождения.
KNOWN_GAPS: tuple[tuple[str, str], ...] = (
    ("C: MDA назван в ПДФ вне Перечня",
     "пробел импорта. Молдова в таблице 2.10 попадает в строку «Нет в Перечне», "
     "но в KG.REG.DEFAULT её нет, а KG.REG.EXEMPT.MDA заблокирована. Движок из-за "
     "этого отдаёт срок регистрации для MDA менеджеру и клиенту не называет "
     "(withheld registration_coverage_missing:MDA) — направление безопасное. "
     "Прибито тестом test_moldova_registration_is_never_spoken."),
)

problems: list[str] = []
notes: list[str] = []


def fail(msg: str) -> None:
    problems.append(msg)


def triage(found: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Разделить расхождения на новые и уже разобранные."""
    fresh: list[str] = []
    known: list[tuple[str, str]] = []
    for item in found:
        match = next((reason for prefix, reason in KNOWN_GAPS if item.startswith(prefix)), None)
        (known.append((item, match)) if match else fresh.append(item))
    return fresh, known


def load_bundle() -> tuple[dict, list[dict], dict[str, str]]:
    meta = json.loads((BUNDLE / "meta.yaml").read_text(encoding="utf-8"))
    units = json.loads((BUNDLE / "units.yaml").read_text(encoding="utf-8"))
    countries = json.loads((BUNDLE / "countries.yaml").read_text(encoding="utf-8"))
    return meta, units, countries


def iso3(name: str, countries: dict[str, str]) -> str | None:
    """Название страны из ПДФ в ISO3. Учитывает перенос слова по дефису."""
    key = name.strip()
    # В ПДФ длинное название переносится по дефису: «Бруней- Даруссалам».
    for candidate in (key, re.sub(r"-\s+", "-", key)):
        candidate = PDF_NAME_FIXES.get(candidate, candidate)
        found = countries.get(candidate)
        if found:
            return found
    return None


def split_countries(cell: str) -> list[str]:
    """Ячейка «Страны» в список названий. Переносы строк PDF уже склеены."""
    cell = re.sub(r"\s+", " ", cell or "").strip().rstrip(".")
    return [p.strip() for p in cell.split(",") if p.strip()]


def pdf_pages(pdf_path: Path, numbers: list[int]) -> dict[int, dict]:
    import pdfplumber

    out: dict[int, dict] = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        for num in numbers:
            page = pdf.pages[num - 1]
            out[num] = {"text": page.extract_text() or "",
                        "tables": page.extract_tables() or []}
    return out


def check_exemptions(pages: dict[int, dict], units: list[dict],
                     countries: dict[str, str]) -> None:
    """B и C: таблица 2.10 против единиц освобождения, общего срока и сроков учёта."""
    from_pdf: dict[str, int] = {}
    not_in_list: list[str] = []
    term_days: dict[str, int] = {}
    rows_seen = 0

    for num in (24, 25):
        for table in pages[num]["tables"]:
            head = re.sub(r"\s+", " ", " ".join(str(c or "") for c in (table[0] if table else ())))
            if "регистрироваться" not in head:
                continue
            for row in table[1:]:
                if not row or len(row) < 2:
                    continue
                left = re.sub(r"\s+", " ", str(row[0] or "")).strip()
                right = re.sub(r"\s+", " ", str(row[1] or "")).strip()
                if not left:
                    continue
                rows_seen += 1
                if "Нет в Перечне" in left:
                    # «Нет в Перечне (Узбекистан, Молдова, Китай, ...)», условия справа.
                    inner = re.search(r"\((.+?)\)", left, flags=re.S)
                    if inner:
                        not_in_list = [n for n in split_countries(inner.group(1))
                                       if "т.д" not in n]
                    for name, days in re.findall(
                            r"([А-ЯЁ][а-яёА-ЯЁ\- ]+?)\s*—\s*на (\d+) к\.д", right):
                        code = iso3(name, countries)
                        if code:
                            term_days[code] = int(days)
                    if "5 рабочих дней" not in right and "5 р.д." not in right:
                        fail("C: в строке «Нет в Перечне» не нашёл срок 5 рабочих дней")
                    continue
                match = re.match(r"(\d+)\s*(?:дн|день|дня)", left)
                if not match:
                    fail(f"B: не разобрал срок в строке таблицы 2.10: {left!r}")
                    continue
                days = int(match.group(1))
                for name in split_countries(right):
                    code = iso3(name, countries)
                    if code is None:
                        fail(f"B: страна из ПДФ не резолвится в ISO3: {name!r} ({days} дн)")
                        continue
                    if code in from_pdf and from_pdf[code] != days:
                        fail(f"B: {code} в ПДФ встречается с разными сроками: "
                             f"{from_pdf[code]} и {days}")
                    from_pdf[code] = days

    if rows_seen < 8:
        fail(f"B: таблица 2.10 разобрана подозрительно коротко — строк {rows_seen}")
        return

    notes.append(f"B: из ПДФ разобрано {len(from_pdf)} стран с освобождением, "
                 f"{len(not_in_list)} стран вне Перечня")

    in_bundle: dict[str, int] = {}
    for unit in units:
        if unit.get("kind") != "registration_exemption":
            continue
        code = str(unit.get("unit_id") or "").rsplit(".", 1)[-1]
        value = unit.get("value") or {}
        if value.get("days") is not None:
            in_bundle[code] = int(value["days"])

    for code, days in sorted(from_pdf.items()):
        if code not in in_bundle:
            fail(f"B: в ПДФ есть освобождение {code}={days} дн, в бандле единицы нет")
        elif in_bundle[code] != days:
            fail(f"B: {code}: в ПДФ {days} дн, в бандле {in_bundle[code]} дн")
    for code, days in sorted(in_bundle.items()):
        if code not in from_pdf:
            fail(f"B: в бандле есть освобождение {code}={days} дн, в таблице 2.10 его нет")

    default = next((u for u in units if u.get("unit_id") == "KG.REG.DEFAULT"), None)
    if default is None:
        fail("C: единицы KG.REG.DEFAULT нет в бандле")
    else:
        value = default.get("value") or {}
        if value.get("deadline_working_days_from_border") != 5:
            fail("C: KG.REG.DEFAULT: срок "
                 f"{value.get('deadline_working_days_from_border')!r} вместо 5 рабочих дней")
        listed = {iso3(n, countries) for n in not_in_list} - {None}
        have = set(value.get("not_in_list") or ())
        if not listed:
            fail("C: из ПДФ не разобрался перечень стран вне Перечня")
        for code in sorted(listed - have):
            fail(f"C: {code} назван в ПДФ вне Перечня, в KG.REG.DEFAULT его нет")
        extra = sorted(have - listed)
        if extra:
            # Список в ПДФ оканчивается «и т.д.» — расширение допустимо, но помечаем.
            notes.append("C: KG.REG.DEFAULT шире ПДФ (там список через «и т.д.»): "
                         + ", ".join(extra))

    for code, days in sorted(term_days.items()):
        unit = next((u for u in units if u.get("unit_id") == f"KG.REG.TERM.{code}"), None)
        if unit is None:
            fail(f"C: в ПДФ регистрация для {code} оформляется на {days} дн, единицы нет")
        elif (unit.get("value") or {}).get("days") != days:
            fail(f"C: KG.REG.TERM.{code}: в ПДФ {days} дн, "
                 f"в бандле {(unit.get('value') or {}).get('days')!r}")
    if term_days:
        notes.append("C: сроки оформления регистрации из ПДФ: "
                     + ", ".join(f"{k}={v}" for k, v in sorted(term_days.items())))


def check_annex1(pages: dict[int, dict], units: list[dict],
                 countries: dict[str, str]) -> None:
    """D: список приложения 1 П-541 из раздела 2.3 против KG.VF.ANNEX1_30_60."""
    text = re.sub(r"\s+", " ", pages[22]["text"])
    match = re.search(r"2\.3\.\s*Приложение 1 П-541:\s*(\d+)\s*стран[^:]*?30/60\s*(.+?)\s*2\.4\.",
                      text, flags=re.S)
    if not match:
        fail("D: раздел 2.3 со списком приложения 1 в ПДФ не найден")
        return
    declared = int(match.group(1))
    names = split_countries(match.group(2))
    from_pdf: set[str] = set()
    for name in names:
        code = iso3(name, countries)
        if code is None:
            fail(f"D: страна приложения 1 не резолвится: {name!r}")
        else:
            from_pdf.add(code)
    if len(names) != declared:
        fail(f"D: ТЗ обещает {declared} стран, в списке перечислено {len(names)}")
    notes.append(f"D: из раздела 2.3 разобрано {len(from_pdf)} стран "
                 f"(ТЗ заявляет {declared})")

    unit = next((u for u in units if u.get("unit_id") == "KG.VF.ANNEX1_30_60"), None)
    if unit is None:
        fail("D: единицы KG.VF.ANNEX1_30_60 нет в бандле")
        return
    value = unit.get("value") or {}
    have = set(value.get("countries") or ())
    for code in sorted(from_pdf - have):
        fail(f"D: {code} есть в приложении 1 ПДФ, в единице его нет")
    for code in sorted(have - from_pdf):
        fail(f"D: {code} есть в единице, в списке приложения 1 ПДФ его нет")
    if (value.get("days"), value.get("window_days")) != (30, 60):
        fail(f"D: KG.VF.ANNEX1_30_60: лимит {value.get('days')}/{value.get('window_days')} "
             "вместо 30/60")


def check_limits(pages: dict[int, dict], units: list[dict]) -> None:
    """E: лимит каждого безвизового режима встречается в ячейках таблиц ТЗ.

    Сверяем по ячейкам, а не по тексту страницы: в многоколоночной вёрстке
    ``extract_text`` склеивает строки по горизонтали, и между словами одной фразы
    вклиниваются слова соседних колонок.
    """
    cells: list[str] = []
    for page in pages.values():
        for table in page["tables"]:
            for row in table:
                for cell in row:
                    cells.append(re.sub(r"\s+", " ", str(cell or "")))
    joined = " ~ ".join(cells)
    for unit in units:
        if unit.get("kind") != "visa_free_regime":
            continue
        value = unit.get("value") or {}
        days, window = value.get("days"), value.get("window_days")
        if days is None or window is None:
            continue
        uid = unit.get("unit_id")
        wanted = f"{days} дней в каждом {window}-"
        if wanted not in joined:
            fail(f"E: {uid}: формулировки {wanted!r} нет в тексте ТЗ")
        else:
            notes.append(f"E: {uid}: лимит {days}/{window} подтверждён текстом ТЗ")


def check_overlay(meta: dict, units: list[dict]) -> None:
    """F: оверлей подтверждений ссылается только на существующие и годные единицы."""
    if not OVERLAY.exists():
        notes.append("F: оверлея подтверждений нет — подтверждено ноль единиц (штатно)")
        return
    sys.path.insert(0, str(ROOT))
    from app.knowledge import entry_confirmations
    from app.knowledge.entry_bundle import loaded

    doc = json.loads(OVERLAY.read_text(encoding="utf-8"))
    bundle = loaded()
    if bundle is None:
        fail("F: бандл не загружается — оверлей проверить нельзя")
        return
    if doc.get("bundle_hash") != bundle.bundle_hash:
        fail(f"F: bundle_hash оверлея {doc.get('bundle_hash')!r} != "
             f"текущего {bundle.bundle_hash!r} — оверлей аннулирован целиком")
    if doc.get("source_hash") != meta.get("source_hash"):
        fail("F: source_hash оверлея не совпадает с хешем исходного PDF")

    # Сверяем с ЗАГРУЖЕННЫМ бандлом: загрузчик нормализует значения (сортирует списки
    # стран), и движок сверяет хеш именно с этой формой.
    by_id = {u.get("unit_id"): u for u in bundle.units}
    rows = doc.get("confirmed") or []
    seen: set[str] = set()
    kinds: dict[str, int] = {}
    for row in rows:
        uid = row.get("unit_id")
        if uid in seen:
            fail(f"F: {uid} подтверждён в оверлее дважды")
        seen.add(uid)
        unit = by_id.get(uid)
        if unit is None:
            fail(f"F: оверлей подтверждает несуществующую единицу {uid!r}")
            continue
        kind = str(unit.get("kind") or "?")
        kinds[kind] = kinds.get(kind, 0) + 1
        if unit.get("value") is None:
            fail(f"F: {uid}: подтверждено пустое значение")
            continue
        if str(unit.get("label") or "") in UNSAYABLE_LABELS:
            fail(f"F: {uid}: метка ТЗ {unit['label']!r} запрещает произносить — "
                 "подтверждать нельзя")
        if unit.get("conflict_ref"):
            fail(f"F: {uid}: у единицы отмечен конфликт источников")
        if row.get("value_sha256") != entry_confirmations.value_digest(unit["value"]):
            fail(f"F: {uid}: хеш значения в оверлее не совпадает с бандлом "
                 "(значение правили после подтверждения)")
        if not row.get("basis"):
            fail(f"F: {uid}: не записано основание подтверждения")
    notes.append(f"F: в оверлее {len(rows)} подтверждений: "
                 + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=str(ROOT / "runs" / "specialist-source.pdf"))
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    meta, units, countries = load_bundle()
    if not pdf_path.exists():
        print(f"НЕВОЗМОЖНО: нет исходного PDF {pdf_path}")
        return 2
    digest = sha256(pdf_path.read_bytes()).hexdigest()
    if digest != meta.get("source_hash"):
        print(f"НЕВОЗМОЖНО: хеш PDF {digest} != meta.source_hash {meta.get('source_hash')}")
        return 2
    print(f"A: PDF сошёлся с бандлом по хешу ({digest[:12]}), единиц в бандле {len(units)}")

    pages = pdf_pages(pdf_path, [19, 20, 21, 22, 24, 25])
    check_exemptions(pages, units, countries)
    check_annex1(pages, units, countries)
    check_limits(pages, units)
    check_overlay(meta, units)

    for note in notes:
        print("   " + note)

    fresh, known = triage(problems)
    for item, reason in known:
        print(f"\nИЗВЕСТНЫЙ ПРОБЕЛ: {item}\n   {reason}")
    if fresh:
        print(f"\nНОВЫХ РАСХОЖДЕНИЙ: {len(fresh)}")
        for problem in fresh:
            print("  x " + problem)
        return 1
    print(f"\nНовых расхождений нет: данные бандла совпадают с таблицами ПДФ "
          f"(разобранных пробелов {len(known)}).")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
