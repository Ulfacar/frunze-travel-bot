"""ГЕЙТ: контроллер карточек — помнит, что делал, различает расхождения, зовёт человека.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 07.09.2026)

Догоняющий проход сутки подряд отдавал `moved: 0` при непустой очереди — 27 карточек,
уже уехавших дальше цели, занимали все 25 слотов лимита. **Этого не увидел никто**, потому
что результат прогона уходил только в `log.info`, и обнаружился он лишь тогда, когда
владелец в третий раз пожаловался на карточки, а я полез в логи руками.

Второе: сверка односторонняя. Мы двигаем портал, но никогда не смотрим, что там на самом
деле. Карточка уехала назад, лид удалили, id подменили — мы молча замираем (`frozen_manual`)
и не отличаем «менеджер работает» от «что-то сломалось».

## Правило

1. Каждый прогон оставляет след, который переживает рестарт: сколько посмотрели, сколько
   двинули, сколько ждёт очереди, сколько расхождений, когда это было.
2. Расхождения различаются по смыслу: стадия ушла ВПЕРЁД не нами — норма, менеджер
   работает; ушла НАЗАД или лид пропал — расхождение, и его видит человек.
3. Контроллер чинит только то, что чинил всегда: стадию и досье. Карточки в боевом CRM
   он не удаляет и не пересоздаёт — про такое рассказывает человеку.
4. Сторож будит, когда контроллер встал: очередь есть, а движения нет несколько прогонов
   подряд. Пустая очередь и ноль движений — это не поломка, это тишина.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import pipeline_metrics as pm

NOW = 1_788_300_000.0
HOUR = 3600.0


def run(coro):
    return asyncio.run(coro)


class Cfg:
    pipeline_controller_alert_enabled = True
    pipeline_stall_runs = 3           # столько прогонов подряд без движения при очереди
    pipeline_silence_hours = 2        # столько часов без единого прогона = джоба умерла
    pipeline_errors_per_day = 20      # ошибок за сутки, выше которых это уже поломка


def _snap(**kw):
    """Снимок метрик контроллера в том виде, в каком его отдаёт `status()`."""
    base = {"runs": 10, "scanned": 300, "moved": 5, "dossiers": 4, "errors": 0,
            "conflicts": 0, "waiting": 0, "stall_runs": 0, "last_run_at": NOW}
    base.update(kw)
    return base


# ---------------- память: прогон оставляет след -------------------------------------
@pytest.fixture(autouse=True)
def _clean():
    pm._reset_for_tests()
    yield
    pm._reset_for_tests()


def test_run_is_remembered():
    run(pm.note_run({"scanned": 100, "eligible": 25, "moved": 7, "dossiers": 3,
                     "errors": 0, "waiting": 12}))
    snap = run(pm.status())
    assert snap["runs"] == 1
    assert snap["moved"] == 7
    assert snap["waiting"] == 12, "очередь показывает последнее известное значение"


def test_runs_accumulate_over_the_day():
    for _ in range(3):
        run(pm.note_run({"scanned": 10, "moved": 1, "errors": 0, "waiting": 0}))
    snap = run(pm.status())
    assert snap["runs"] == 3
    assert snap["moved"] == 3


def test_status_on_empty_metrics_does_not_crash():
    """Ложноположительный: пустые метрики — обычное состояние после рестарта."""
    snap = run(pm.status())
    assert snap["runs"] == 0
    assert snap["moved"] == 0
    assert snap["last_run_at"] in (0, None) or isinstance(snap["last_run_at"], float)


def test_broken_storage_never_breaks_the_pass(monkeypatch):
    """Счётчик не важнее работы: сбой хранилища молчит, но не роняет контроллер."""
    async def boom(*a, **kw):
        raise RuntimeError("redis down")
    monkeypatch.setattr(pm, "_incr", boom)
    run(pm.note_run({"scanned": 1, "moved": 1, "errors": 0, "waiting": 0}))  # не падает


# ---------------- расхождения: что норма, а что беда --------------------------------
def test_stage_moved_forward_by_human_is_not_a_conflict():
    """Менеджер двинул карточку вперёд — так и надо, бот замирает и молчит."""
    from app.integrations.crm.bitrix_pipeline import classify_drift

    assert classify_drift(current="UC_PNSIIB", remembered="UC_S0NTF8") == "ahead"


def test_stage_moved_backwards_is_a_conflict():
    from app.integrations.crm.bitrix_pipeline import classify_drift

    assert classify_drift(current="NEW", remembered="UC_S0NTF8") == "behind"


def test_same_stage_is_not_a_drift():
    from app.integrations.crm.bitrix_pipeline import classify_drift

    assert classify_drift(current="UC_S0NTF8", remembered="UC_S0NTF8") == ""


def test_unknown_stage_is_not_guessed():
    """Стадии вне нашей последовательности не судим — вдруг портал перенастроили."""
    from app.integrations.crm.bitrix_pipeline import classify_drift

    assert classify_drift(current="UC_WHATEVER", remembered="UC_S0NTF8") == ""


def test_conflicts_are_remembered_for_the_human():
    run(pm.note_conflict("stage_backwards", "frunze_tours:996700111222",
                         detail="NEW ← UC_S0NTF8"))
    snap = run(pm.status())
    assert snap["conflicts"] == 1
    items = run(pm.conflicts())
    assert items and items[0]["kind"] == "stage_backwards"
    assert "996700111222" in items[0]["conv_key"]


# ---------------- сторож: будит только когда контроллер правда встал ----------------
def test_queue_without_movement_wakes_the_owner():
    """Ровно дефект 07.09: очередь есть, moved=0, и так сутки."""
    state: dict = {}
    alerts = pm.decide(NOW, _snap(moved=0, waiting=30, stall_runs=3), state, Cfg)
    assert alerts, "очередь стоит — это поломка, о ней надо сказать"
    assert "не дви" in alerts[0].lower() or "очеред" in alerts[0].lower()


def test_one_alert_not_one_per_run():
    state: dict = {}
    first = pm.decide(NOW, _snap(moved=0, waiting=30, stall_runs=3), state, Cfg)
    second = pm.decide(NOW + 600, _snap(moved=0, waiting=30, stall_runs=4), state, Cfg)
    assert len(first) == 1 and second == [], "повтор в пределах cooldown не шлём"


def test_empty_queue_and_no_movement_is_silence_not_breakage():
    """Ложноположительный, обязан пройти: делать было нечего — это не поломка."""
    assert pm.decide(NOW, _snap(moved=0, waiting=0, stall_runs=9), {}, Cfg) == []


def test_movement_clears_the_latch():
    state: dict = {}
    pm.decide(NOW, _snap(moved=0, waiting=30, stall_runs=3), state, Cfg)
    pm.decide(NOW + 600, _snap(moved=4, waiting=10, stall_runs=0), state, Cfg)
    again = pm.decide(NOW + 1200, _snap(moved=0, waiting=30, stall_runs=3), state, Cfg)
    assert again, "контроллер ожил и снова встал — про второй случай надо сказать"


def test_short_stall_is_not_an_alert():
    """Один-два прогона без движения — обычное дело, не будим."""
    assert pm.decide(NOW, _snap(moved=0, waiting=30, stall_runs=1), {}, Cfg) == []


def test_dead_job_is_noticed():
    """Контроллер не отработал ни разу за два часа — джоба умерла."""
    alerts = pm.decide(NOW, _snap(last_run_at=NOW - 3 * HOUR), {}, Cfg)
    assert alerts and ("не отраб" in alerts[0].lower() or "молч" in alerts[0].lower())


def test_errors_burst_is_noticed():
    alerts = pm.decide(NOW, _snap(errors=50), {}, Cfg)
    assert alerts and "ошиб" in alerts[0].lower()


def test_conflicts_are_reported_once_a_day():
    state: dict = {}
    first = pm.decide(NOW, _snap(conflicts=3), state, Cfg)
    second = pm.decide(NOW + 600, _snap(conflicts=5), state, Cfg)
    assert len(first) == 1 and second == []


def test_flag_off_keeps_the_watchdog_quiet():
    """Ложноположительный: снятый тумблер = ни одного сообщения владельцу."""
    class Off(Cfg):
        pipeline_controller_alert_enabled = False

    assert pm.decide(NOW, _snap(moved=0, waiting=30, stall_runs=9), {}, Off) == []


def test_healthy_controller_says_nothing():
    """Ложноположительный: всё в порядке — тишина."""
    assert pm.decide(NOW, _snap(), {}, Cfg) == []


# ---------------- экран ---------------------------------------------------------------
def test_cards_screen_opens_with_empty_metrics():
    """Страница обязана открываться сразу после рестарта, когда метрик ещё нет."""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/admin/cards")
    assert resp.status_code in (200, 302, 401), resp.status_code
