"""Авто-исход диалога через LLM (advisory) — сметает менеджерам ручную разметку исходов.

Менеджеры не жмут кнопки исхода → win-rate/воронки врут. Этот sweep раз в час читает
переписку застойных диалогов и классифицирует won/lost/ghosted/active дешёвой моделью
(Haiku), пишет в ОТДЕЛЬНОЕ поле `outcome_inferred` (ручной `outcome` не трогаем —
менеджер всегда авторитетнее). ВЫКЛ по умолчанию (`outcome_infer_enabled`): стоит денег.

Чистые функции (_candidates, _parse) — тестируемы без LLM; _classify изолирует вызов.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.config import settings
from app.core.leadstate import looks_unseen_conversation

log = logging.getLogger("outcome_infer")

_RUN_EVERY_SECONDS = 3600
_last_run = 0.0
_VALID = {"won", "lost", "ghosted", "active"}
_MANUAL_FINAL = {"won", "lost"}          # ручной финал — не переклассифицируем
_TERMINAL_INFERRED = {"won", "lost", "ghosted"}  # ИИ-финал заморожен; "active" — переоцениваем позже

# На какое последнее сообщение мы уже судили этот диалог: user_id → ts(last_message_at).
# In-memory (как `_checked` в manager_sync): сброс при рестарте безвреден — будет один
# лишний круг. Отдельного поля в БД нет, а миграция ради экономии не стоит своего риска.
_judged_on: dict[str, float] = {}

_SYSTEM = (
    "Ты классифицируешь ИСХОД диалога турагентства/визового центра по переписке.\n"
    "Ответь СТРОГО одним словом на первой строке из списка:\n"
    "WON — клиент оплатил, оформил, точно покупает;\n"
    "LOST — явно отказался, выбрал другое агентство, передумал;\n"
    "GHOSTED — пропал после цены/вопроса, не купил и молчит;\n"
    "ACTIVE — диалог живой, рано судить.\n"
    "На второй строке — короткая причина (до 10 слов) с опорой на слова клиента."
)


def _ghost_hours(conv, now: datetime) -> float:
    dt = getattr(conv, "last_message_at", None)
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600)


def _message_stamp(conv) -> float:
    """Время последнего сообщения как число. 0.0 — неизвестно (тогда не экономим).

    Допущение: клиентское сообщение ВСЕГДА двигает `last_message_at`. Единственное место,
    где в проекте бывает иначе — `add_message(..., counts_as_reply=False)` для аварийной
    отписки (`app/integrations/panel/store.py`), и оно только для реплик бота. Если этот
    флаг когда-нибудь распространят на клиентские сообщения, экономия ниже станет врать.
    """
    dt = getattr(conv, "last_message_at", None)
    if dt is None:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _candidates(convs: list, now: datetime, stale_hours: int, limit: int,
                judged: dict[str, float] | None = None) -> list:
    """Застойные диалоги без ручного финала и без свежего инференса — старые первыми.

    `judged` (user_id → ts последнего сообщения, на который уже судили) включает экономию:
    «active» без новых сообщений не пересуживается — по той же переписке модель скажет то же.
    None — прежнее поведение (пересуживаем всё), это состояние флага OFF.
    """
    out = []
    for c in convs:
        if (getattr(c, "outcome", "") or "") in _MANUAL_FINAL:
            continue                                   # менеджер уже отметил — не трогаем
        if (getattr(c, "outcome_inferred", "") or "") in _TERMINAL_INFERRED:
            continue                                   # терминальный ИИ-исход заморожен ("active" — нет)
        if judged is not None and (getattr(c, "outcome_inferred", "") or "") == "active":
            stamp = _message_stamp(c)
            if stamp and judged.get(getattr(c, "user_id", "") or "") == stamp:
                continue                               # с прошлого суда сообщений не было
        if _ghost_hours(c, now) < stale_hours:
            continue                                   # ещё живой/свежий
        if not getattr(c, "messages", None):
            continue
        if looks_unseen_conversation(c):
            continue                                   # одни клиентские реплики — судить не по чему:
                                                       # менеджер мог вести клиента мимо нас
        out.append(c)
    # приоритет: сперва ни разу не размеченные (""), потом "active" на переоценку; внутри — старые первыми
    out.sort(key=lambda c: ((getattr(c, "outcome_inferred", "") or "") != "",
                            getattr(c, "last_message_at", now) or now))
    return out[:limit]


def _transcript(conv, max_msgs: int = 30) -> str:
    rows = []
    for m in (getattr(conv, "messages", []) or [])[-max_msgs:]:
        who = {"client": "Клиент", "bot": "Бот", "manager": "Менеджер"}.get(m.sender, m.sender)
        rows.append(f"{who}: {m.text}")
    return "\n".join(rows)


def _parse(text: str) -> tuple[str, str]:
    """LLM-ответ → (label, reason). Неизвестное слово → ('active', ...)."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "active", ""
    # strip пунктуацию ПЕРЕД индексом: строка вида "!!!"/"..." даёт пустой split → не падаем
    parts = lines[0].lower().strip(".:,!").split()
    first = parts[0] if parts else ""
    label = first if first in _VALID else "active"
    reason = lines[1][:150] if len(lines) > 1 else ""
    return label, reason


async def _classify(conv) -> tuple[str, str] | None:
    from app.agent.llm import chat
    resp = await chat(_SYSTEM, [{"role": "user", "content": _transcript(conv)}],
                      model=settings.llm_model_cheap, tools=[], cacheable_system=False,
                      bot_id=getattr(conv, "bot_id", ""), user_id=getattr(conv, "user_id", ""))
    text = " ".join(b.get("text", "") for b in resp.get("content", [])
                    if b.get("type") == "text")
    text = "\n".join(part for part in text.replace(" \n", "\n").split("\n"))
    return _parse(text)


async def run() -> None:
    """Джоба планировщика: классифицировать исход застойных диалогов (если включено)."""
    global _last_run
    from app.core import flags
    if not await flags.get_flag("outcome_infer_enabled", settings.outcome_infer_enabled):
        return
    now_ts = time.time()
    if now_ts - _last_run < _RUN_EVERY_SECONDS:
        return
    _last_run = now_ts

    from app.agent.llm import llm_available
    from app.core import budget
    if not await llm_available():
        return  # LLM выключен или дневной бюджет исчерпан — не тратим

    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    convs = await store.all_conversations()
    now = datetime.now(timezone.utc)
    skip_unchanged = await flags.get_flag("outcome_infer_skip_unchanged_enabled",
                                          settings.outcome_infer_skip_unchanged_enabled)
    cands = _candidates(convs, now, settings.outcome_infer_stale_hours,
                        settings.outcome_infer_max_per_run,
                        judged=_judged_on if skip_unchanged else None)
    done = 0
    for c in cands:
        if await budget.hard_capped():
            break  # бюджет исчерпался в процессе — не конкурируем с живым ботом
        try:
            result = await _classify(c)
        except Exception:  # noqa: BLE001
            log.warning("outcome_infer classify failed for %s", getattr(c, "user_id", "?"),
                        exc_info=True)
            continue
        if not result:
            continue
        label, reason = result
        await store.update_meta(c.user_id, outcome_inferred=label, outcome_inferred_reason=reason)
        # Отметку ставим независимо от флага: тогда включение экономит сразу, а не через круг.
        _judged_on[c.user_id] = _message_stamp(c)
        done += 1
    if done:
        log.info("outcome_infer: классифицировано %d диалогов", done)
