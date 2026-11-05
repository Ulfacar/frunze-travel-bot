"""Постоянный справочник креативов, независимый от исходных данных диалогов."""
import sqlite3
from pathlib import Path


def names(path, direction):
    path = Path(path).resolve()
    if not path.exists():
        return {}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        return {(source, code): label for source, code, label in db.execute(
            "SELECT source, code, label FROM creatives WHERE direction=?", (direction,))}


def rename(path, direction, source, code, label):
    if direction not in ("visa", "tours") or source not in ("post", "ad"):
        raise ValueError("Недопустимый источник или направление")
    code, label = code.strip(), label.strip()
    if not code or len(code) > 128 or len(label) > 160:
        raise ValueError("Код обязателен (до 128 символов), название — до 160 символов")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS creatives (direction TEXT, source TEXT, code TEXT, "
                   "label TEXT NOT NULL, PRIMARY KEY(direction, source, code))")
        if label:
            db.execute("INSERT INTO creatives VALUES (?, ?, ?, ?) ON CONFLICT(direction,source,code) "
                       "DO UPDATE SET label=excluded.label", (direction, source, code, label))
        else:
            db.execute("DELETE FROM creatives WHERE direction=? AND source=? AND code=?",
                       (direction, source, code))
