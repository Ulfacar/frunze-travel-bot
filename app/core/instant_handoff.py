"""P1.1: мгновенная передача ГОТОВОЙ заявки владельцу диалога в личный Telegram.

Главное требование встречи 29.07, дословно: «не раз в день, а сразу», «чтобы клиент не
ждал». Ночью тоже слать — «ну пусть отправляет, а что делать». И ограничение из той же
минуты, которое легко потерять: **«Главное, чтобы их это не доставало»**. Поэтому:

* мгновенно уходит ТОЛЬКО собранная заявка (бот перевёл стадию в manager/office),
  ровно один раз на заявку;
* канал можно перевести на дайджест (`instant_handoff_digest_bots`) — тогда его заявки
  копятся и уходят пачкой в 12/15/19 по Бишкеку. Это ЗАМЕНА мгновенному пушу, а не
  добавка: у менеджера два касания в день (бриф + пуш), не пять.

Дедуп сделан условным UPDATE по `conversations.handoff_notified_at`, а не флагом в
состоянии диалога: состояние живёт в Redis по одному ключу, а джобе дайджеста нужно
сканировать все диалоги разом. Это же защищает от повторного вызова инструмента —
стадия `office` бота НЕ перехватывает (`orchestrator`: `auto_handoff = stage == "manager"`),
поэтому LLM может эскалировать ещё раз на следующем ходу.

Колонка добавляется через `_ensure_columns` в `init_models`, БЕЗ Alembic-ревизии:
по доктрине `alembic/env.py` миграции ведут только доменные таблицы и legacy-схему
(`conversations`/`messages`/`deals`) не трогают вообще.

Если отправка не удалась, признак снимается обратно в NULL: заявка вернётся в дайджест,
а не потеряется молча.

Fail-safe: любой сбой здесь не должен ронять живой диалог — вызывающая сторона глушит
исключения, и внутри мы тоже ничего не поднимаем наружу.

Секреты: `telegram_chat_id` не логируется никогда.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update

from app.config import settings
from app.core.morning_brief import BISHKEK_UTC_OFFSET, _FUNNEL_LABEL

log = logging.getLogger("instant_handoff")

FLAG = "instant_handoff_enabled"
CATCHUP_FLAG = "instant_handoff_catchup_enabled"

# Границы догоняющей отправки — см. run_catchup. Пауза от последнего сообщения нужна,
# чтобы не гоняться за живым ходом: у него есть свой шанс отправить пуш.
CATCHUP_MIN_AGE = timedelta(minutes=15)
CATCHUP_CAP = 10

# Стадии «заявка собрана, дальше человек». manager_handoff/office_consultation — на
# случай, если стадию заведут под другим именем в CRM-маппинге.
HANDOFF_STAGES = ("manager", "manager_handoff", "office", "office_consultation")

# Сколько символов обещания бота показываем менеджеру: строка нужна целиком, но телега
# не должна превращаться в простыню.
PROMISE_CAP = 220
DIGEST_MANAGER_CAP = 12


def _sessionmaker(sessionmaker=None):
    if sessionmaker is not None:
        return sessionmaker
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


def _chat_id_for(login: str) -> str:
    """Личный chat_id менеджера из конфига. Пусто — значит слать некому."""
    for mgr in settings.manager_list():
        if (mgr.login or "").strip().lower() == (login or "").strip().lower():
            return (getattr(mgr, "telegram_chat_id", "") or "").strip()
    return ""


def _request_line(qualification: dict | None, funnel: str) -> str:
    """Запрос одной строкой: направление, состав, даты, бюджет — что есть, то и есть."""
    q = qualification or {}
    order = ("destination", "country", "visa_country", "dates", "period",
             "pax", "adults", "budget", "purpose")
    seen: list[str] = []
    for key in order:
        raw = q.get(key)
        if raw in (None, "", [], {}):
            continue
        text = ", ".join(str(v) for v in raw) if isinstance(raw, (list, tuple)) else str(raw)
        text = text.strip()
        if text and text not in seen:
            seen.append(text)
    return " · ".join(seen) or _FUNNEL_LABEL.get(funnel, funnel or "запрос")


def render_handoff_text(*, name: str, phone: str, request: str, promised: str,
                        link: str, wa_link: str = "",
                        waited_since: datetime | None = None) -> str:
    """Пуш читается с телефона за 20 секунд; номер тапабелен сам (международный формат).

    Строка «Бот пообещал» обязательна и всегда в кавычках: менеджер должен звонить, зная,
    что клиенту уже сказано, иначе назовёт другую цену.

    ``waited_since`` — заголовок догоняющей отправки. Менеджер обязан видеть, что заявка
    не свежая: звонить «здравствуйте, вы только что писали» по вчерашнему лиду — хуже,
    чем не звонить вовсе.
    """
    if waited_since is not None:
        local = waited_since + timedelta(hours=BISHKEK_UTC_OFFSET)
        head = f"⏰ Заявка ждёт с {local:%d.%m %H:%M} — уведомление не ушло вовремя"
    else:
        head = "🔥 Заявка готова — можно звонить"
    who = " · ".join(x for x in ((name or "").strip(), (phone or "").strip()) if x)
    lines = [head, who or "клиент без имени", request]
    if promised:
        short = promised.strip().replace("\n", " ")
        if len(short) > PROMISE_CAP:
            short = short[:PROMISE_CAP].rstrip() + "…"
        lines.append(f"Бот пообещал: «{short}»")
    if wa_link:
        lines.append(f"💬 написать: {wa_link}")
    if link:
        lines.append(f"👉 открыть диалог: {link}")
    return "\n".join(lines)


def _digest_bots() -> set[str]:
    return {b.strip() for b in (settings.instant_handoff_digest_bots or []) if b.strip()}


async def _enabled() -> bool:
    from app.core.flags import get_flag
    return await get_flag(FLAG, settings.instant_handoff_enabled)


async def _claim(session, user_id: str, now: datetime) -> bool:
    """Забрать заявку под пуш: условный UPDATE = дедуп даже при конкурентных ходах."""
    from app.integrations.crm.db import Conversation
    res = await session.execute(
        update(Conversation)
        .where(Conversation.user_id == user_id,
               Conversation.handoff_notified_at.is_(None),
               Conversation.stage.in_(HANDOFF_STAGES))
        .values(handoff_notified_at=now))
    await session.commit()
    return bool(res.rowcount)


async def _release(sm, user_id: str) -> None:
    """Вернуть заявку в очередь, если отправить не удалось (молча терять нельзя)."""
    from app.integrations.crm.db import Conversation
    try:
        async with sm() as session:
            await session.execute(
                update(Conversation).where(Conversation.user_id == user_id)
                .values(handoff_notified_at=None))
            await session.commit()
    except Exception:  # noqa: BLE001
        log.warning("instant handoff: release failed (key=%s)", user_id, exc_info=True)


async def _send(login: str, text: str) -> bool:
    from app.core.calendar_brief import _push_telegram, _token
    token = _token()
    chat_id = _chat_id_for(login)
    if not token or not chat_id:
        log.info("instant handoff: no telegram target (manager=%s)", login)
        return False
    return await _push_telegram(token, chat_id, text)


async def _send_cc(text: str, *, owner_login: str) -> bool:
    """Копия заявки владельцу бизнеса. True — доставлено хотя бы одному получателю.

    Адресат менеджера дописывается строкой: без неё владелец не поймёт, звонит уже кто-то
    или заявка повисла. Сбой копии никогда не влияет на пуш менеджеру — это наблюдение,
    а не доставка.
    """
    targets = [c.strip() for c in (settings.instant_handoff_cc_chat_ids or []) if c.strip()]
    if not targets:
        return False
    from app.core.calendar_brief import _push_telegram, _token
    token = _token()
    if not token:
        return False
    body = f"{text}\n\nМенеджер: {owner_login or '—'}"
    ok = False
    for chat_id in targets:
        try:
            ok = await _push_telegram(token, chat_id, body) or ok
        except Exception:  # noqa: BLE001
            log.warning("instant handoff: копия владельцу не ушла", exc_info=True)
    return ok


async def maybe_notify(user_id: str, *, promised: str = "", sessionmaker=None,
                       waited_since: datetime | None = None) -> bool:
    """Пуш по собранной заявке. True — отправлено. Никогда не поднимает исключение."""
    try:
        if not await _enabled():
            return False
        from app.core.calendar_brief import _client_link, _phone_display, _wa_link
        from app.integrations.crm.db import Conversation
        sm = _sessionmaker(sessionmaker)
        now = datetime.now(timezone.utc)
        async with sm() as session:
            conv = (await session.execute(select(Conversation).where(
                Conversation.user_id == user_id))).scalar_one_or_none()
            if conv is None or (conv.stage or "") not in HANDOFF_STAGES:
                return False
            if (conv.bot_id or "") in _digest_bots():
                return False          # канал на дайджесте — заберёт джоба, признак не трогаем
            login = (conv.assigned_to or "").strip()
            if not login:
                # Владельца нет — слать некому. Признак НЕ ставим: как только владелец
                # появится (autoassign/пилот/панель), заявка уйдёт следующим ходом.
                log.info("instant handoff: no owner yet (key=%s)", user_id)
                return False
            snapshot = {
                "name": ((conv.qualification or {}).get("name") or "").strip(),
                "phone": _phone_display(conv.phone or conv.user_id),
                "request": _request_line(conv.qualification, conv.funnel or ""),
                "wa": _wa_link(conv.phone or conv.user_id),
            }
            if not await _claim(session, user_id, now):
                return False          # уже отправляли (или стадия успела уехать)
        text = render_handoff_text(
            name=snapshot["name"], phone=snapshot["phone"], request=snapshot["request"],
            promised=promised, link=_client_link(user_id, settings.admin_base_url),
            wa_link=snapshot["wa"], waited_since=waited_since)
        owner_ok = await _send(login, text)
        cc_ok = await _send_cc(text, owner_login=login)
        if owner_ok:
            log.info("instant handoff: sent (manager=%s key=%s cc=%s)", login, user_id, cc_ok)
            return True
        if cc_ok:
            # Менеджеру не дошло (нет chat_id/сбой), но владелец бизнеса заявку УЖЕ видит.
            # Признак не снимаем: иначе на каждом следующем ходу клиента владельцу летела бы
            # та же карточка. Заявка не потеряна — она у владельца и в панели.
            log.warning("instant handoff: менеджеру не доставлено (manager=%s key=%s), "
                        "ушла только копия владельцу", login, user_id)
            return False
        await _release(sm, user_id)
        return False
    except Exception:  # noqa: BLE001 — фича не имеет права ронять живой диалог
        log.warning("instant handoff failed (key=%s)", user_id, exc_info=True)
        return False


async def run_catchup(*, now: datetime | None = None, sessionmaker=None) -> int:
    """Догоняющая отправка: заявка готова, владелец есть, а пуш так и не ушёл.

    Мгновенный пуш живёт внутри хода диалога — он уходит только когда бот отвечает
    клиенту. Если владельца в ту секунду ещё не было, второй попытки не случалось
    НИКОГДА: за две недели июля так осели 12 готовых заявок из 17, часть — вообще без
    звонка. Джоба закрывает ровно этот разрыв и ничего больше.

    Границы узкие намеренно — «главное, чтобы их это не доставало» (встреча 29.07):

    * окно ``instant_handoff_catchup_window_hours`` (72ч): недельную древность утром
      менеджеру не вываливаем, такой лид уже мёртв и только злит;
    * молчим, если последним в диалоге говорил менеджер — человек уже там, напоминание
      лишнее. Отметку при этом НЕ ставим: менеджер мог ответить и бросить, тогда заявку
      подберёт следующий тик, пока не истечёт окно;
    * пауза ``CATCHUP_MIN_AGE`` от последнего сообщения — живой ход имеет право
      отправить пуш сам, мы не гоняемся за ним;
    * не больше ``CATCHUP_CAP`` за тик: разовый разбор накопленного не должен
      прилететь менеджеру пачкой из тридцати карточек.

    Каналы на дайджесте и дедуп не трогаем: отправка идёт через ``maybe_notify``, то
    есть путь и признак ровно те же, что у мгновенного пуша.
    """
    try:
        from app.core.flags import get_flag
        if not await _enabled():
            return 0
        if not await get_flag(CATCHUP_FLAG, settings.instant_handoff_catchup_enabled):
            return 0
        from app.integrations.crm.db import Conversation
        sm = _sessionmaker(sessionmaker)
        now = now or datetime.now(timezone.utc)
        window = timedelta(hours=max(1, settings.instant_handoff_catchup_window_hours))
        digest = _digest_bots()
        async with sm() as session:
            rows = (await session.execute(select(Conversation).where(
                Conversation.stage.in_(HANDOFF_STAGES),
                Conversation.handoff_notified_at.is_(None),
                Conversation.archived.is_not(True),
                Conversation.assigned_to.is_not(None),
                Conversation.assigned_to != "",
                Conversation.last_message_at >= now - window,
                Conversation.last_message_at <= now - CATCHUP_MIN_AGE,
            ).order_by(Conversation.last_message_at))).scalars().all()
        pending = [c for c in rows
                   if (c.bot_id or "") not in digest
                   and (c.last_sender or "") != "manager"]
        sent = 0
        for conv in pending[:CATCHUP_CAP]:
            # «Бот пообещал» берём только если последним говорил бот: реплику клиента
            # в эту строку класть нельзя, менеджер прочтёт её как обещание фирмы.
            promised = (conv.last_text or "") if (conv.last_sender or "") == "bot" else ""
            if await maybe_notify(conv.user_id, promised=promised, sessionmaker=sm,
                                  waited_since=conv.last_message_at):
                sent += 1
        if sent or len(pending) > CATCHUP_CAP:
            log.info("instant handoff catchup: sent %s of %s pending", sent, len(pending))
        return sent
    except Exception:  # noqa: BLE001 — фоновая догонялка не имеет права ронять тик
        log.warning("instant handoff catchup failed", exc_info=True)
        return 0


def _is_digest_hour(now: datetime) -> bool:
    local_hour = (now + timedelta(hours=BISHKEK_UTC_OFFSET)).hour
    return local_hour in set(settings.instant_handoff_digest_hours or [])


def render_digest_text(cards: list[dict], *, hour_label: str) -> str:
    lines = [f"📋 Готовые заявки · {hour_label}", f"Всего: {len(cards)}"]
    for c in cards[:DIGEST_MANAGER_CAP]:
        who = " · ".join(x for x in (c["name"], c["phone"]) if x) or "клиент"
        lines += ["", f"• {who}", f"  {c['request']}"]
        if c["link"]:
            lines.append(f"  👉 {c['link']}")
    if len(cards) > DIGEST_MANAGER_CAP:
        lines.append(f"\n…и ещё {len(cards) - DIGEST_MANAGER_CAP} — в панели")
    return "\n".join(lines)


async def run_digest(*, now: datetime | None = None, sessionmaker=None,
                     force: bool = False) -> int:
    """Пачка готовых заявок по каналам на дайджесте. Возвращает число отправленных пачек.

    Планировщик тикает раз в 5 минут, поэтому одного попадания в «час дайджеста» мало:
    без датированного флага слот 15:00 разослал бы до 12 пачек. Флаг на слот и на день —
    та же конвенция, что у календарного брифа.
    """
    try:
        from app.core import flags
        if not await _enabled():
            return 0
        bots = _digest_bots()
        if not bots:
            return 0
        now = now or datetime.now(timezone.utc)
        if not force and not _is_digest_hour(now):
            return 0
        local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
        slot_key = f"handoff_digest_sent_{local:%Y%m%d_%H}"
        if not force and await flags.get_flag(slot_key, False):
            return 0
        from app.core.calendar_brief import _client_link, _phone_display
        from app.integrations.crm.db import Conversation
        sm = _sessionmaker(sessionmaker)
        hour_label = (now + timedelta(hours=BISHKEK_UTC_OFFSET)).strftime("%H:%M")
        by_manager: dict[str, list[dict]] = {}
        claimed: list[str] = []
        async with sm() as session:
            rows = (await session.execute(select(Conversation).where(
                Conversation.bot_id.in_(bots),
                Conversation.stage.in_(HANDOFF_STAGES),
                Conversation.handoff_notified_at.is_(None),
                Conversation.archived.is_not(True),
                or_(Conversation.assigned_to != "",
                    Conversation.assigned_to.is_not(None)),
            ).order_by(Conversation.last_message_at))).scalars().all()
            for conv in rows:
                login = (conv.assigned_to or "").strip()
                if not login:
                    continue
                by_manager.setdefault(login, []).append({
                    "name": ((conv.qualification or {}).get("name") or "").strip(),
                    "phone": _phone_display(conv.phone or conv.user_id),
                    "request": _request_line(conv.qualification, conv.funnel or ""),
                    "link": _client_link(conv.user_id, settings.admin_base_url),
                    "user_id": conv.user_id,
                })
            for cards in by_manager.values():
                for card in cards:
                    if await _claim(session, card["user_id"], now):
                        claimed.append(card["user_id"])
        sent = 0
        for login, cards in by_manager.items():
            live = [c for c in cards if c["user_id"] in claimed]
            if not live:
                continue
            if await _send(login, render_digest_text(live, hour_label=hour_label)):
                sent += 1
            else:
                for card in live:
                    await _release(sm, card["user_id"])
        if not force:
            # Слот закрываем всегда, даже если рассылать было нечего: иначе следующий тик
            # через 5 минут снова полез бы считать.
            await flags.set_flag(slot_key, True)
        if sent:
            log.info("instant handoff digest: sent %s packs", sent)
        return sent
    except Exception:  # noqa: BLE001
        log.warning("instant handoff digest failed", exc_info=True)
        return 0
