"""ГЕЙТ: «простой контроллера» считается по всей работе, а не только по движениям стадий.

Написан ДО правки, по итогам калибровки на реальных метриках прода (07.09.2026, ночь).

## Замер

Первые четыре прогона контроллера после включения дали:

    прогонов 4 | сдвинуто 28 | сводок 84 | очередь 283 | ошибок 0

Сводок втрое больше, чем движений: слоты лимита уходят и на запись досье в карточки, у
которых стадия уже правильная. Это нормальная работа — но по первоначальному правилу
(`waiting > 0 и moved == 0` три прогона подряд) она выглядела бы простоем: как только в
очереди останутся одни «сводочные» карточки, `moved` станет нулём при непустой очереди,
и владельцу уйдёт тревога о том, что контроллер встал. А он в этот момент работает.

Это ровно тот класс ошибки, из-за которого 07.08 сгорел сторож каналов: он слал 5.3
ложных тревоги в сутки, и его отключили. Отключённый сторож хуже отсутствующего.

## Правило

Простой — это когда очередь есть, а контроллер не сделал НИЧЕГО: ни одного движения и
ни одной сводки. Любая выполненная работа обнуляет счётчик простоев.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import pipeline_metrics as pm


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    pm._reset_for_tests()
    yield
    pm._reset_for_tests()


def test_dossier_only_run_is_not_a_stall():
    """Главный случай замера: стадии не двигались, но 21 сводка записана — это работа."""
    run(pm.note_run({"scanned": 900, "moved": 0, "dossiers": 21, "errors": 0, "waiting": 283}))
    assert run(pm.status())["stall_runs"] == 0


def test_real_stall_still_counts():
    """Очередь есть, не сделано ничего — вот это простой."""
    for _ in range(3):
        run(pm.note_run({"scanned": 900, "moved": 0, "dossiers": 0, "errors": 0, "waiting": 283}))
    assert run(pm.status())["stall_runs"] == 3


def test_any_work_resets_the_counter():
    for _ in range(2):
        run(pm.note_run({"scanned": 900, "moved": 0, "dossiers": 0, "errors": 0, "waiting": 283}))
    run(pm.note_run({"scanned": 900, "moved": 0, "dossiers": 5, "errors": 0, "waiting": 283}))
    assert run(pm.status())["stall_runs"] == 0


def test_empty_queue_never_counts_as_stall():
    """Ложноположительный, обязан пройти: делать было нечего — это не простой."""
    for _ in range(5):
        run(pm.note_run({"scanned": 900, "moved": 0, "dossiers": 0, "errors": 0, "waiting": 0}))
    assert run(pm.status())["stall_runs"] == 0


def test_moving_work_still_resets():
    """Ложноположительный: обычный рабочий прогон счётчик не копит."""
    run(pm.note_run({"scanned": 900, "moved": 7, "dossiers": 21, "errors": 0, "waiting": 283}))
    assert run(pm.status())["stall_runs"] == 0
