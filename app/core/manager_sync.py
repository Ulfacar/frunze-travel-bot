"""Подтягиваем ответы менеджеров, отправленные с телефона, в панель.

Зачем. 31.07.2026 Гриша спросил: «если диалог перехватили, почему он до сих пор ждёт
ответа?». Разбор: колонка «ждёт ответа» снимается ответом менеджера — но за неделю в базе
оказалось НОЛЬ сообщений с `sender='manager'` при 980 клиентских. Менеджеры отвечают со
своих телефонов, а профиль Wappi подписан только на `incoming_message` (проверено:
`webhook_types = [incoming_message, delivery_status, authorization_status]`), поэтому эхо
исходящих до нас не долетает. Последствия: перехваченный диалог висит «ждёт ответа» вечно,
алерт «клиент ждёт живого менеджера» дёргает впустую, а в панели переписка неполная —
виден вопрос клиента, но не виден ответ.

Правильное лечение — включить тип вебхука в кабинете Wappi. Этот модуль решает две задачи,
которых галочка не закрывает: **чинит уже накопившееся прошлое** (галочка работает только
вперёд) и страхует, если её забудут проставить на новом профиле.

Как отличаем ответ менеджера от сообщения бота — без эвристик по тексту:
берём только исходящие, которые НОВЕЕ последнего сообщения в диалоге. Диалог попадает в
обработку, лишь когда последним писал клиент, — значит после него мы не записали ничего,
и любое исходящее позже этой отметки написал человек. Свои отправки бот пишет сам и с
`provider_msg_id`, так что перепутать нечего.

Повторный запуск безопасен: каждое подтянутое сообщение помечается ключом `wappi:<id>`,
дедуп идёт по нему.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.channels.wappi import WappiAdapter, is_manager_reply, message_time
from app.config import settings

log = logging.getLogger("manager_sync")

# Стадии «у человека»: здесь бот молчит и отвечать должен менеджер (как в awaiting.py).
_HANDOFF_STAGES = ("manager", "manager_handoff")
# Глубина разбора: старее — уже не рабочая лента, а архив.
LOOKBACK_DAYS = 14
# Сколько диалогов обрабатываем за прогон: у Wappi суточный лимит запросов, а джоба
# крутится каждые 5 минут — незачем выгребать всё подряд.
BATCH = 25
# Один и тот же ждущий диалог не опрашиваем чаще этого: пока менеджер не ответил, он
# остаётся в выборке, и без кулдауна мы дёргали бы Wappi по нему каждые 5 минут.
# In-memory (как `_alerted` в awaiting.py): сброс при рестарте безвреден.
RECHECK_MINUTES = 30
_checked: dict[int, datetime] = {}

# Устойчивый отказ Wappi по конкретному чату держим в карантине.
# 28.09.2026: один диалог (3671, номер 996552255755) стабильно отдавал `400 Bad Request`
# на `/api/sync/messages/get` и давал 96 полных стеков за 48 часов — по одному каждые
# `RECHECK_MINUTES`. Повтор бессмысленен: это ответ ПО ДАННЫМ (чата нет, номер не в
# WhatsApp), а не сбой связи, зато он жжёт суточную квоту Wappi и топит лог, в котором
# потом не видно настоящих аварий.
REJECT_HOURS = 24
# 429 и 5xx сюда намеренно не входят: это «приходи позже», а не «никогда».
_REJECT_CODES = (400, 404)
_rejected: dict[int, datetime] = {}
# Сколько карантинов за один прогон считаем не «битым чатом», а поломкой на стороне Wappi
# (сменился токен, поехали параметры, инцидент у провайдера). Один битый чат — это 1 в
# прогон; если разом отказали несколько, то молчаливый карантин на сутки спрячет от нас
# то, что ответы менеджеров перестали доезжать до панели ВООБЩЕ.
QUARANTINE_ALARM = 3

FLAG = "manager_sync_enabled"


def permanent_rejection_code(exc: BaseException) -> int | None:
    """Код устойчивого отказа по этому чату, иначе None. Чистая, чтобы её можно было тестировать."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        code = int(exc.response.status_code)
        if code in _REJECT_CODES:
            return code
    return None


def looks_like_access_failure(quarantined: int) -> bool:
    """Похоже ли это на поломку доступа, а не на битые чаты. Чистая — тестируется без БД."""
    return quarantined >= QUARANTINE_ALARM


def _adapters() -> dict[str, WappiAdapter]:
    """Свой адаптер на каждого бота: profile_id у каждого номера собственный."""
    return {b.id: WappiAdapter(bot=b) for b in settings.bots if b.wappi_profile_id}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def select_missing_replies(raw_messages: list[dict], *, after: datetime,
                           known_ids: set[str]) -> list[dict]:
    """Исходящие человека новее отметки `after`, которых у нас ещё нет. Старое → новое."""
    cutoff = int(_aware(after).timestamp()) if after else 0
    out = []
    for raw in raw_messages:
        if not is_manager_reply(raw):
            continue
        if message_time(raw) <= cutoff:
            continue                       # не новее последнего сообщения клиента
        if str(raw.get("id") or "") in known_ids:
            continue                       # уже записано (наше или подтянутое раньше)
        out.append(raw)
    return sorted(out, key=message_time)


async def sync_conversation(session, conv, adapter: WappiAdapter) -> int:
    """Подтянуть пропущенные ответы менеджера в один диалог. Вернуть, сколько добавлено."""
    from app.integrations.crm.db import ConvMessage

    phone = (conv.phone or conv.user_id or "").split(":")[-1]
    if not phone:
        return 0
    raw_messages = await adapter.fetch_chat_messages(phone)
    if not raw_messages:
        return 0

    known = {row for row in (await session.execute(
        select(ConvMessage.provider_msg_id).where(ConvMessage.conversation_id == conv.id)
    )).scalars().all() if row}
    known |= {row.split("wappi:", 1)[1] for row in (await session.execute(
        select(ConvMessage.idempotency_key).where(ConvMessage.conversation_id == conv.id)
    )).scalars().all() if row and row.startswith("wappi:")}

    missing = select_missing_replies(raw_messages, after=_aware(conv.last_message_at),
                                     known_ids=known)
    if not missing:
        return 0

    for raw in missing:
        msg_id = str(raw.get("id") or "")
        session.add(ConvMessage(
            conversation_id=conv.id,
            sender="manager",
            text=str(raw.get("body") or "").strip(),
            provider_msg_id=msg_id,
            idempotency_key=f"wappi:{msg_id}",
            # Время настоящее, а не «сейчас»: иначе в панели ответ недельной давности
            # всплывёт как свежий и перепутает сортировку рабочих списков.
            created_at=datetime.fromtimestamp(message_time(raw), tz=timezone.utc),
        ))

    newest = missing[-1]
    conv.last_sender = "manager"
    conv.last_text = str(newest.get("body") or "").strip()
    conv.last_message_at = datetime.fromtimestamp(message_time(newest), tz=timezone.utc)
    return len(missing)


async def run(*, sessionmaker=None, limit: int = BATCH, force: bool = False) -> dict:
    """Разобрать диалоги, которые числятся ждущими ответа. Точка для планировщика.

    `force` снимает кулдаун — для разового разбора накопившегося прошлого.
    """
    from app.core import flags
    from app.integrations.crm.db import Conversation, get_sessionmaker

    if not force and not await flags.get_flag(FLAG, True):
        return {"checked": 0, "fixed": 0, "added": 0}

    adapters = _adapters()
    if not adapters:
        return {"checked": 0, "fixed": 0, "added": 0}

    sm = sessionmaker or get_sessionmaker()
    since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    checked = fixed = added = quarantined = 0
    async with sm() as session:
        convs = (await session.execute(
            select(Conversation)
            .where(Conversation.last_sender == "client",
                   Conversation.last_message_at >= since,
                   Conversation.bot_id.in_(list(adapters)))
            .order_by(Conversation.last_message_at.desc())
            .limit(limit)
        )).scalars().all()
        # Ждут ответа только те, кого забрал человек: либо перехват, либо стадия хендоффа.
        convs = [c for c in convs if c.intercepted or (c.stage or "") in _HANDOFF_STAGES]

        now = datetime.now(timezone.utc)
        never = datetime.min.replace(tzinfo=timezone.utc)
        cooldown = timedelta(minutes=RECHECK_MINUTES)
        quarantine = timedelta(hours=REJECT_HOURS)
        for conv in convs:
            if not force and now - _checked.get(conv.id, never) < cooldown:
                continue                   # недавно смотрели, менеджер ещё не ответил
            if not force and now - _rejected.get(conv.id, never) < quarantine:
                continue                   # Wappi по этому чату уже сказал «нет»
            _checked[conv.id] = now
            checked += 1
            try:
                n = await sync_conversation(session, conv, adapters[conv.bot_id])
            except Exception as exc:  # noqa: BLE001 — один битый диалог не должен ронять прогон
                code = permanent_rejection_code(exc)
                if code is not None:
                    _rejected[conv.id] = now
                    quarantined += 1
                    # Без стека: стек тут ничего не добавляет, а повторяется он сутками.
                    log.warning("manager_sync: Wappi отказал по диалогу %s (HTTP %s) — "
                                "молчим по нему %s ч", conv.id, code, REJECT_HOURS)
                else:
                    log.warning("manager_sync: диалог %s не разобран", conv.id, exc_info=True)
                continue
            if n:
                fixed += 1
                added += n
        await session.commit()

    if fixed:
        log.info("manager_sync: подтянуто %s ответов в %s диалогов (проверено %s)",
                 added, fixed, checked)
    if looks_like_access_failure(quarantined):
        # ERROR, а не WARNING: это уже не битый чат, а похоже на поломку у Wappi, и тогда
        # ответы менеджеров сутки не доезжают до панели по ВСЕЙ выборке — молча.
        log.error("manager_sync: Wappi отказал по %s диалогам за прогон (из %s проверенных) "
                  "— похоже на поломку доступа, а не на битые чаты", quarantined, checked)
    return {"checked": checked, "fixed": fixed, "added": added, "quarantined": quarantined}
