"""Build the offline E6-01A PDF checkpoint from its coverage matrix.

Requires local PyMuPDF (document tooling only, not an application dependency).
No network, CRM database, personal data or source PDF modification.
"""
import argparse
from datetime import date
from html import escape
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
CSS = """body{font-family:sans-serif;font-size:10pt;line-height:1.4;color:#17263b}
h1{font-size:25pt;color:#123b60}h2{font-size:15pt;color:#123b60}
table{border-collapse:collapse;width:100%;font-size:9pt}
td,th{border:1px solid #b9c7d5;padding:8px;vertical-align:top}
th{background-color:#eaf0f6;text-align:left}
.note{background-color:#fff1d8;padding:12px}.small{font-size:9pt;color:#465669}
"""


def render(html):
    box = fitz.paper_rect("a4")
    area = box + (40, 42, -40, -42)
    story = fitz.Story(html, user_css=CSS)
    return story.write_with_links(lambda number, filled: (box, area, None))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True, help="Code commit or explicitly uncommitted snapshot")
    parser.add_argument("--checks", required=True, help="Actual check result, including known failures")
    parser.add_argument("--date", dest="report_date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    target = ROOT / f"docs/reports/frunze-pdf-progress-{args.report_date.isoformat()}-applications.pdf"
    source = (ROOT / "docs/e5-pdf-section-coverage.md").read_text(encoding="utf-8")
    rows = [[part.strip() for part in line.strip().strip("|").split("|")]
            for line in source.splitlines() if line.startswith("| ")]
    header, rows = rows[0], rows[1:]
    if len(rows) != 26 or any(len(row) != 3 for row in rows):
        raise SystemExit("Unexpected coverage matrix; review the report builder.")
    output = render(f"""<h1>Frunze Travel / GetVisa</h1><h2>Что сделано по PDF и CRM</h2>
    <p>{args.report_date:%d.%m.%Y} · E6-01A · заявители и подачи в CRM</p>
    <p class="note"><b>Весь PDF ещё не выполнен.</b> Добавлен локальный реестр отдельных
    заявителей и попыток подачи с журналом фактов. Пилот выключен по умолчанию;
    на рабочий сервер эти изменения не выкатывались.</p>
    <h2>Результат этого этапа</h2>
    <ul><li>У услуги теперь отдельные номерные заявители и заявки на каждый документ.
    Шесть видов процедур сгруппированы в четыре семейства из PDF.</li>
    <li>Фиксируются подача, доработка, повторная отправка, одобрение, отказ и закрытие
    в CRM: дата, источник, автор и неизменяемая история.</li>
    <li>Доработка остаётся в той же попытке; после отказа создаётся новая связанная
    попытка. Reference уникален; одно решение не завершает другие заявки.</li>
    <li>Нативные формы, пагинация, печать, контроль доступа, повторов и конфликтов.
    Четыре новые таблицы проверяются на синтетике; реальные анкеты и сканы не добавлены.</li>
    <li>Сверка всех 26 разделов исходного документа: выполненное и конкретный остаток
    приведены на следующих страницах.</li></ul>
    <h2>Проверка</h2><p>{escape(args.checks)}</p>
    <p class="small">Код: {escape(args.revision)}<br>Ветка: fix/tours-search-quality<br>
    Независимые CRITICAL review/audit и PostgreSQL runtime остаются UNKNOWN.
    Это локальная реализация, не подтверждение готовности к запуску.</p>
    <h2>Главный остаток</h2><p>Полные профили заявителей, четыре исполняемых процесса CRM,
    документы, согласия, сроки и сопровождение; диалог и передача менеджеру; утверждение знаний,
    цен и календаря. Новый точный процент не вычислялся. Исторический ориентир
    остатка 70–80% — грубая оценка, не измерение трудозатрат.</p>""")
    for start in range(0, len(rows), 7):
        table = "<tr>" + "".join(f"<th>{escape(cell)}</th>" for cell in header) + "</tr>"
        for row in rows[start:start + 7]:
            table += "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        section = render(f"<h2>Сверка с исходным PDF · часть {start // 7 + 1}</h2>"
                         "<p class='small'>Страницы физические. Наличие текста в поиске не означает выполнение процедуры.</p>"
                         f"<table>{table}</table>")
        output.insert_pdf(section)
        section.close()
    for i, page in enumerate(output):
        page.insert_text((40, 820), f"Frunze Travel / GetVisa | {args.report_date.isoformat()} | {i + 1} / {len(output)}",
                         fontsize=8, color=(.3, .35, .4))
    output.set_metadata({"title": f"Frunze Travel — PDF/CRM progress {args.report_date.isoformat()}", "author": "Codex"})
    target.parent.mkdir(parents=True, exist_ok=True)
    output.save(target, garbage=4, deflate=True)
    print(f"Report: {target.name}; pages: {len(output)}")
    output.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
