"""Подсказка тумблера «Рабочий день» берёт запись дел из рантайм-флага, а не из env.

Нашли 27.11.2026 при восстановлении истории: `_workday_note` читал
`settings.service_cases_enabled`, а тумблер «Запись в реестр услуг» живёт в БД. Включили
кнопкой — подсказка продолжала писать «запись выключена».
"""
import asyncio

from app.admin import router as ar
from app.core import flags


def _views(monkeypatch, states: dict):
    async def fake_get_flag(key, default=False):
        return states.get(key, default)
    monkeypatch.setattr(flags, "get_flag", fake_get_flag)
    return {v["key"]: v for v in asyncio.run(ar._flag_views())}


def test_note_is_empty_when_cases_flag_is_on_in_db_but_off_in_env(monkeypatch):
    monkeypatch.setattr(ar.settings, "service_cases_enabled", False)
    views = _views(monkeypatch, {"service_cases_enabled": True})
    assert views["admin_workday_enabled"]["note"] == ""


def test_note_warns_when_cases_flag_is_off_in_db_but_on_in_env(monkeypatch):
    monkeypatch.setattr(ar.settings, "service_cases_enabled", True)
    views = _views(monkeypatch, {"service_cases_enabled": False})
    assert "выключена" in views["admin_workday_enabled"]["note"]


def test_flag_states_still_come_from_db(monkeypatch):
    views = _views(monkeypatch, {"admin_workday_enabled": True, "service_cases_enabled": False})
    assert views["admin_workday_enabled"]["on"] is True
    assert views["service_cases_enabled"]["on"] is False


def test_note_without_argument_keeps_env_fallback(monkeypatch):
    monkeypatch.setattr(ar.settings, "service_cases_enabled", False)
    assert "выключена" in ar._workday_note()
    monkeypatch.setattr(ar.settings, "service_cases_enabled", True)
    assert ar._workday_note() == ""
