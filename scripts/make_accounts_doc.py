#!/usr/bin/env python3
"""Собрать Word-документ с доступами менеджеров из файла паролей.

Зачем. `add_manager_accounts.py` кладёт пароли в `new-logins-<дата>.json` с правами
0600 — машинный формат, который менеджеру не отдашь. Этот скрипт делает из него
документ, который можно распечатать или переслать человеку: адрес панели, логин,
пароль и объяснение, что он там увидит.

Пароли НЕ печатаются в stdout: в выводе только путь к документу и число учёток.
Поэтому скрипт безопасно запускать с общего экрана — в отличие от `cat` по файлу.

Запускать ЛОКАЛЬНО (в образе бота python-docx нет):

    scp frunze:/root/frunze-travel/new-logins-2026-11-11.json .
    python scripts/make_accounts_doc.py new-logins-2026-11-11.json -o Доступы.docx

Документ содержит пароли в открытом виде — это его смысл. Хранить соответственно:
не в общий чат, не в облачную папку на всех.
"""
from __future__ import annotations

import argparse
import json
import pathlib
from datetime import date

try:
    from docx import Document
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
except ImportError:  # pragma: no cover - понятное сообщение вместо трассировки
    raise SystemExit("нужен python-docx: pip install python-docx")

PANEL_URL = "https://frunzetravel.kg/admin"

# Кто что видит. Держим здесь, а не в JSON: JSON — это пароли, и чем меньше в нём
# полей, тем спокойнее его пересылать и удалять.
ROLES = {
    "daulet": ("Даулет", "Туры: диалоги, доска, карточки клиентов, задачи"),
    "daulet-admin": ("Даулет (админ)", "Полный доступ: туры и визы, сводка пилота, "
                                       "настройки"),
    "marsel": ("Марсель", "Визы: диалоги, доска, карточки клиентов, задачи"),
    "medina": ("Медина", "Визы: диалоги, доска, карточки клиентов, задачи"),
    "eliza": ("Элиза", "Визы: диалоги, доска, карточки клиентов, задачи"),
    "ademi": ("Адеми", "Туры: диалоги, доска, карточки клиентов, задачи"),
    "aisina": ("Айсина", "Туры: диалоги, доска, карточки клиентов, задачи"),
    "grisha": ("Гриша", "Визы: диалоги, доска, карточки клиентов"),
    "grisha-admin": ("Гриша (админ)", "Полный доступ: туры и визы, сводка пилота, "
                                      "настройки"),
}


def build(logins: dict[str, str], out: pathlib.Path, url: str) -> int:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    title = doc.add_heading("Доступы в панель Frunze Travel", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT

    intro = doc.add_paragraph()
    intro.add_run("Как войти. ").bold = True
    intro.add_run(f"Откройте {url} в браузере на телефоне или компьютере, "
                  "введите логин и пароль из таблицы ниже. Логин и пароль вводятся "
                  "маленькими буквами, ровно как написано, вместе с чёрточками.")

    doc.add_paragraph(
        "Пароль состоит из трёх слов и двух цифр — его можно продиктовать по телефону. "
        "Менять пароль самостоятельно пока нельзя: если нужно сменить, скажите Алану.")

    doc.add_heading("Учётные данные", level=1)

    table = doc.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    header = table.rows[0].cells
    for cell, text in zip(header, ("Кто", "Логин", "Пароль", "Что видит в панели")):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True

    for login in sorted(logins):
        name, access = ROLES.get(login, (login, "Доступ по направлению"))
        row = table.add_row().cells
        row[0].text = name
        row[1].text = login
        pwd = row[2].paragraphs[0].add_run(logins[login])
        pwd.bold = True
        pwd.font.name = "Consolas"
        row[3].text = access

    doc.add_paragraph()
    warn = doc.add_paragraph()
    run = warn.add_run(
        "Этот лист с паролями не нужно пересылать в общие чаты и выкладывать в общие "
        "папки. Лучше отдать каждому его строку лично.")
    run.bold = True
    run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

    doc.add_heading("Если что-то не работает", level=1)
    for line in ("Страница не открывается — проверьте, что адрес набран полностью, "
                 "вместе с https.",
                 "Пишет «неверный логин или пароль» — проверьте раскладку и что нет "
                 "лишнего пробела в конце.",
                 "Вошли, но пусто — значит за вами пока не закреплены клиенты; "
                 "скажите Алану.",
                 "Телефон просит сохранить пароль — можно сохранить, это ваш рабочий "
                 "компьютер или телефон."):
        doc.add_paragraph(line, style="List Bullet")

    footer = doc.add_paragraph()
    footer.add_run(f"Документ собран {date.today():%d.%m.%Y}. "
                   f"Учётных записей в документе: {len(logins)}.").italic = True

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out)
    return len(logins)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logins", help="JSON от add_manager_accounts.py: {логин: пароль}")
    ap.add_argument("-o", "--out", default="Доступы в панель.docx")
    ap.add_argument("--url", default=PANEL_URL)
    args = ap.parse_args()

    data = json.loads(pathlib.Path(args.logins).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data:
        print("в файле нет пар «логин: пароль»")
        return 2
    out = pathlib.Path(args.out)
    count = build(data, out, args.url)
    print(f"готово: {out} — учётных записей {count} (пароли в stdout не выводятся)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
