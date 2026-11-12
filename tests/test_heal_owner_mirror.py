# -*- coding: utf-8 -*-
"""Лечение расхождений владельца — проверяем предохранители, а не счастливый путь.

Скрипт пишет в боевые данные по живым клиентам. Поэтому тесты здесь про то, как он
ОТКАЗЫВАЕТСЯ работать: без `--apply`, сверх предела, при владельце из реестра,
которого нет среди менеджеров, при строке, изменившейся под ним, и при расхождении,
которое за время счёта успело измениться.

Отдельно проверяем разделение на группы: случай «в переписке уволенная Сезим» лечится
без вопросов, а «в переписке живой менеджер» решает Алан, и скрипт по умолчанию его
не трогает (замер 12.11.2026: реестровый владелец этих диалогов в панели не касался
ни разу, а панелью в ноябре пользуется только Адеми).
"""
import json
import sys
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

heal = pytest.importorskip("heal_owner_mirror")


def _row(user_id="getvisa:996700000001", panel="eliza", panel_ok=True, domain="medina",
         domain_ok=True, reason="round_robin", last="2026-11-11", direction="visa"):
    """Кортеж в том виде, в каком его отдаёт owner_mirror_check.collect()."""
    return (last, direction, user_id, panel, panel_ok, domain, domain_ok,
            "2026-08-29", reason)


class _Res:
    def __init__(self, rowcount):
        self.rowcount = rowcount


class _Session:
    """Сессия, которая считает запросы и отдаёт заданный rowcount на UPDATE."""

    def __init__(self, rowcounts=None):
        self.updates, self.inserts = [], []
        self.committed = False
        self._rowcounts = list(rowcounts or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if sql.lstrip().upper().startswith("UPDATE"):
            self.updates.append((sql, params))
            return _Res(self._rowcounts.pop(0) if self._rowcounts else 1)
        self.inserts.append((sql, params))
        return _Res(1)

    async def commit(self):
        self.committed = True


@pytest.fixture
def wired(monkeypatch):
    """Подменяем всё внешнее: замер и сессию. Менеджеров скрипт больше не читает."""
    state = {"session": _Session(), "found": [], "later": None}

    async def fake_collect():
        # `later` — что замер отдаёт на ВТОРОМ и дальше вызовах (перепроверка перед
        # записью). None значит «то же самое».
        if state["later"] is not None and fake_collect.calls:
            fake_collect.calls += 1
            return list(state["later"]), {}
        fake_collect.calls += 1
        return list(state["found"]), {}

    fake_collect.calls = 0
    monkeypatch.setattr(heal, "collect", fake_collect)
    monkeypatch.setattr(heal.ar, "_domain_sessionmaker", lambda: (lambda: state["session"]))
    state["collect"] = fake_collect
    return state


async def _run(argv, tmp_path):
    sys.argv = ["heal_owner_mirror.py", *argv, "--backup-dir", str(tmp_path)]
    return await heal.main()


# --- группы -----------------------------------------------------------------

def test_a_departed_owner_is_unambiguous():
    """Уволенная (нет в настройках) и служебный «Админ» — владельцев по факту нет."""
    assert heal._group_of("sezim", False) == "departed"
    assert heal._group_of("admin", True) == "departed"


def test_a_working_manager_is_contested():
    """Живой менеджер в переписке — это вопрос «чей клиент», а не баг."""
    assert heal._group_of("ademi", True) == "contested"
    assert heal._group_of("eliza", True) == "contested"


def test_default_group_leaves_the_contested_cards_alone():
    """Главная защита решения Алана: по умолчанию спорные 18 не трогаются."""
    found = [_row(user_id="a", panel="sezim", panel_ok=False, domain="ademi"),
             _row(user_id="b", panel="ademi", domain="aisina")]
    plan, other, refused = heal._plan_from(found, "departed")
    assert [r["user_id"] for r in plan] == ["a"]
    assert [r["user_id"] for r in other] == ["b"]
    assert refused == []


def test_group_all_takes_both():
    found = [_row(user_id="a", panel="sezim", panel_ok=False, domain="ademi"),
             _row(user_id="b", panel="ademi", domain="aisina")]
    plan, other, _ = heal._plan_from(found, "all")
    assert len(plan) == 2 and other == []


def test_an_unconfigured_registry_owner_is_refused_in_every_group():
    """Владелец из реестра, которого нет в панели, спрятал бы карточку из всех листов."""
    found = [_row(domain="sezim", domain_ok=False)]
    for group in ("departed", "contested", "all"):
        plan, _, refused = heal._plan_from(found, group)
        assert plan == [], group
        assert len(refused) == 1, group


# --- запись -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_without_apply_nothing_is_written(wired, tmp_path):
    """Показ без записи — главный предохранитель: один и тот же вызов безопасен."""
    wired["found"] = [_row(panel="sezim", panel_ok=False)]
    rc = await _run([], tmp_path)
    assert rc == 0
    assert wired["session"].updates == []
    assert wired["session"].committed is False
    assert list(tmp_path.iterdir()) == []       # и бэкапа нет: нечего бэкапить


@pytest.mark.asyncio
async def test_apply_writes_conditionally_and_normalizes(wired, tmp_path):
    """UPDATE адресный и по нормализованному владельцу: в базе регистр не гарантирован."""
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    rc = await _run(["--apply"], tmp_path)
    assert rc == 0
    sql, params = wired["session"].updates[0]
    assert "UPDATE conversations" in sql
    assert "lower(trim(coalesce(assigned_to,''))) = :old" in sql, \
        "без старого владельца в WHERE это слепая перезапись"
    assert "assigned_at" not in sql, "assigned_at трогать нельзя — иначе откат неполный"
    assert params == {"new": "ademi", "uid": "getvisa:996700000001", "old": "sezim"}
    assert wired["session"].committed is True


@pytest.mark.asyncio
async def test_the_audit_trail_shares_the_transaction(wired, tmp_path):
    """Журнал в той же транзакции: иначе бывает «данные изменены, следа нет»."""
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    await _run(["--apply"], tmp_path)
    assert len(wired["session"].inserts) == 1
    sql, params = wired["session"].inserts[0]
    assert "INSERT INTO audit_log" in sql
    assert params["m"] == heal.AUDIT_ACTOR
    assert "sezim" in params["d"] and "ademi" in params["d"]
    # один commit на всё: и смена владельца, и след
    assert wired["session"].committed is True


@pytest.mark.asyncio
async def test_a_backup_is_written_before_any_change(wired, tmp_path):
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    await _run(["--apply"], tmp_path)
    backups = list(tmp_path.glob("owner-mirror-backup-*.json"))
    assert len(backups) == 1, "без бэкапа откатиться нечем"
    saved = json.loads(backups[0].read_text(encoding="utf-8"))
    assert saved["rows"][0]["before"] == "sezim"
    assert saved["rows"][0]["after"] == "ademi"


@pytest.mark.asyncio
async def test_too_many_candidates_is_a_refusal(wired, tmp_path):
    """Если кандидатов внезапно много — значит считается не то. Отказ, не запись."""
    wired["found"] = [_row(user_id=f"getvisa:99670000{i:04d}", panel="sezim",
                           panel_ok=False) for i in range(12)]
    rc = await _run(["--apply", "--max", "5"], tmp_path)
    assert rc == 2
    assert wired["session"].updates == []
    assert list(tmp_path.iterdir()) == [], "отказ не должен оставлять бэкап"


@pytest.mark.asyncio
async def test_the_limit_is_inclusive(wired, tmp_path):
    """Граница: ровно предел — ещё работаем, предел+1 — отказ."""
    rows = [_row(user_id=f"getvisa:99670000{i:04d}", panel="sezim", panel_ok=False)
            for i in range(5)]
    wired["found"] = rows
    assert await _run(["--apply", "--max", "5"], tmp_path) == 0
    wired["session"] = _Session()
    wired["found"] = rows + [_row(user_id="getvisa:996700009999", panel="sezim",
                                  panel_ok=False)]
    assert await _run(["--apply", "--max", "5"], tmp_path) == 2


@pytest.mark.asyncio
async def test_a_row_changed_underneath_is_reported_not_forced(wired, tmp_path):
    """Менеджер поменял владельца в базе пока мы писали — пропускаем, без следа."""
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    wired["session"] = _Session(rowcounts=[0])
    rc = await _run(["--apply"], tmp_path)
    assert rc == 0
    assert len(wired["session"].updates) == 1          # попытка была
    assert wired["session"].inserts == [], "пропущенная строка не идёт в журнал"


@pytest.mark.asyncio
async def test_the_registry_is_re_read_before_writing(wired, tmp_path):
    """Реестр перечитываем перед записью: за время счёта он мог измениться.

    Иначе зеркалу достаётся устаревший логин — именно тот сбой, который лечим.
    """
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    wired["later"] = [_row(panel="sezim", panel_ok=False, domain="aisina")]  # реестр изменился
    rc = await _run(["--apply"], tmp_path)
    assert rc == 0
    assert wired["session"].updates == [], "писать по устаревшему реестру нельзя"


@pytest.mark.asyncio
async def test_mixed_batch_writes_only_what_applied(wired, tmp_path):
    """Две строки, одна ушла из-под нас: журнал — только по записанной."""
    wired["found"] = [_row(user_id="a", panel="sezim", panel_ok=False, domain="ademi"),
                      _row(user_id="b", panel="admin", domain="aisina")]
    wired["session"] = _Session(rowcounts=[1, 0])
    await _run(["--apply"], tmp_path)
    assert len(wired["session"].updates) == 2
    assert len(wired["session"].inserts) == 1
    assert wired["session"].inserts[0][1]["uid"] == "a"


@pytest.mark.asyncio
async def test_a_broken_backup_stops_the_heal(wired, tmp_path, monkeypatch):
    """Бэкап, который перечитался не тем, что писали — лечение не начинаем."""
    wired["found"] = [_row(panel="sezim", panel_ok=False, domain="ademi")]
    monkeypatch.setattr(heal.json, "dumps",
                        lambda *a, **k: '{"rows": [{"user_id": "x", "before": "y"}]}')
    with pytest.raises(RuntimeError, match="бэкап"):
        await _run(["--apply"], tmp_path)
    assert wired["session"].updates == [], "записи не должно быть без годного бэкапа"


@pytest.mark.asyncio
async def test_nothing_to_heal_is_a_clean_exit(wired, tmp_path):
    wired["found"] = []
    rc = await _run([], tmp_path)
    assert rc == 0
    assert wired["session"].updates == []


# --- откат ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_restore_puts_the_old_owner_back_conditionally(wired, tmp_path):
    """Откат — зеркало лечения: по НОВОМУ значению, чужую правку не затирает."""
    backup = tmp_path / "owner-mirror-backup-test.json"
    backup.write_text(json.dumps({"created_at": "2026-11-12T00:00:00+00:00", "rows": [
        {"user_id": "getvisa:996700000001", "before": "sezim", "after": "ademi",
         "reason": "tours_orphans_2026_07"}]}, ensure_ascii=False), encoding="utf-8")
    rc = await _run(["--restore", str(backup)], tmp_path)
    assert rc == 0
    sql, params = wired["session"].updates[0]
    assert params == {"new": "sezim", "uid": "getvisa:996700000001", "old": "ademi"}
    assert "lower(trim(coalesce(assigned_to,''))) = :old" in sql
    assert "откат" in wired["session"].inserts[0][1]["d"]


@pytest.mark.asyncio
async def test_restore_of_an_empty_backup_refuses(wired, tmp_path):
    backup = tmp_path / "empty.json"
    backup.write_text('{"rows": []}', encoding="utf-8")
    assert await _run(["--restore", str(backup)], tmp_path) == 2
    assert wired["session"].updates == []
