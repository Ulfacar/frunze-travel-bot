"""Поле «Комментарий» карточки: владение определяется по СОДЕРЖИМОМУ, а не по памяти.

## Дефект, из-за которого написан этот файл (найден прогоном 21.08.2026)

Было так:

```python
remembered = bool(getattr(conv, "bitrix_dossier_by_bot", False))
if not remembered and comments and not _dossier_ours(comments) and not _legacy_ours(comments):
    return False
```

`remembered` — это «я когда-то сюда писал». Если бот однажды записал досье, условие
целиком пропускалось, и дальше поле перезаписывалось ВСЕГДА. Прогон показал: менеджер
правит карточку после бота («Клиент передумал: летят из Оша, бюджет 3000, записан на
25.08») — и следующее обновление стирает эту запись.

Не стреляло только потому, что перехваченные диалоги вообще не обновлялись. Тумблер
`dossier_when_intercepted_enabled` (см. `test_dossier_intercepted.py`) снимает это
прикрытие, поэтому дефект чинится той же задачей — порознь нельзя.

## Правило

Пишем, только если поле сейчас пустое, или в нём наше досье, или наш же легаси-формат.
Всё остальное — чужой текст, и он важнее свежести нашей сводки: менеджер писал это
руками и знает то, чего не знает бот.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "186261"
FACTS = {"destination": "ОАЭ", "region": "Дубай", "dates": "05.09-11.09", "tourists": "4"}

MANUAL = "Клиент передумал: летят из Оша, бюджет 3000. Записан на 25.08 в офис."
LEGACY = "destination: Турция\ndates: сентябрь\ntourists: 2"


class FakeAdapter:
    def __init__(self, comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": "NEW", "COMMENTS": comments}
        self.comment_writes: list[str] = []

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self.lead)

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)
        self.comment_writes.append(text)
        self.lead["COMMENTS"] = text

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)

    async def add_note(self, lead_id, text):
        await asyncio.sleep(0)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    yield
    flags.reset()


def _conv(*, dossier_by_bot):
    key = "frunze_tours:996700000093"
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хотим в Дубай"))
    run(store.update_meta(key, bitrix_lead_id=LEAD, intercepted=False, funnel="tours",
                          qualification=dict(FACTS)))
    if dossier_by_bot:
        run(store.update_meta(key, bitrix_dossier_by_bot=True))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc)
    return key


def _sync(key, fake):
    return run(bp.sync_dossier(key, adapter=fake))


def _our_dossier():
    """Досье в нашем формате — берём у самого рендерера, чтобы маркер не разошёлся."""
    key = _conv(dossier_by_bot=False)
    conv = run(ps.get_conversation_store().get(key))
    return bp.render_dossier(conv, dict(FACTS))


# ---------------- главный тест задачи -----------------------------------------------
def test_manual_text_not_overwritten_even_if_bot_wrote_before():
    fake = FakeAdapter(comments=MANUAL)
    assert _sync(_conv(dossier_by_bot=True), fake) is False
    assert not fake.comment_writes, "правка менеджера важнее свежести нашей сводки"
    assert fake.lead["COMMENTS"] == MANUAL


# ---------------- ложноположительные: обновление своего не сломано ------------------
def test_bot_updates_its_own_dossier():
    fake = FakeAdapter(comments=_our_dossier())
    assert _sync(_conv(dossier_by_bot=True), fake) is True
    assert fake.comment_writes


def test_legacy_dossier_recognised_as_ours():
    fake = FakeAdapter(comments=LEGACY)
    assert _sync(_conv(dossier_by_bot=False), fake) is True
    assert fake.comment_writes


def test_empty_comments_are_writable():
    fake = FakeAdapter(comments="")
    assert _sync(_conv(dossier_by_bot=False), fake) is True
    assert fake.comment_writes


# ---------------- дописанное человеком ----------------------------------------------
def test_dossier_with_manager_append_is_not_ours():
    """Наше досье, а ниже строка менеджера — поле больше не наше."""
    fake = FakeAdapter(comments=_our_dossier() + "\nМенеджер: клиент просит перезвонить после 18:00")
    assert _sync(_conv(dossier_by_bot=True), fake) is False
    assert not fake.comment_writes


# ---------------- дыры, найденные прогоном по реалистичным пометкам ------------------
# Ветка «бот помнит, что писал» была придумана против искажений портала (шрам 17.08),
# но на однострочных записях менеджера она пропускала чужой текст как свой: строк
# «после первой» у них нет, проверять нечего. Ниже — ровно те формулировки, на которых
# это поймано 21.08.
@pytest.mark.parametrize("manual", [
    "Направление: уточнить у клиента",          # менеджер взял слово из нашего шаблона
    "Досье клиента: хочет Египет",              # и слово из нашего маркера
    "Досье клиента: хочет Египет\nзвонить утром",
    "перезвонить после 18:00",
    "ВАЖНО: клиент VIP, скидка согласована",
])
def test_manager_shorthand_is_never_ours(manual):
    fake = FakeAdapter(comments=manual)
    assert _sync(_conv(dossier_by_bot=True), fake) is False
    assert not fake.comment_writes
    assert fake.lead["COMMENTS"] == manual


@pytest.mark.parametrize("spoiled", [
    "Досье:\nНаправление: что угодно",                          # портал срезал «бота»
    "Досье бота:\nДиалог: [URL=https://x/t/1]ссылка[/URL]",      # портал добавил BBCode
])
def test_our_dossier_survives_portal_damage(spoiled):
    """Ложноположительный к тестам выше: искажённое порталом досье обязано остаться нашим.

    Иначе возвращается авария 17.08 — бот не узнаёт свой текст и замолкает по карточке
    навсегда.
    """
    fake = FakeAdapter(comments=spoiled)
    assert _sync(_conv(dossier_by_bot=True), fake) is True
    assert fake.comment_writes
