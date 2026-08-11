"""ГЕЙТ: утренний список звонков ведёт в карточку Битрикса, а не только ночные заявки.

Написан ДО правки, исполнителем не редактируется.

## Что нашлось 11.08

Визовые менеджеры просили, чтобы бот по утрам кидал ссылку прямо в Битрикс. Ссылку сделали
06.08 (`14c3dfc`) — но только в блоке «🌙 Ночные заявки». В основном блоке брифа, «📞 Звонки»,
её нет: `_task_card` ставит `"bitrix_link": ""` с комментарием «проставляется ниже из
диалога», и ниже этого не делает НИКТО.

Цена видна на живом брифе Элизы за 11.08: 11 задач-звонков без единой ссылки на Битрикс и
6 ночных заявок — со ссылками. То есть в той части, по которой менеджер и работает утром,
ссылки нет.

У задачи календаря своего лида действительно нет: она знает только `user_id`. Лид живёт на
диалоге, поэтому соответствие приходит снаружи — так же, как в бриф уже приходят диалоги.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.core.calendar_brief import build_manager_brief, render_manager_brief_text

NOW = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)     # 08:00 по Бишкеку
PORTAL = "https://getvisakg.bitrix24.kz"
USER_ID = "getvisa:996700240970"


def _task(user_id=USER_ID, kind="call"):
    return SimpleNamespace(kind=kind, priority="normal", status="open", user_id=user_id,
                           due_at=None, comment="Автозадача: перезвонить по ночной заявке",
                           ai_summary="", direction="visa")


def _conv(user_id=USER_ID, lead_id="185639"):
    return SimpleNamespace(user_id=user_id, funnel="visa", assigned_to="eliza", outcome="",
                           qualification={"name": "Камран"}, bitrix_lead_id=lead_id,
                           last_message_at=NOW, archived=False, stage="manager")


def _text(tasks, *, leads=None, night=()):
    brief = build_manager_brief("eliza", "Элиза", tasks, list(night), NOW, lead_ids=leads)
    return render_manager_brief_text(brief, "https://frunzetravel.kg")


def _patch_portal(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "bitrix_portal_url", PORTAL, raising=False)


def test_call_task_carries_the_bitrix_link(monkeypatch):
    """Главный кейс: утренний звонок открывается одним тапом в карточке клиента."""
    _patch_portal(monkeypatch)
    text = _text([_task()], leads={USER_ID: "185639"})
    assert f"🗂 {PORTAL}/crm/lead/details/185639/" in text


def test_link_is_absent_when_lead_unknown(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: карточки ещё нет — строки нет. Битой ссылки в 8 утра быть не должно."""
    _patch_portal(monkeypatch)
    text = _text([_task()], leads={})
    assert "🗂" not in text
    assert "crm/lead/details" not in text and "None" not in text


def test_wa_and_panel_links_survive(monkeypatch):
    """Ссылку в панель и WhatsApp не отбираем: туровые Битриксом не пользуются."""
    _patch_portal(monkeypatch)
    text = _text([_task()], leads={USER_ID: "185639"})
    assert "https://wa.me/996700240970" in text
    assert "https://frunzetravel.kg/admin/conversation/" in text


def test_night_block_still_has_its_link(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: то, что уже работало 06.08, не сломано."""
    _patch_portal(monkeypatch)
    text = _text([], night=[_conv()])
    assert f"🗂 карточка: {PORTAL}/crm/lead/details/185639/" in text


def test_brief_without_lead_map_still_builds(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: старый вызов без карты лидов не должен падать."""
    _patch_portal(monkeypatch)
    brief = build_manager_brief("eliza", "Элиза", [_task()], [], NOW)
    text = render_manager_brief_text(brief, "https://frunzetravel.kg")
    assert "Задач сегодня: 1" in text
    assert "🗂" not in text


def test_task_without_user_id_is_safe(monkeypatch):
    _patch_portal(monkeypatch)
    text = _text([_task(user_id="")], leads={USER_ID: "185639"})
    assert "🗂" not in text
