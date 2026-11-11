# -*- coding: utf-8 -*-
"""`_view` обязан переносить КАЖДОЕ поле, которое панель умеет хранить.

12.11.2026 причина закрытия лида неделю бы писалась в базу и не читалась обратно:
поле добавили в датакласс и в оба `update_meta`, но забыли в `_view` — а именно через
него Postgres-хранилище отдаёт диалоги панели. На боевом сервере это выглядело бы так:
менеджер выбирает «Высокая стоимость», карточка перерисовывается без отметки, он жмёт
снова. Тесты молчали, потому что шли по memory-хранилищу, которое отдаёт сам объект.

Поэтому проверка здесь структурная, а не про одно поле: любое новое поле панели,
забытое в `_view`, валит этот тест.
"""
from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace

from app.integrations.panel.store import ConversationView, _view

# Поля, которых у ORM-строки нет по устройству: сообщения грузятся отдельным запросом
# (в `_view` их намеренно не тянут — иначе список карточек поднимал бы всю переписку).
NOT_ON_THE_ROW = {"messages"}


def _orm_like() -> SimpleNamespace:
    """ORM-строка со всеми полями представления и различимыми значениями."""
    row = {}
    for field in fields(ConversationView):
        if field.name in NOT_ON_THE_ROW:
            continue
        if field.type in ("str", "str | None"):
            row[field.name] = f"значение-{field.name}"
        elif field.type in ("bool",):
            row[field.name] = True
        elif field.type in ("int",):
            row[field.name] = 7
        elif field.type in ("float", "float | None"):
            row[field.name] = 1.5
        elif "dict" in str(field.type):
            row[field.name] = {"k": field.name}
        elif "datetime" in str(field.type):
            row[field.name] = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)
        else:
            row[field.name] = f"значение-{field.name}"
    return SimpleNamespace(**row)


def test_every_stored_field_survives_the_trip_through_view():
    row = _orm_like()

    view = _view(row)

    lost = []
    for field in fields(ConversationView):
        if field.name in NOT_ON_THE_ROW:
            continue
        expected = getattr(row, field.name)
        actual = getattr(view, field.name)
        # Пустое значение там, где в строке было непустое, — это и есть потерянное поле.
        if actual in ("", None, {}) and expected not in ("", None, {}):
            lost.append(field.name)
    assert lost == [], f"_view теряет поля: {lost}"


def test_the_outcome_reason_specifically_survives():
    """Именно на этом поле мы обожглись — пусть у него будет свой тест."""
    row = _orm_like()
    row.outcome = "lost"
    row.outcome_reason = "competitor"

    view = _view(row)

    assert view.outcome == "lost"
    assert view.outcome_reason == "competitor"
