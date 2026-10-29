"""Сводка пилота по направлению: цифры для руководителя (ТЗ UI-04, REPORT-05). Только чтение.

Те же правила, что у `scripts/pilot_daily_summary.py`:
- **эпизод ожидания** — от сообщения клиента до первого ответа (менеджера или бота), в
  рабочих минутах по часам приёма (`reply_sla.working_minutes`); без ответа — до конца
  периода (или до «сейчас» для сегодняшнего дня). **Отличие от скрипта** (ревью ux, P5):
  эпизод, начатый до периода и длящийся в нём, тоже входит в период — скрипт считает
  только эпизоды, начатые внутри дня;
- «ждали дольше X» — X = `pilot_reply_sla_minutes`;
- ошибки отправки — сообщения менеджера со статусом `failed` / `unknown`;
- продажи — `sale_full_payment` из журнала при включённом B3 (`sale_by_full_payment_enabled`),
  иначе отметка «Продажа состоялась» (`outcome=won`) в журнале.

Добавлено к скрипту: новые обращения, ответы менеджеров **из панели** (журнал `send` /
`send_file` / `resend` — эхо ответов из Битрикса туда не попадает), разрез по менеджерам
и раскрытие любой цифры в список диалогов. В агрегатах нет имён и номеров.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

BISHKEK = timedelta(hours=6)
PERIODS = (("today", "Сегодня"), ("yesterday", "Вчера"), ("week", "7 дней"))
METRICS = (("new", "Новых обращений"), ("answered", "Ответили из панели"),
           ("over_sla", "Ждали дольше {sla} мин"), ("failed", "Не доставлено"),
           ("unknown", "Неизвестно, дошло ли"), ("sales", "Продажи"))
PANEL_SENDS = ("send", "send_file", "resend")
NOBODY = "—"


def _aware(at):
    if at is None:
        return None
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def period_bounds(period: str, now: datetime) -> tuple[datetime, datetime]:
    """[start, end) в UTC для местного (Бишкек) периода; сегодня и 7 дней — до «сейчас»."""
    now = now.astimezone(timezone.utc)
    local_today = (now + BISHKEK).date()

    def to_utc(d: date) -> datetime:
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - BISHKEK
    if period == "yesterday":
        return to_utc(local_today - timedelta(days=1)), to_utc(local_today)
    days_back = 6 if period == "week" else 0
    return to_utc(local_today - timedelta(days=days_back)), now


@dataclass
class Dialog:
    user_id: str
    bot_id: str
    owner: str
    created_at: datetime | None
    messages: list = field(default_factory=list)        # (sender, status, created_at)


def _episodes(d: Dialog, start: datetime, end: datetime) -> list[float]:
    """Ожидания, которые ПЕРЕСЕКАЮТ период [start, end), в рабочих минутах.

    Эпизод — от первого сообщения клиента после нашего ответа до следующего ответа
    менеджера или бота. Попадает в период, если хоть часть ожидания лежит в нём: клиент,
    который написал вчера вечером и ждёт до сих пор, — это и «сегодня» (ревью ux 30.10,
    P5). Длина — от сообщения клиента (а не от начала периода) до ответа; без ответа к
    концу периода — до конца периода. Так «ждал с вечера и до 9:20 утра» — одно долгое
    ожидание, а не два коротких по разные стороны полуночи.
    """
    from app.core.reply_sla import working_minutes
    out, since = [], None
    for sender, _status, at in sorted(d.messages, key=lambda m: _aware(m[2])):
        at = _aware(at)
        if at >= end:
            break
        if sender == "client":
            if since is None:
                since = at
        elif since is not None:
            if at > start:                       # ответ пришёл уже в периоде
                out.append(working_minutes(d.bot_id, since, at))
            since = None
    if since is not None:                        # к концу периода ответа нет
        out.append(working_minutes(d.bot_id, since, end))
    return out


def compute(dialogs: list[Dialog], audit: list[dict], start: datetime, end: datetime, *,
            sla: int, sales_action: str) -> dict:
    """Агрегаты и раскрытие. `audit` — строки журнала за период (manager/action/user_id/detail)."""
    by_id = {d.user_id: d for d in dialogs}
    ids: dict[str, set[str]] = {m: set() for m, _ in METRICS}
    per: dict[str, dict[str, set[str]]] = {}
    max_wait = 0.0
    episodes_total = 0

    def put(metric, manager, user_id):
        ids[metric].add(user_id)
        per.setdefault(manager or NOBODY, {m: set() for m, _ in METRICS})[metric].add(user_id)

    for d in dialogs:
        created = _aware(d.created_at)
        if created is not None and start <= created < end:
            put("new", d.owner, d.user_id)
        waits = _episodes(d, start, end)
        episodes_total += len(waits)
        if waits:
            max_wait = max(max_wait, max(waits))
        if any(w > sla for w in waits):
            put("over_sla", d.owner, d.user_id)
        for sender, status, at in d.messages:
            at = _aware(at)
            if sender == "manager" and start <= at < end and status in ("failed", "unknown"):
                put(status, d.owner, d.user_id)
    for row in audit:
        uid = row.get("user_id") or ""
        if uid not in by_id:
            continue
        action = row.get("action")
        if action in PANEL_SENDS:
            put("answered", row.get("manager") or "", uid)
        elif action == sales_action and (sales_action != "outcome" or row.get("detail") == "won"):
            put("sales", row.get("manager") or "", uid)
    managers = [{"login": login, **{m: len(v) for m, v in metrics.items()}}
                for login, metrics in sorted(per.items(), key=lambda kv: (kv[0] == NOBODY, kv[0]))]
    return {"totals": {m: len(v) for m, v in ids.items()}, "ids": ids, "managers": managers,
            "per_ids": per, "max_wait": round(max_wait, 1), "episodes": episodes_total}


# ------------------------------ загрузка ------------------------------

# Пачка `IN (...)` для карточек раскрытия: у asyncpg предел 32 767 параметров (ревью ux, P1).
CARD_BATCH = 500


def _sessionmaker(store):
    sm = getattr(store, "_sm", None)
    if sm is not None:
        return sm()
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


async def load(bot_ids: set[str], start: datetime, end: datetime) -> tuple[list[Dialog], list[dict]]:
    """Диалоги ботов направления с сообщениями окна [start − 2 дня, end) и журнал периода.

    Окно на 2 дня раньше начала — чтобы увидеть ожидание, начавшееся до периода (P5);
    ожидание, начатое ещё раньше, видно с первого сообщения клиента внутри окна.
    Память панели (тесты) — из неё; Postgres (прод) — тремя запросами: скалярные колонки
    диалогов ботов, сообщения окна через JOIN по боту (без списка id в `IN`), журнал."""
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    window = start - timedelta(days=2)
    memory = getattr(store, "_conv", None)
    if memory is not None:
        dialogs = []
        for c in memory.values():
            if (c.bot_id or "") not in bot_ids:
                continue
            msgs = [(m.sender, m.status or "", m.created_at) for m in c.messages
                    if m.created_at is not None and window <= _aware(m.created_at) < end]
            first = min((_aware(m.created_at) for m in c.messages if m.created_at), default=None)
            dialogs.append(Dialog(c.user_id, c.bot_id, c.assigned_to or "", first, msgs))
        audit = [r for r in store._audit if start <= _aware(r["created_at"]) < end]
        return dialogs, audit
    from sqlalchemy import select
    from app.integrations.crm.db import AuditLog, Conversation, ConvMessage
    bots = sorted(bot_ids)
    if not bots:
        return [], []
    async with _sessionmaker(store)() as s:
        convs = (await s.execute(select(Conversation.id, Conversation.user_id, Conversation.bot_id,
                                        Conversation.assigned_to, Conversation.created_at)
                                 .where(Conversation.bot_id.in_(bots)))).all()
        by_pk = {pk: Dialog(uid, bot, owner or "", created) for pk, uid, bot, owner, created in convs}
        rows = (await s.execute(select(ConvMessage.conversation_id, ConvMessage.sender,
                                       ConvMessage.status, ConvMessage.created_at)
                                .join(Conversation, Conversation.id == ConvMessage.conversation_id)
                                .where(Conversation.bot_id.in_(bots),
                                       ConvMessage.created_at >= window,
                                       ConvMessage.created_at < end))).all()
        for pk, sender, status, at in rows:
            if pk in by_pk:
                by_pk[pk].messages.append((sender, status or "", at))
        audit = [{"manager": m, "action": a, "user_id": u, "detail": d, "created_at": at}
                 for m, a, u, d, at in
                 (await s.execute(select(AuditLog.manager, AuditLog.action, AuditLog.user_id,
                                         AuditLog.detail, AuditLog.created_at)
                                  .where(AuditLog.created_at >= start, AuditLog.created_at < end)))
                 .all()]
    return list(by_pk.values()), audit


async def cards(user_ids: list[str]) -> dict:
    """Лёгкие карточки для раскрытия: скалярные колонки диалога, БЕЗ истории сообщений.

    Раньше раскрытие делало до 200 `store.get` — каждый тянул всю переписку (ревью ux, P1;
    ср. 21.10: инбокс на полной истории держал CPU на 100%). `IN` — пачками `CARD_BATCH`."""
    from dataclasses import is_dataclass, replace
    from app.integrations.panel.store import _view, get_conversation_store
    store = get_conversation_store()
    memory = getattr(store, "_conv", None)
    if memory is not None:
        return {uid: (replace(memory[uid], messages=[]) if is_dataclass(memory[uid]) else memory[uid])
                for uid in user_ids if uid in memory}
    from sqlalchemy import select
    from app.integrations.crm.db import Conversation
    out = {}
    async with _sessionmaker(store)() as s:
        for i in range(0, len(user_ids), CARD_BATCH):
            batch = user_ids[i:i + CARD_BATCH]
            for conv in (await s.execute(select(Conversation)
                                         .where(Conversation.user_id.in_(batch)))).scalars().all():
                out[conv.user_id] = _view(conv)
    return out
