"""ГЕЙТ: дневной пуш по готовой заявке тоже ведёт в карточку Битрикса.

Написан ДО реализации и исполнителем НЕ редактируется.

## Зачем

Визовые менеджеры работают в Битриксе. Утренний бриф ссылку туда уже несёт
(коммит `14c3dfc`), а **дневной пуш «заявка готова — можно звонить» — нет**: в нём
только ссылка в нашу панель.

А получают они и то, и другое. Вторая менеджер на встрече 06.08 дословно:

> «Да, мне приходят уведомления. Типа, можно уже позвонить… Каждое утро. **Днём.
> Когда он поговорил, пригласил в офис.**»

То есть половину уведомлений мы почини, половину оставили как было.

Ссылку на панель НЕ подменяем: туровые Битриксом не пользуются.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.core.instant_handoff import render_handoff_text

PORTAL = "https://getvisakg.bitrix24.kz"
LEAD_LINK = f"{PORTAL}/crm/lead/details/185301/"


@pytest.fixture(autouse=True)
def _portal(monkeypatch):
    monkeypatch.setattr(settings, "bitrix_portal_url", PORTAL, raising=False)
    yield


def _text(**over):
    kwargs = dict(name="Камран", phone="+996 700 111 222", request="виза · США",
                  promised="Пригласил в офис на консультацию",
                  link="https://frunzetravel.kg/admin/conversation/getvisa:996700111222",
                  wa_link="https://wa.me/996700111222", bitrix_link=LEAD_LINK)
    kwargs.update(over)
    return render_handoff_text(**kwargs)


def test_push_carries_bitrix_link():
    """Одним тапом из пуша — в карточку клиента, откуда визовая и отвечает."""
    assert LEAD_LINK in _text()


def test_panel_link_is_kept():
    assert "/admin/conversation/getvisa:996700111222" in _text()


def test_whatsapp_link_is_kept():
    assert "wa.me/996700111222" in _text()


def test_no_link_no_line():
    """Лида ещё нет — просто нет строки. Битой ссылки в пуше быть не должно."""
    text = _text(bitrix_link="")
    assert "crm/lead/details" not in text
    assert "None" not in text
    assert not any(line.strip() in ("🗂", "") for line in text.splitlines()[1:])


def test_promise_line_survives():
    """Строка «Бот пообещал» обязательна: менеджер звонит, зная, что уже сказано клиенту."""
    assert "Бот пообещал" in _text()


def test_order_client_first():
    """Читается с телефона за 20 секунд: сперва кому звонить, ссылки — хвостом."""
    lines = [l for l in _text().splitlines() if l.strip()]
    assert "Камран" in lines[1]
    assert any("wa.me" in l for l in lines[-3:])


def test_catchup_header_still_works():
    """Догоняющая отправка обязана честно говорить, что заявка не свежая."""
    from datetime import datetime, timezone

    text = _text(waited_since=datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc))
    assert "ждёт с" in text and LEAD_LINK in text
