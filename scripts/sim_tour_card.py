#!/usr/bin/env python3
"""Замер: что происходит с карточкой Битрикса, пока клиент передумывает.

Гоняет НАСТОЯЩЕГО бота (тот же `Orchestrator`, те же поиски TourVisor, тот же конвейер
карточек) по написанному сценарию и после каждого хода читает лид из портала: стадию и
поле COMMENTS. Ответ клиенту никуда не уходит — канал подменён на захват.

Зачем именно так, а не юнит-тестом: вопрос «успевает ли карточка за разговором» — это
вопрос калибровки, а не логики (закон 5 в `docs/venom-v2.md`). Тест проверяет «пишем ли
мы досье», а увидеть надо «сколько раз оно поменялось за живой диалог из 7 реплик».

Скрипт СОЗДАЁТ карточку в боевом портале. Телефон синтетический и помечен в имени,
после прогона лид удаляется ключом `--cleanup` (или руками по выведенному ID).

Запуск внутри контейнера прода:
    docker cp scripts/sim_tour_card.py frunze-travel-app-1:/app/
    docker exec -w /app frunze-travel-app-1 python sim_tour_card.py --run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DEBOUNCE_SECONDS", "0")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.channels.base import Message  # noqa: E402
from app.config import settings  # noqa: E402
from app.core import flags  # noqa: E402
from app.core.bots import registry  # noqa: E402
from app.core.orchestrator import Orchestrator  # noqa: E402
from app.integrations.crm import bitrix_pipeline as bp  # noqa: E402
from app.integrations.panel.store import get_conversation_store  # noqa: E402

# Синтетический номер: не пересекается с живыми, узнаётся в портале с одного взгляда.
SIM_PHONE = "996700000077"
SIM_NAME = "ТЕСТ БОТА (симуляция)"

# Два сценария. `drip` — клиент выдаёт данные по капле, как в жизни: проверяем, дойдёт ли
# бот до поиска вообще. `offer_then_change` — клиент сразу даёт всё вплоть до питания,
# получает подборку и ТОЛЬКО ПОТОМ передумывает: это и есть вопрос заказчика.
SCENARIOS: dict[str, list[tuple[str, str]]] = {
    "drip": [
        ("1", "Здравствуйте! Хотим отдохнуть, интересует Турция, Анталия"),
        ("2", "Вылет из Бишкека, с 5 по 11 сентября, двое взрослых"),
        ("3", "Бюджет до 1500 долларов на двоих"),
        ("4", "А давайте лучше ОАЭ, Дубай"),
        ("5", "И нас будет четверо: двое взрослых и двое детей, 7 и 10 лет"),
        ("6", "Бюджет тогда поднимем до 2500 долларов"),
        ("7", "И вылетать будем не из Бишкека, а из Оша"),
    ],
    "offer_then_change": [
        ("1", "Здравствуйте! Хотим в Турцию, Анталия, всё включено. Вылет из Бишкека, "
              "с 5 по 11 сентября, двое взрослых, бюджет до 1500 долларов"),
        ("2", "Да, показывайте варианты"),
        ("3", "А давайте лучше ОАЭ, Дубай"),
        ("4", "И нас будет четверо: двое взрослых и двое детей, 7 и 10 лет"),
        ("5", "Бюджет тогда поднимем до 2500 долларов"),
        ("6", "И вылетать будем не из Бишкека, а из Алматы"),
    ],
}


class NoticeBox:
    """Перехват уведомлений менеджеру: в замере их надо ВИДЕТЬ, а не отправлять.

    Подменяется транспорт, а не логика: решение «слать или молчать» остаётся настоящим,
    до Telegram дело просто не доходит.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def __call__(self, login: str, text: str) -> bool:
        self.sent.append((login, text))
        return True


class CaptureChannel:
    """Канал-заглушка: ответ бота никуда не уходит, только запоминается."""

    channel = "telegram"

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def parse(self, raw: dict) -> Message:  # pragma: no cover — не используется
        raise NotImplementedError

    async def send(self, chat_id: str, text: str, **kwargs) -> str:
        self.sent.append(text)
        return "sim"


async def _drain_background() -> None:
    """Дождаться фоновых задач конвейера: `fire()` не блокирует ответ клиенту."""
    for _ in range(20):
        pending = [t for t in bp._tasks if not t.done()]
        if not pending:
            break
        await asyncio.gather(*pending, return_exceptions=True)
    await asyncio.sleep(1.0)


async def _card(lead_id: str) -> tuple[str, str]:
    from app.integrations.crm.bitrix24 import Bitrix24Crm
    if not lead_id:
        return "", ""
    lead = await Bitrix24Crm().get_lead(lead_id)
    return str(lead.get("STATUS_ID") or ""), str(lead.get("COMMENTS") or "")


def _facts(comments: str) -> str:
    """Только фактические строки досье — по ним видно, отстала карточка или нет."""
    keep = ("Направление", "Бюджет", "Даты", "Состав", "Вылет", "Предложено")
    lines = [ln.strip() for ln in comments.splitlines() if ln.strip()]
    picked = [ln for ln in lines if ln.split(":")[0].strip() in keep]
    return " | ".join(picked) if picked else "(фактов нет)"


async def run(bot_id: str, cleanup: bool, phone: str, scenario: str, owner: str) -> int:
    turns = SCENARIOS[scenario]
    # Боевые боты живут в `registry` (WhatsApp/Открытые линии), тестовые Telegram —
    # отдельным списком `settings.telegram_bots`, как их и поднимает `main.py`.
    bot = next((b for b in registry.all() if b.id == bot_id), None)
    if bot is None:
        tb = next((t for t in settings.telegram_bots if t.id == bot_id), None)
        if tb is not None:
            from app.config import BotConfig
            bot = BotConfig(id=tb.id, scenario=tb.scenario, title=tb.title)
    if bot is None:
        known = [b.id for b in registry.all()] + [t.id for t in settings.telegram_bots]
        print(f"Бот {bot_id} не найден. Есть: {known}")
        return 2

    # Лид под симуляцию заводим сразу: ждать «близнеца от Wappi» тут нечего, канала нет.
    settings.bitrix_openline_wait_seconds = 0

    key = f"{bot_id}:{phone}"
    store = get_conversation_store()

    from app.core import offer_change_notice as notice
    notices = NoticeBox()
    notice._default_send = notices
    channel = CaptureChannel()
    orch = Orchestrator(channel, bot=bot)

    print(f"=== СИМУЛЯЦИЯ «{scenario}» на {bot_id}, диалог {key}")
    print(f"    конвейер: {await flags.get_flag(f'bitrix_pipeline_enabled:{bot_id}', False)}")
    print()

    seen_comments = ""
    changes = 0
    seen_notices = 0
    lead_id = ""

    for num, text in turns:
        before = len(channel.sent)
        await orch.handle(Message(channel="telegram", user_id=phone,
                                  chat_id=phone, text=text))
        await _drain_background()

        conv = await store.get(key)
        lead_id = (getattr(conv, "bitrix_lead_id", "") if conv else "") or lead_id
        status, comments = await _card(lead_id)
        reply = " ⏎ ".join(t.replace("\n", " ")[:160] for t in channel.sent[before:]) or "(молчит)"

        if comments and comments != seen_comments:
            changes += 1
            seen_comments = comments
            mark = "ДОСЬЕ ОБНОВЛЕНО"
        else:
            mark = "досье без изменений"

        if owner:
            await store.update_meta(key, assigned_to=owner)

        print(f"--- ход {num}")
        print(f"    клиент: {text}")
        print(f"    бот:    {reply[:200]}")
        print(f"    лид:    {lead_id or '(ещё нет)'}  стадия: {status or '—'}  [{mark}]")
        print(f"    в карточке: {_facts(comments)}")
        for _login, body in notices.sent[seen_notices:]:
            print("    📨 УВЕДОМЛЕНИЕ МЕНЕДЖЕРУ:")
            for line in body.splitlines():
                print(f"       {line}")
        seen_notices = len(notices.sent)
        print()

    print(f"=== ИТОГ: карточка {lead_id}, досье менялось {changes} раз(а) за {len(turns)} ходов")
    print(f"    уведомлений менеджеру: {len(notices.sent)}")
    print(f"    последнее состояние карточки: {_facts(seen_comments)}")

    if cleanup and lead_id:
        from app.integrations.crm.bitrix24 import Bitrix24Crm
        await Bitrix24Crm()._call("crm.lead.delete", {"id": lead_id})
        await store.update_meta(key, bitrix_lead_id="")
        print(f"    тестовый лид {lead_id} удалён из портала")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bot", default="frunze_tours_tg")
    ap.add_argument("--phone", default=SIM_PHONE)
    ap.add_argument("--owner", default="", help="логин владельца диалога (адресат сигнала)")
    ap.add_argument("--scenario", default="drip", choices=sorted(SCENARIOS))
    ap.add_argument("--run", action="store_true", help="подтверждение: пишем в боевой портал")
    ap.add_argument("--cleanup", action="store_true", help="удалить тестовый лид в конце")
    args = ap.parse_args()
    if not args.run:
        print("Скрипт создаёт карточку в боевом Битриксе. Запускать с --run.")
        return 1
    return asyncio.run(run(args.bot, args.cleanup, args.phone, args.scenario, args.owner))


if __name__ == "__main__":
    raise SystemExit(main())
