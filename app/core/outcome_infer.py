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

log = logging.getLogger("outcome_infer")

_RUN_EVERY_SECONDS = 3600
_last_run = 0.0
_VALID = {"won", "lost", "ghosted", "active"}
_MANUAL_FINAL = {"won", "lost"}          # ручной финал — не переклассифицируем
_TERMINAL_INFERRED = {"won", "lost", "ghosted"}  # ИИ-финал заморожен; "active" — переоцениваем позже

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


def _candidates(convs: list, now: datetime, stale_hours: int, limit: int) -> list:
    """Застойные диалоги без ручного финала и без свежего инференса — старые первыми."""
    out = []
    for c in convs:
        if (getattr(c, "outcome", "") or "") in _MANUAL_FINAL:
            continue                                   # менеджер уже отметил — не трогаем
        if (getattr(c, "outcome_inferred", "") or "") in _TERMINAL_INFERRED:
            continue                                   # терминальный ИИ-исход заморожен ("active" — нет)
        if _ghost_hours(c, now) < stale_hours:
            continue                                   # ещё живой/свежий
        if not getattr(c, "messages", None):
            continue
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
    cands = _candidates(convs, now, settings.outcome_infer_stale_hours,
                        settings.outcome_infer_max_per_run)
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
        done += 1
    if done:
        log.info("outcome_infer: классифицировано %d диалогов", done)
