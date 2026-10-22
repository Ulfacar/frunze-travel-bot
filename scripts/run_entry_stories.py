#!/usr/bin/env python3
"""Прогон клиентских историй въездной ветки через настоящего бота.

Зачем отдельно от `run_scenarios.py`. Тот судит качество продажи туров и отдаёт
смысловые решения LLM-судье. Здесь предмет другой: бот излагает закон чужой страны.
Поэтому судим детерминированно — вердиктом движка, сработками ремней и наличием
обязательных и запрещённых подстрок. Мнение модели о модели тут не доказательство.

Истории берутся из `scenarios/kg_entry_stories.json`, каждая со ссылкой на строку ТЗ.
У каждой есть честное поле `covered`: обслуживает ли её текущее ядро. Где нет — бот
обязан передать человеку, и это проверяется так же строго, как правильный ответ.

Изоляция от прода: состояние, CRM и панель принудительно в памяти ДО импорта
приложения, как в `run_scenarios.py`. Прогон не создаёт ни лида в Битриксе, ни
карточки в панели, ни заявки менеджеру.

Запуск:
    python scripts/run_entry_stories.py                  # все истории
    python scripts/run_entry_stories.py --only b8_3      # одна
    python scripts/run_entry_stories.py --no-llm         # без модели, только движок
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys

os.environ["CRM_BACKEND"] = "stub"
os.environ["STATE_BACKEND"] = "memory"
os.environ["PANEL_BACKEND"] = "memory"
os.environ["DEBOUNCE_SECONDS"] = "0"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.channels.base import Message                                   # noqa: E402
from app.config import BotConfig, settings                              # noqa: E402
from app.core import flags                                              # noqa: E402
from app.core.orchestrator import Orchestrator                          # noqa: E402
from app.core.state import get_state_store                              # noqa: E402

STORIES = ROOT / "scenarios" / "kg_entry_stories.json"
BOT_ID = "sim_getvisa_entry"


class CollectChannel:
    """Канал-сборщик: реплики никуда не уходят, только копятся."""

    name = "telegram"

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id: str, text: str, **kw):
        self.sent.append((chat_id, text))
        return True

    async def parse(self, raw):  # pragma: no cover — вебхук здесь не используется
        raise NotImplementedError


async def prepare_flags() -> None:
    """Въездная ветка и речь включены только этому симулятору."""
    await flags.set_flag(f"kg_entry_enabled:{BOT_ID}", True)
    await flags.set_flag(f"kg_entry_say_confirmed_enabled:{BOT_ID}", True)
    await flags.set_flag(f"kg_entry_knowledge_enabled:{BOT_ID}", True)
    await flags.set_flag("bots_enabled", True)
    await flags.set_flag(f"bots_enabled:{BOT_ID}", True)
    # Ночной режим иначе заткнул бы бота днём и прогон был бы пустым.
    await flags.set_flag("night_mode_enabled", False)
    await flags.set_flag(f"night_mode_enabled:{BOT_ID}", False)
    await flags.set_flag("bitrix_mirror_enabled", False)
    await flags.set_flag("instant_handoff_enabled", False)
    await flags.set_flag("visa_autoassign_enabled", False)


def _hit(needle: str, text: str) -> bool:
    """Подстрока, либо альтернатива через «|». Метасимволы экранируются.

    Экранировать обязательно: среди запрещённых подстрок есть «$», а в регулярном
    выражении это конец строки — такое условие совпало бы с любым ответом.
    """
    return any(re.search(re.escape(part), text, re.IGNORECASE)
               for part in needle.split("|") if part)


def verdict_for(state) -> dict:
    """Что посчитал движок по собранным ботом фактам."""
    from app.knowledge.entry_regime import EntryQuery, evaluate

    kg = (getattr(state, "qualification", {}) or {}).get("kg_entry") or {}
    iso = kg.get("citizenship_iso3")
    if not iso:
        return {"citizenship_iso3": None}
    verdict = evaluate(EntryQuery(
        citizenship_iso3=iso, document_type=kg.get("document_type") or "ordinary",
        purpose=kg.get("purpose"), location=kg.get("location"),
        entry_on=kg.get("entry_on"), exit_on=kg.get("exit_on")))
    return {"citizenship_iso3": iso, "regime": verdict.regime,
            "stay_limit_days": verdict.stay_limit_days,
            "window_days": verdict.window_days,
            "sayable": sorted(verdict.sayable), "withheld": list(verdict.withheld)}


def judge(story: dict, replies: list[str], state) -> tuple[list[str], list[str], dict]:
    """Детерминированная оценка. Возвращает (провалы, замечания, вердикт движка)."""
    fails: list[str] = []
    notes: list[str] = []
    text = "\n".join(replies)

    if not text.strip():
        fails.append("бот не ответил вообще")
        return fails, notes, verdict_for(state)

    for needle in story.get("must") or ():
        if not _hit(needle, text):
            fails.append(f"нет обязательного: {needle!r}")
    for needle in story.get("must_not") or ():
        if _hit(needle, text):
            fails.append(f"есть запрещённое: {needle!r}")

    got = verdict_for(state)
    for field, expected in (story.get("expect_engine") or {}).items():
        actual = got.get(field)
        if actual != expected:
            fails.append(f"движок: {field} = {actual!r}, ожидалось {expected!r}")

    kg = (getattr(state, "qualification", {}) or {}).get("kg_entry") or {}
    handed = bool(kg.get("handoff_reason"))
    if story.get("expect_handoff") and not handed:
        notes.append("передачи человеку не было (ТЗ по этой истории её требует)")
    if not story.get("expect_handoff") and handed:
        notes.append("бот передал человека, хотя мог ответить сам")

    # Ремни: любая сработка на истории, где бот обязан отвечать по существу, — сигнал.
    from app.agent.validator import validate_reply
    allowed = frozenset(got.get("sayable") or ())
    for reply in replies:
        _, violations = validate_reply(reply, "visa", profile="kg_entry",
                                       allowed_claims=allowed)
        for v in violations:
            if v.startswith("kg_entry_forbidden_") or v in (
                    "kg_entry_price_blocked", "kg_entry_guarantee_blocked",
                    "kg_entry_remaining_days_blocked"):
                fails.append(f"ремень сработал на выходе бота: {v}")
    return fails, notes, got


async def run_story(story: dict, *, llm: bool) -> dict:
    bot = BotConfig(id=BOT_ID, scenario="visa")
    channel = CollectChannel()
    orch = Orchestrator(channel=channel, bot=bot)
    stamp = datetime.now(timezone.utc).timestamp()
    user_id = f"sim-{story['id']}-{stamp}"
    replies: list[str] = []
    transcript: list[tuple[str, str]] = []

    for line in story["messages"]:
        transcript.append(("клиент", line))
        before = len(channel.sent)
        await orch.handle(Message(channel="telegram", user_id=user_id,
                                  chat_id=user_id, text=line))
        for _, reply in channel.sent[before:]:
            replies.append(reply)
            transcript.append(("бот", reply))

    state = await get_state_store().load(f"{BOT_ID}:{user_id}")
    fails, notes, got = judge(story, replies, state)
    return {"id": story["id"], "title": story["title"], "source": story["source"],
            "covered": story.get("covered"), "expect_product": story.get("expect_product"),
            "transcript": transcript, "fails": fails, "notes": notes, "verdict": got,
            "llm": llm}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="подстрока id истории")
    parser.add_argument("--no-llm", action="store_true", help="без модели")
    # Путь задаётся отдельно, потому что в боевом контейнере каталог приложения
    # непривилегированному пользователю не записывается, и файл историй кладётся в /tmp.
    parser.add_argument("--stories", default=str(STORIES), help="файл историй")
    args = parser.parse_args()

    if args.no_llm:
        settings.openrouter_api_key = ""

    doc = json.loads(Path(args.stories).read_text(encoding="utf-8"))
    stories = [s for s in doc["stories"] if args.only in s["id"]]
    if not stories:
        print("ни одна история не подошла под фильтр")
        return 2

    await prepare_flags()
    print(f"историй: {len(stories)} | модель: {'нет' if args.no_llm else 'живая'}")
    print(f"источник: {doc['_meta']['source']}")
    print("=" * 78)

    results = []
    for story in stories:
        res = await run_story(story, llm=not args.no_llm)
        results.append(res)
        mark = "ПРОВАЛ" if res["fails"] else "ок"
        print(f"\n[{mark}] {res['id']} — {res['title']}")
        print(f"   ТЗ: {res['source']} | покрыто ядром: {res['covered']}")
        for who, line in res["transcript"]:
            prefix = "  клиент: " if who == "клиент" else "  бот   : "
            print(prefix + line.replace("\n", "\n           "))
        v = res["verdict"]
        if v.get("citizenship_iso3"):
            print(f"   движок: {v['citizenship_iso3']} · {v.get('regime')} · "
                  f"{v.get('stay_limit_days')}/{v.get('window_days')} · "
                  f"можно: {v.get('sayable') or 'ничего'}"
                  + (f" · скрыто: {v['withheld']}" if v.get("withheld") else ""))
        else:
            print("   движок: гражданство не записано")
        for f in res["fails"]:
            print(f"   ✗ {f}")
        for n in res["notes"]:
            print(f"   · {n}")

    print("\n" + "=" * 78)
    bad = [r for r in results if r["fails"]]
    print(f"ИТОГ: историй {len(results)}, с провалами {len(bad)}")
    for r in bad:
        print(f"   {r['id']}: {'; '.join(r['fails'])}")
    print("\nПОКРЫТИЕ ТЗ (что предписывает источник там, где ядро ещё не умеет):")
    for r in results:
        if r["covered"] is False:
            print(f"   {r['id']}: {r['expect_product']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(main()))
