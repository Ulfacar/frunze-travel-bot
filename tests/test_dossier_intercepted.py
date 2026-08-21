"""Досье в карточке пишется и тогда, когда диалог ведёт менеджер (тумблер, дефолт OFF).

## Замер, из которого выросла задача (прод, 21.08.2026)

Требование заказчика по турам: бот ведёт карточку сам, менеджер лишь сверяется с
клиентом, когда тот физически пришёл в офис. Что было в проде через шесть часов после
подключения QR:

* 11 туровых диалогов, из них **8 перехвачены менеджером** — 5 из 5 у Адеми,
  4 из 6 у Айсины;
* `sync_dossier` выходил первой строкой на `intercepted`, значит в этих восьми карточках
  сводка не появилась бы никогда;
* за август по турам 333 диалога и 326 заведённых лидов: карточки есть, досье в них нет.

## Что закрепляем

Перехват означает «менеджер ПИШЕТ клиенту». Это не повод переставать вести карточку:
менеджеру в офисе сводка нужна ровно тогда, когда он с клиентом и разговаривает.

Тумблер отдельный от `bitrix_stage_catchup_enabled`: движение стадии и ведение досье —
разные обещания заказчику, и включать их порознь мы должны уметь.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "186443"
FACTS = {"destination": "Турция", "region": "Анталья", "dates": "05.09-11.09",
         "tourists": "2"}


class FakeAdapter:
    def __init__(self, status="NEW", comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": status, "COMMENTS": comments}
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


def _conv(*, intercepted, dossier_by_bot=False):
    key = "frunze_tours:996700208905"
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хотим в Анталью вдвоём"))
    run(store.update_meta(key, bitrix_lead_id=LEAD, intercepted=intercepted,
                          funnel="tours", qualification=dict(FACTS)))
    if dossier_by_bot:
        run(store.update_meta(key, bitrix_dossier_by_bot=True))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc)
    return key


def _sync(key, fake):
    return run(bp.sync_dossier(key, adapter=fake))


# ---------------- тумблер включён ---------------------------------------------------
def test_dossier_written_when_intercepted_and_flag_on():
    run(flags.set_flag("dossier_when_intercepted_enabled", True))
    fake = FakeAdapter()
    assert _sync(_conv(intercepted=True), fake) is True
    assert fake.comment_writes, "менеджер ведёт диалог — досье всё равно нужно в карточке"
    assert "Анталья" in fake.comment_writes[-1]


# ---------------- тумблер снят: дефолтное поведение не меняется ---------------------
def test_dossier_skipped_when_intercepted_and_flag_off():
    fake = FakeAdapter()
    assert _sync(_conv(intercepted=True), fake) is False
    assert not fake.comment_writes, "при снятом тумблере перехват по-прежнему запрещает запись"


def test_dossier_still_written_when_not_intercepted_and_flag_off():
    """Ложноположительный: обычный диалог не должен пострадать от новой развилки."""
    fake = FakeAdapter()
    assert _sync(_conv(intercepted=False), fake) is True
    assert fake.comment_writes


# ---------------- терминальные статусы неприкосновенны ------------------------------
@pytest.mark.parametrize("status", ["CONVERTED", "JUNK", "UC_R8BD0W"])
@pytest.mark.parametrize("flag_on", [True, False])
def test_dossier_skipped_on_terminal_status(status, flag_on):
    if flag_on:
        run(flags.set_flag("dossier_when_intercepted_enabled", True))
    fake = FakeAdapter(status=status)
    assert _sync(_conv(intercepted=True), fake) is False
    assert not fake.comment_writes, "закрытую карточку не трогаем ни при каком тумблере"
