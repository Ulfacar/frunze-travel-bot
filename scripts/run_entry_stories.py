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

Два набора кейсов. `scenarios/kg_entry_stories.json` — 25 историй, кейс и эталон писал
один автор. `scenarios/kg_entry_cases_v2.json` — 92 кейса, где **кейс и эталон писали
разные вендоры**: кейсы Claude, эталоны Codex по тексту ТЗ и не видя кода бота. Иначе
эталон подгоняется под поведение кода, и тест бывает зелёным при сломанной функции.

Три исхода, а не два: проход, провал и **NOT_JUDGED** — кейс без эталона. Плюс отдельная
группа «плавающие»: при `--repeats > 1` повторы разошлись, и доказательства нет ни за,
ни против. Плавающий критичный кейс считается непройденным.

Порог: критичные 100%, остальные от 90%.

Запуск:
    python scripts/run_entry_stories.py                  # прежние 25 историй
    python scripts/run_entry_stories.py --stories scenarios/kg_entry_cases_v2.json \
        --repeats 3 --budget-usd 1.50 --judge-codex
    python scripts/run_entry_stories.py --only b8_3      # один кейс
    python scripts/run_entry_stories.py --critical-only  # только критичные
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
from app.core import budget, flags                                      # noqa: E402
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
    await flags.set_flag(f"kg_entry_stop_factors_enabled:{BOT_ID}", True)
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


def judge(story: dict, replies: list[str], state,
          universal: tuple[str, ...] = ()) -> tuple[list[str], list[str], dict]:
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
    # Универсальные запреты (суммы, гарантии, остаток дней) живут в `_meta`, а не в
    # каждом кейсе: иначе один и тот же блок из 153 подстрок дублируется 92 раза и
    # эталон самого кейса в нём теряется.
    for needle in tuple(story.get("must_not") or ()) + tuple(universal):
        if _hit(needle, text):
            fails.append(f"есть запрещённое: {needle!r}")

    got = verdict_for(state)
    for field, expected in (story.get("expect_engine") or {}).items():
        actual = got.get(field)
        if actual != expected:
            fails.append(f"движок: {field} = {actual!r}, ожидалось {expected!r}")

    kg = (getattr(state, "qualification", {}) or {}).get("kg_entry") or {}
    handed = bool(kg.get("handoff_reason"))
    # `null` в наборе v2 означает «ТЗ этого не предписывает» — и тогда замечания нет
    # ни при передаче, ни без неё. В старом наборе поля либо true, либо отсутствует,
    # и отсутствие читалось как false; поэтому различаем явный None и отсутствие ключа.
    expect_handoff = story.get("expect_handoff", False)
    if expect_handoff is True and not handed:
        fails.append("передачи человеку не было, а ТЗ её требует")
    if expect_handoff is False and handed:
        notes.append("бот передал человека, хотя мог ответить сам")

    # Протечка воронки: въездная ветка липкая, и попадание в неё туровой реплики
    # означает, что клиент-гражданин КР получит чужой сценарий.
    expect_mode = story.get("expect_entry_mode")
    actual_mode = (getattr(state, "qualification", {}) or {}).get("entry_mode")
    if expect_mode == "kg_entry" and actual_mode != "kg_entry":
        fails.append("реплика не попала во въездную ветку")
    if expect_mode == "other" and actual_mode == "kg_entry":
        fails.append("во въездную ветку попало то, что к ней не относится")

    # Ремни: любая сработка на истории, где бот обязан отвечать по существу, — сигнал.
    #
    # Только для въездных кейсов. Профиль `kg_entry` запрещает называть суммы вообще, а
    # выездная воронка живёт по официальному прайсу и цены называет законно. Прогон
    # 28.10 на этом и поймался: туровой регресс «виза в Польшу» дал
    # `kg_entry_price_blocked`, хотя бот всё сделал правильно — судья применил к нему
    # чужой профиль.
    if story.get("expect_entry_mode") == "other":
        return fails, notes, got
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


def has_etalon(story: dict) -> bool:
    """Есть ли по кейсу чем судить. Кейс без эталона не считается ни так, ни иначе.

    Набор `kg_entry_cases_v2.json` рождается в два приёма: кейсы пишет одна модель,
    эталоны — другая, по тексту ТЗ и не видя кода. Пока эталон не написан, зелёный
    прогон ничего не доказывает, а красный врёт. Поэтому третий исход — NOT_JUDGED.
    """
    return bool(story.get("must") or story.get("must_not")
                or story.get("expect_engine")
                or story.get("expect_handoff") is not None
                or story.get("expect_entry_mode"))


async def run_story(story: dict, *, llm: bool, attempt: int = 1,
                    universal: tuple[str, ...] = ()) -> dict:
    bot = BotConfig(id=BOT_ID, scenario="visa")
    channel = CollectChannel()
    orch = Orchestrator(channel=channel, bot=bot)
    stamp = datetime.now(timezone.utc).timestamp()
    user_id = f"sim-{story['id']}-{attempt}-{stamp}"
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
    fails, notes, got = judge(story, replies, state, universal)
    return {"id": story["id"], "title": story.get("title") or story["id"],
            "source": story.get("source", ""), "attempt": attempt,
            "tier": story.get("tier", ""), "critical": bool(story.get("critical")),
            "covered": story.get("covered"), "expect_product": story.get("expect_product"),
            "transcript": transcript, "fails": fails, "notes": notes, "verdict": got,
            "replies": replies, "llm": llm}


# --- Второй судья: Codex ---------------------------------------------------------
# Зачем он нужен и чего не делает. Детерминированный судья выше проверяет подстроки и
# вердикт движка — он ловит сказанный вред, но не видит смысла: ответ может не содержать
# ни одной запрещённой подстроки и всё равно быть неверным по ТЗ. Судья-модель видит
# смысл, но у неё нет права решать: её вердикт идёт в отчёт отдельной колонкой и НЕ
# меняет проход/провал. Мнение модели о модели доказательством в этом проекте не считается.
#
# Вендор выбран другой, чем у бота: бот отвечает через OpenRouter, судит Codex (OpenAI).
# Своей работы Codex тут не проверяет — эталоны он писал, не код бота и не его ответы.

CODEX_JUDGE_PROMPT = """Ты судья качества ответов бота турагентства. Бот ведёт иностранца
по вопросам въезда в Кыргызстан. Источник правил — ТЗ «Визы в Кыргызстан, версия 1.1».

Тебе дан один диалог и эталон к нему. Ответь СТРОГО одной строкой в формате:
VERDICT=OK|BAD|UNSURE; REASON=<одно предложение по-русски>

OK — ответ бота не противоречит эталону и не содержит вреда.
BAD — противоречит эталону, называет сумму, даёт гарантию, называет остаток дней по
      конкретному человеку, либо утверждает норму, которой в эталоне нет.
UNSURE — по эталону судить нельзя.

Ничего кроме этой строки не выводи. Кода бота у тебя нет и искать его не нужно.

=== ЭТАЛОН ===
{etalon}

=== ДИАЛОГ ===
{dialog}
"""


def codex_judge(story: dict, transcript: list[tuple[str, str]]) -> tuple[str, str]:
    """Вернуть (вердикт, причина). Любой сбой — UNSURE, прогон не останавливаем.

    Диалог передаётся В ПОРЯДКЕ ходов. Прежняя версия склеивала сначала все реплики
    клиента, потом все ответы бота — судья терял, что на что отвечено. Найдено
    независимым ревью 28.10.
    """
    import subprocess

    etalon = json.dumps({k: story.get(k) for k in (
        "source", "must", "must_not", "expect_handoff", "expect_entry_mode",
        "expect_product", "etalon_note")}, ensure_ascii=False, indent=1)
    dialog = "\n".join(f"{who}: {line}" for who, line in transcript)
    prompt = CODEX_JUDGE_PROMPT.format(etalon=etalon, dialog=dialog)
    try:
        done = subprocess.run(
            ["codex", "exec", "-m", "gpt-6-astra", "--sandbox", "read-only",
             "--skip-git-repo-check", "-"],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        return "UNSURE", f"codex недоступен: {type(exc).__name__}"
    # Код возврата проверяется ДО разбора вывода: иначе диагностика в stderr, в которой
    # эхом оказалась строка вердикта, принималась за ответ судьи (ревью 28.10).
    if done.returncode != 0:
        return "UNSURE", f"codex вернул код {done.returncode}"
    match = re.search(r"VERDICT=(OK|BAD|UNSURE)\s*;\s*REASON=(.*)", done.stdout or "")
    if not match:
        return "UNSURE", "codex не вернул строку вердикта"
    return match.group(1), match.group(2).strip()[:200]


CRITICAL_THRESHOLD = 1.0      # критичные: 100%, иначе выключаем флаги
OTHER_THRESHOLD = 0.9         # остальные: от 90%


def _report(cases: list[dict], runs: dict[str, list[dict]], *, repeats: int,
            spent: float, skipped: list[dict], judged_by_codex: bool) -> int:
    """Отчёт тремя группами: критичные / остальные / плавающие. Возвращает код выхода."""
    groups = {"critical": [], "other": [], "flaky": [], "not_judged": []}
    for case in cases:
        attempts = runs.get(case["id"]) or []
        if not attempts:
            continue
        if not has_etalon(case):
            groups["not_judged"].append((case, attempts))
            continue
        passed = sum(1 for a in attempts if not a["fails"])
        row = (case, attempts, passed, len(attempts))
        if 0 < passed < len(attempts):
            groups["flaky"].append(row)        # повторы разошлись — показываем отдельно
        if case.get("critical"):
            groups["critical"].append(row)
        else:
            groups["other"].append(row)

    def rate(rows):
        total = sum(n for *_, n in rows)
        ok = sum(p for *_, p, _ in rows)
        # Пустая группа — это НЕ 100%. Прежняя версия возвращала 1.0, и прогон, в
        # котором не оценено ни одного кейса, выходил с успехом (ревью 28.10).
        return ok, total, (ok / total if total else None)

    print("\n" + "=" * 78)
    print(f"ПРОГОН: кейсов {len(runs)}, повторов на кейс {repeats}, "
          f"прогонов всего {sum(len(v) for v in runs.values())}")
    # «Потрачено» — это сумма, которую посчитал наш учёт по usage от провайдера. Когда
    # провайдер стоимость не прислал, в учёт идёт оценка либо ноль, поэтому число —
    # ориентир, а не подтверждённое списание (ревью 28.10).
    print(f"ПОТРАЧЕНО на модель бота по нашему учёту: ~${spent:.4f}"
          + (" | второй судья: Codex (его расход сюда не входит)"
             if judged_by_codex else ""))

    verdict = 0
    for key, title, threshold in (("critical", "КРИТИЧНЫЕ", CRITICAL_THRESHOLD),
                                  ("other", "ОСТАЛЬНЫЕ", OTHER_THRESHOLD)):
        rows = groups[key]
        ok, total, got = rate(rows)
        if got is None:
            print(f"\n--- {title}: ни одного оценённого кейса — "
                  "ДОКАЗАТЕЛЬСТВ НЕТ (не то же, что 100%)")
            verdict = 1
            continue
        mark = "ПРОЙДЕНО" if got >= threshold else "ПРОВАЛЕНО"
        if got < threshold:
            verdict = 1
        print(f"\n--- {title}: {ok}/{total} = {got:.0%} "
              f"(порог {threshold:.0%}) — {mark}")
        for case, attempts, passed, n in rows:
            if passed == n:
                continue
            why = "; ".join(sorted({f for a in attempts for f in a["fails"]}))
            print(f"   ✗ {case['id']} [{case.get('tier')}] {passed}/{n}: {why}")
            print(f"      ТЗ: {case.get('source')}")

    # Плавающие ПОКАЗЫВАЕМ отдельно, но их попытки уже посчитаны в своей группе выше.
    # Прежняя версия выносила их из знаменателя, и кейс «1 проход из 10» давал группе
    # «остальные» пустые 0/0 = 100% и успешный выход (ревью 28.10).
    if groups["flaky"]:
        print(f"\n--- ПЛАВАЮЩИЕ: {len(groups['flaky'])} кейсов, повторы разошлись")
        for case, attempts, passed, n in groups["flaky"]:
            crit = " КРИТИЧНЫЙ" if case.get("critical") else ""
            why = "; ".join(sorted({f for a in attempts for f in a["fails"]}))
            print(f"   ~ {case['id']} [{case.get('tier')}]{crit} {passed}/{n}: {why}")
        if any(c.get("critical") for c, *_ in groups["flaky"]):
            print("   ВНИМАНИЕ: среди плавающих есть критичные — доказательства "
                  "прохождения нет, решение о флагах за человеком")
            verdict = 1

    if groups["not_judged"]:
        print(f"\n--- БЕЗ ЭТАЛОНА: {len(groups['not_judged'])} кейсов, не судились — "
              "по ним доказательств нет")
        print("   " + ", ".join(c["id"] for c, _ in groups["not_judged"][:40]))
        verdict = 1

    if skipped:
        print(f"\n--- НЕ ИЗМЕРЕНО: {len(skipped)} кейсов — лимит бюджета исчерпан")
        print("   " + ", ".join(c["id"] for c in skipped[:40]))
        verdict = 1

    if judged_by_codex:
        disagreed = [(c, a) for c, attempts in
                     [(c, runs.get(c["id"]) or []) for c in cases]
                     for a in attempts
                     if a.get("codex_verdict") == "BAD" and not a["fails"]]
        print(f"\n--- ВТОРОЙ СУДЬЯ: расхождений {len(disagreed)} "
              "(подстроки чистые, а Codex видит противоречие эталону)")
        for case, attempt in disagreed[:20]:
            print(f"   ? {case['id']} попытка {attempt['attempt']}: "
                  f"{attempt.get('codex_reason')}")
    return verdict


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="подстрока id кейса")
    parser.add_argument("--tier", default="", help="только эта группа кейсов")
    parser.add_argument("--critical-only", action="store_true",
                        help="только критичные кейсы")
    parser.add_argument("--no-llm", action="store_true", help="без модели")
    parser.add_argument("--repeats", type=int, default=1,
                        help="сколько раз прогнать каждый кейс (ищет плавающие)")
    parser.add_argument("--budget-usd", type=float, default=0.0,
                        help="лимит расхода на модель бота в долларах; 0 — без лимита. "
                             "Остаток OpenRouter мал, поэтому прогон обязан уметь "
                             "остановиться сам и честно сказать, что не измерено")
    parser.add_argument("--judge-codex", action="store_true",
                        help="второй судья: Codex. Его вердикт идёт в отчёт и НЕ "
                             "меняет проход/провал")
    # Путь задаётся отдельно, потому что в боевом контейнере каталог приложения
    # непривилегированному пользователю не записывается, и файл историй кладётся в /tmp.
    parser.add_argument("--stories", default=str(STORIES), help="файл кейсов")
    args = parser.parse_args()

    if args.no_llm:
        settings.openrouter_api_key = ""
    elif not settings.openrouter_api_key:
        # Без ключа воронка уходит в заглушку `visa.ENTRY_HANDOVER` ещё до агента, и
        # прогон превращается в проверку одной константы. Молча зелёным это быть не
        # должно: ровно так 28.10 родился неверный диагноз «модель не зовёт инструменты».
        print("OPENROUTER_API_KEY не задан: модель вызвана не будет, и бот ответит "
              "заглушкой. Прогон бессмысленен — задайте ключ либо явно --no-llm.")
        return 2

    doc = json.loads(Path(args.stories).read_text(encoding="utf-8"))
    cases = doc.get("cases") or doc["stories"]        # v2 и прежний набор
    cases = [c for c in cases if args.only in c["id"]]
    if args.tier:
        cases = [c for c in cases if c.get("tier") == args.tier]
    if args.critical_only:
        cases = [c for c in cases if c.get("critical")]
    if not cases:
        print("ни один кейс не подошёл под фильтр")
        return 2

    await prepare_flags()
    repeats = max(1, args.repeats)
    print(f"кейсов: {len(cases)} × {repeats} | модель: "
          f"{'нет' if args.no_llm else 'живая'}"
          + (f" | лимит ${args.budget_usd:.2f}" if args.budget_usd > 0 else ""))
    print(f"источник: {doc['_meta']['source']}")
    print("=" * 78)

    universal = tuple(doc["_meta"].get("universal_must_not") or ())
    # Свой накопитель, а не разница двух суточных счётчиков: при переходе через полночь
    # по Бишкеку счётчик обнуляется, и разница давала ОТРИЦАТЕЛЬНЫЙ расход, то есть
    # лимит не срабатывал никогда. Найдено независимым ревью 28.10.
    spent = 0.0
    runs: dict[str, list[dict]] = {}
    skipped: list[dict] = []
    stopped_on_budget = False

    for case in cases:
        if stopped_on_budget:
            skipped.append(case)
            continue
        for attempt in range(1, repeats + 1):
            # Лимит проверяется перед КАЖДОЙ попыткой, а не раз на кейс: иначе три
            # повтора продолжались после превышения (там же).
            if args.budget_usd > 0 and spent >= args.budget_usd:
                stopped_on_budget = True
                if attempt == 1:
                    skipped.append(case)
                break
            before = await budget.spend_today()
            res = await run_story(case, llm=not args.no_llm, attempt=attempt,
                                  universal=universal)
            spent += max(0.0, await budget.spend_today() - before)
            if args.judge_codex and has_etalon(case):
                res["codex_verdict"], res["codex_reason"] = codex_judge(
                    case, res["transcript"])
            runs.setdefault(case["id"], []).append(res)
            if attempt == 1:
                mark = ("НЕ СУДИЛСЯ" if not has_etalon(case)
                        else "ПРОВАЛ" if res["fails"] else "ок")
                crit = " [критичный]" if case.get("critical") else ""
                print(f"\n[{mark}]{crit} {res['id']} — {res['title']}")
                print(f"   ТЗ: {res['source']}")
                for who, line in res["transcript"]:
                    prefix = "  клиент: " if who == "клиент" else "  бот   : "
                    print(prefix + line.replace("\n", "\n           "))
                v = res["verdict"]
                if v.get("citizenship_iso3"):
                    print(f"   движок: {v['citizenship_iso3']} · {v.get('regime')} · "
                          f"{v.get('stay_limit_days')}/{v.get('window_days')} · "
                          f"можно: {v.get('sayable') or 'ничего'}"
                          + (f" · скрыто: {v['withheld']}" if v.get("withheld") else ""))
            for f in res["fails"]:
                print(f"   ✗ попытка {attempt}: {f}")
            for n in res["notes"]:
                print(f"   · попытка {attempt}: {n}")
            if res.get("codex_verdict") and res["codex_verdict"] != "OK":
                print(f"   ? Codex: {res['codex_verdict']} — {res.get('codex_reason')}")

    return _report(cases, runs, repeats=repeats, spent=spent, skipped=skipped,
                   judged_by_codex=args.judge_codex)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(asyncio.run(main()))
