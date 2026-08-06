"""ГЕЙТ задачи «утреннее уведомление ведёт прямо в карточку Битрикса».

Написан ДО реализации и исполнителем НЕ редактируется.

## Зачем (со встречи 06.08, уточнено владельцем)

Визовые девочки работают в Битриксе и просят, чтобы утреннее уведомление сразу
кидало их в НУЖНУЮ карточку. Дословно из транскрипции:

> «Переписка, значит, чтобы были видны битриксы именно в карточках, и чтобы утром
> сразу на битрикс перекидывала. Чтобы мы сразу битриксы их нашли и от этого отвечали.»

Сейчас в брифе стоит ссылка в НАШУ админку. Тапнув, менеджер попадает не туда, где
работает, и клиента приходится искать в Битриксе руками.

Ссылку не подменяем, а ДОБАВЛЯЕМ: туровые менеджеры Битриксом не пользуются, для них
ссылка на панель — рабочая, отбирать её нельзя.

Опирается на `bitrix_lead_id`, который после правки `2a2db0c` указывает на карточку
Открытой линии — ровно ту, которую менеджер и открывает.

## Требуется от реализации

    app/core/calendar_brief.py
        _bitrix_link(lead_id: str) -> str    # "" если id или базовый URL не заданы
        карточка брифа несёт "bitrix_link"
        render_manager_brief_text печатает его строкой

    app/config.py
        bitrix_portal_url: str = ""          # https://getvisakg.bitrix24.kz
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.core import calendar_brief as cb

PORTAL = "https://getvisakg.bitrix24.kz"
LEAD = "185301"


@pytest.fixture(autouse=True)
def _portal(monkeypatch):
    monkeypatch.setattr(settings, "bitrix_portal_url", PORTAL, raising=False)
    yield


# --- сама ссылка ----------------------------------------------------------------

def test_link_points_at_the_lead_card():
    """Формат живого портала: /crm/lead/details/<ID>/ — открывается сразу карточка."""
    link = cb._bitrix_link(LEAD)
    assert link.startswith(PORTAL)
    assert LEAD in link
    assert "/crm/lead/details/" in link


def test_no_link_without_lead_id():
    assert cb._bitrix_link("") == ""
    assert cb._bitrix_link(None) == ""


def test_no_link_without_portal_url(monkeypatch):
    """Портал не задан — ссылка не собирается. Битая ссылка в 6 утра хуже её отсутствия."""
    monkeypatch.setattr(settings, "bitrix_portal_url", "", raising=False)
    assert cb._bitrix_link(LEAD) == ""


def test_trailing_slash_does_not_double(monkeypatch):
    monkeypatch.setattr(settings, "bitrix_portal_url", PORTAL + "/", raising=False)
    assert "//crm" not in cb._bitrix_link(LEAD)


# --- как это выглядит в тексте брифа --------------------------------------------

def _brief(cards, night=None):
    return {"date_label": "7 августа", "name": "Медина", "task_count": len(cards),
            "by_kind": {"call": cards}, "night": night or [],
            "night_count": len(night or []),
            "to_distribute": [], "to_distribute_count": 0}


def _card(**over):
    card = {"kind": "call", "priority": "normal", "status": "open", "time": "09:00",
            "user_id": "getvisa:996700111222", "client": "1222",
            "phone": "+996 700 111 222", "wa_link": "https://wa.me/996700111222",
            "comment": "", "context": "", "bitrix_link": cb._bitrix_link(LEAD)}
    card.update(over)
    return card


def test_brief_shows_bitrix_link():
    text = cb.render_manager_brief_text(_brief([_card()]), "https://frunzetravel.kg")
    assert LEAD in text, "менеджер должен попадать в карточку одним тапом"


def test_panel_link_is_kept_too():
    """Туровые менеджеры Битриксом не пользуются — их рабочую ссылку не отбираем."""
    text = cb.render_manager_brief_text(_brief([_card()]), "https://frunzetravel.kg")
    assert "/admin/conversation/getvisa:996700111222" in text


def test_no_empty_line_when_lead_unknown():
    """Лида ещё нет (бот ждёт карточку Открытой линии) — просто нет строки."""
    text = cb.render_manager_brief_text(_brief([_card(bitrix_link="")]),
                                        "https://frunzetravel.kg")
    assert "crm/lead/details" not in text
    assert "None" not in text and "  \n" not in text


def test_whatsapp_link_survives():
    """Три ссылки решают разные задачи: написать клиенту, открыть карточку, открыть панель."""
    text = cb.render_manager_brief_text(_brief([_card()]), "https://frunzetravel.kg")
    assert "wa.me/996700111222" in text


def test_night_block_also_links_to_bitrix():
    """Ночные заявки — тот же случай: менеджер утром идёт по ним в первую очередь."""
    brief = _brief([], night=[{"head": "Камран · +996 700 111 222", "name": "Камран",
                               "direction": "визы", "wait_label": "ждёт 9 ч",
                               "user_id": "getvisa:996700111222",
                               "wa_link": "https://wa.me/996700111222",
                               "bitrix_link": cb._bitrix_link(LEAD)}])
    brief["by_kind"] = {}
    assert LEAD in cb.render_manager_brief_text(brief, "https://frunzetravel.kg")


# --- карточка брифа несёт поле --------------------------------------------------

def test_lead_card_carries_bitrix_link():
    """Поле должно приезжать из диалога, иначе печатать нечего."""
    class Conv:
        user_id = "getvisa:996700111222"
        qualification = {"name": "Камран"}
        bitrix_lead_id = LEAD
        funnel = "visa"
        last_message_at = None
        stage = "manager"
        lead_temperature = "warm"
        ai_summary = ""
        manager_next_step = ""
        intercepted = False
        outcome = ""
        phone = "996700111222"

    from datetime import datetime, timezone
    card = cb._lead_card(Conv(), datetime(2026, 8, 7, 6, 0, tzinfo=timezone.utc))
    assert card.get("bitrix_link", "") == cb._bitrix_link(LEAD)
