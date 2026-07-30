"""Разбор владения диалогами (июль 2026): визовый бэклог, наследство Сезим, орфаны.

Dry-run по умолчанию. `--apply` запускать ТОЛЬКО после свежего бэкапа и сверки
напечатанных чисел.

Три режима работы, независимые друг от друга:

* **визовый бэклог** — бесхозные визовые диалоги раздаются по `visa_manager_roster`
  (`medina`/`eliza`) через настоящий `select_next_visa_manager`;
* **наследство Сезим** (`--sezim`) — активные диалоги канала `frunze_tours_sezim`,
  закреплённые за уволившейся Сезим, переходят к новому владельцу. Ловятся ДВА случая:
  владелец стоит в панели (`Conversation.assigned_to`) и владелец стоит только в домене
  (`Assignment.manager_id`) при пустом зеркале панели;
* **орфаны канала** (`--tours-orphans`) — активные диалоги того же канала вообще без
  владельца.

Предохранители, за которые заплачено ревью (не убирать):

1. **Единый код для dry-run и apply.** Различие ровно одно: в конце батча `commit()`
   против `rollback()`. Поэтому превью падает там же, где упал бы apply, и учитывает
   `manager_off:<login>`.
2. **`assigned_at` проставляется явно в Python.** `Assignment.assigned_at` объявлен как
   `server_default=func.now()`, а в PostgreSQL `now()` — время НАЧАЛА транзакции и внутри
   неё константа. Раздача пачкой в одной транзакции давала всем строкам одинаковый
   `assigned_at`, ротация `least-recently-assigned` вырождалась, и ~все диалоги уезжали
   первому логину в роспись. Явная возрастающая метка это лечит.
3. **Батчи с короткими транзакциями.** Иначе одна транзакция держит 500+ блокировок
   строк на живой базе.
4. **Идентичность контакта не угадывается.** Телефон берётся только из `Conversation.phone`,
   telegram-диалоги идут по telegram-идентичности. Ряд без пригодной идентичности
   ПРОПУСКАЕТСЯ со счётчиком, а не догадкой: иначе 9-значный telegram-id молча
   превратился бы в выдуманный номер `996XXXXXXXXX` с реальным владельцем.
5. **Одна битая строка не роняет прогон.** `DomainError` по строке → пропуск со счётчиком.
6. **`--rollback`** отыгрывает прогон по аудит-записям (в них пишется прежний владелец).

Оговорка про батчи: в dry-run каждый батч откатывается, поэтому ротация внутри батча
честная, но между батчами не переносится. На числа это не влияет (внутри батча
чередование ровное), но `--batch-size` в превью и в применении держите одинаковым.

Примеры:

    python scripts/assign_manager_backlog.py                      # превью всего
    python scripts/assign_manager_backlog.py --sezim --apply      # только наследство
    python scripts/assign_manager_backlog.py --tours-orphans --since-days 30
    python scripts/assign_manager_backlog.py --rollback backfill_2026_07 --apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select

# Прямой запуск из корня репозитория.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.core.flags import get_flag  # noqa: E402
from app.domain import live_assign  # noqa: E402
from app.domain.assignment_queue import select_next_visa_manager  # noqa: E402
from app.domain.models import DomainError  # noqa: E402
from app.integrations.crm.db import (  # noqa: E402
    AuditLog, ConvMessage, Conversation, get_sessionmaker)

SEZIM_BOT_ID = "frunze_tours_sezim"
SEZIM_LOGIN = "sezim"

REASON_VISA = "backfill_2026_07"
REASON_SEZIM = "staff_transition_2026_07"
REASON_ORPHANS = "tours_orphans_2026_07"
REASON_DEPARTED = "departed_owner_2026_07"
REASONS = (REASON_VISA, REASON_SEZIM, REASON_ORPHANS, REASON_DEPARTED)


# --------------------------------------------------------------------------- helpers


def _audit_detail(reason: str, prev: str, new: str) -> str:
    """Формат, который умеет отыграть `--rollback`: прежний владелец сохраняется."""
    return f"{reason}: {prev or '-'} -> {new}"


def _parse_detail(detail: str, reason: str) -> tuple[str, str] | None:
    """Обратный разбор `_audit_detail` → (prev, new). None, если строка не наша."""
    prefix = f"{reason}: "
    if not detail.startswith(prefix) or " -> " not in detail:
        return None
    prev, _, new = detail[len(prefix):].partition(" -> ")
    prev, new = prev.strip(), new.strip()
    if not new:
        return None
    return ("" if prev == "-" else prev), new


def _identity(conv: Conversation) -> tuple[str, str] | None:
    """(channel, raw) для `contact_for_channel` — или None, если идентичности нет.

    Телефон НЕ достаётся из `user_id`: там лежит ключ вида `<bot_id>:<номер>`, и для
    telegram-ботов это id, который нормализатор превратил бы в выдуманный номер.
    """
    channel = (conv.channel or "").strip().lower()
    if channel == "telegram":
        raw = (conv.chat_id or "").strip() or (conv.user_id or "").rpartition(":")[2]
        return ("telegram", raw) if raw else None
    phone = (conv.phone or "").strip()
    return ("whatsapp", phone) if phone else None


def _filters_label(run: "_Run") -> str:
    """Человекочитаемые отсечки — печатаются до применения, чтобы было что сверять."""
    parts = ["без отсечки по давности" if run.cutoff is None
             else f"давность ≤{run.since_days} дн (с {run.cutoff.date()})"]
    if run.min_messages > 0:
        parts.append(f"сообщений ≥{run.min_messages}")
    return ", ".join(parts)


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


async def _availability(logins: list[str]) -> dict[str, bool]:
    """Читаем `manager_off:<login>` один раз на прогон, а не на каждую строку."""
    return {login: not await get_flag(f"manager_off:{login}", False) for login in logins}


def _msg_count_sq():
    """Подзапрос «сколько сообщений в диалоге» — для отсечки по содержательности."""
    return (select(ConvMessage.conversation_id.label("cid"),
                   func.count(ConvMessage.id).label("cnt"))
            .group_by(ConvMessage.conversation_id).subquery())


def _active_query(*, cutoff: datetime | None, min_messages: int = 0):
    """Живой диалог + отсечка по свежести (0 дней = без отсечки) и по содержательности.

    Отсечка по сообщениям нужна потому, что на живых данных давность почти ничего не
    отсекает: бот в бою с 01.07.2026, вся база младше месяца, и `--since-days 30`
    оказывается no-op. Разделяет реальные разговоры и «поздоровался и ушёл» именно
    число сообщений.
    """
    q = select(Conversation).where(Conversation.archived.is_not(True))
    if cutoff is not None:
        q = q.where(Conversation.last_message_at >= cutoff)
    if min_messages > 0:
        sq = _msg_count_sq()
        q = q.join(sq, sq.c.cid == Conversation.id).where(sq.c.cnt >= min_messages)
    return q


def _ownerless():
    """Бесхозный = пустая строка ИЛИ NULL. На проде колонка добавлена self-heal-DDL
    без NOT NULL, поэтому NULL там возможен (в тестах ORM создаёт колонку nullable
    тоже — иначе эта ветка не покрывалась бы)."""
    return or_(Conversation.assigned_to == "", Conversation.assigned_to.is_(None))


# --------------------------------------------------------------------------- core


class _Run:
    """Состояние одного прогона: счётчики, конфликты, режим."""

    def __init__(self, *, apply: bool, owner: str, since_days: int,
                 batch_size: int, now: datetime, min_messages: int = 0) -> None:
        self.apply = apply
        self.owner = owner
        self.since_days = since_days
        self.min_messages = min_messages
        self.batch_size = batch_size
        self.now = now
        self.cutoff = None if since_days <= 0 else now - timedelta(days=since_days)
        self.visa: dict[str, int] = defaultdict(int)
        self.by_bot: dict[str, int] = defaultdict(int)
        self.skipped: dict[str, int] = defaultdict(int)
        self.conflicts: list[str] = []
        self.sezim_moved = 0
        self.orphans_moved = 0
        self.departed_moved = 0
        self.repaired = 0
        self.rolled_back = 0
        self._seq = 0

    def stamp(self) -> datetime:
        """Строго возрастающая метка — лечит вырождение ротации (см. модульный docstring)."""
        self._seq += 1
        return self.now + timedelta(milliseconds=self._seq)

    def conflict(self, conv: Conversation, owner: str, direction: str) -> None:
        msg = (f"конфликт владельца: id={conv.id} user_id={conv.user_id} "
               f"direction={direction} уже за {owner!r}")
        if self.apply:
            # В применении останавливаемся на первом — батч не коммитится.
            raise RuntimeError(msg)
        # В превью собираем ВСЕ, чтобы оператор увидел проблемы разом, а не по одной.
        self.conflicts.append(msg)

    def summary(self, mode: str) -> dict[str, object]:
        return {
            "mode": mode,
            "owner": self.owner,
            "since_days": self.since_days,
            "min_messages": self.min_messages,
            "cutoff": self.cutoff.isoformat() if self.cutoff else None,
            "visa": dict(self.visa),
            "visa_by_bot": dict(self.by_bot),
            "sezim_moved": self.sezim_moved,
            "tours_orphans_moved": self.orphans_moved,
            "departed_moved": self.departed_moved,
            "mirrors_repaired": self.repaired,
            "skipped": dict(self.skipped),
            "conflicts": self.conflicts,
            "rolled_back": self.rolled_back,
        }


async def _set_owner(session, run: _Run, conv: Conversation, *, direction: str,
                     login: str, reason: str, allow_emergency: bool) -> bool:
    """Назначить владельца в домене И в зеркале панели + аудит. False = строка пропущена."""
    ident = _identity(conv)
    if ident is None:
        run.skipped["нет идентичности"] += 1
        return False
    channel, raw = ident
    prev = (conv.assigned_to or "")
    try:
        contact = await live_assign.contact_for_channel(session, channel=channel, raw=raw)
        assignment = await live_assign.assign_locked(
            session, contact.id, direction, login,
            assigned_by="system", reason=reason, allow_emergency=allow_emergency)
    except DomainError as exc:
        # Битый номер/идентичность не должны ронять весь прогон.
        run.skipped[f"DomainError: {exc}"[:60]] += 1
        return False
    assignment.assigned_at = run.stamp()
    conv.assigned_to = login
    conv.assigned_at = assignment.assigned_at
    session.add(AuditLog(manager="system", action="assign" if not prev else "reassign",
                         user_id=conv.user_id, detail=_audit_detail(reason, prev, login)))
    return True


async def _repair_mirror(session, run: _Run, conv: Conversation, assignment) -> None:
    """Владелец есть в домене, а зеркало панели пустое — восстановить без смены владельца."""
    conv.assigned_to = assignment.manager_id
    conv.assigned_at = assignment.assigned_at
    run.repaired += 1
    session.add(AuditLog(
        manager="system", action="assign", user_id=conv.user_id,
        detail=f"repair_assignment_mirror: - -> {assignment.manager_id}"))


async def _finish_batch(session, apply: bool) -> None:
    if apply:
        await session.commit()
    else:
        await session.rollback()


# --------------------------------------------------------------------------- passes


async def _pass_visa(sm, run: _Run) -> None:
    """Бесхозные визовые диалоги → по роспись через настоящий селектор."""
    roster = list(settings.visa_manager_roster)
    avail = await _availability(roster)
    if not any(avail.values()):
        raise RuntimeError("no available visa manager (все помечены manager_off)")

    async def _is_available(login: str) -> bool:
        return avail.get(login, False)

    async with sm() as session:
        total = len((await session.execute(
            select(Conversation.id).where(
                Conversation.funnel == "visa", Conversation.archived.is_not(True),
                _ownerless()))).scalars().all())
        rows = (await session.execute(
            _active_query(cutoff=run.cutoff, min_messages=run.min_messages)
            .where(Conversation.funnel == "visa", _ownerless())
            .order_by(Conversation.last_message_at.desc(), Conversation.id)
        )).scalars().all()
        ids = [c.id for c in rows]
    print(f"визы: под отсечку попало {len(ids)} / всего бесхозных {total} "
          f"[{_filters_label(run)}]")

    for chunk in _chunks(ids, run.batch_size):
        async with sm() as session:
            q = select(Conversation).where(Conversation.id.in_(chunk)).order_by(
                Conversation.last_message_at.desc(), Conversation.id)
            if run.apply:
                q = q.with_for_update()
            for conv in (await session.execute(q)).scalars().all():
                ident = _identity(conv)
                if ident is None:
                    run.skipped["нет идентичности"] += 1
                    continue
                channel, raw = ident
                try:
                    contact = await live_assign.contact_for_channel(
                        session, channel=channel, raw=raw)
                except DomainError as exc:
                    run.skipped[f"DomainError: {exc}"[:60]] += 1
                    continue
                active = await live_assign.active_assignment(session, contact.id, "visa")
                if active is not None:
                    # Владелец уже есть в домене — только восстановить зеркало панели.
                    await _repair_mirror(session, run, conv, active)
                    run.visa[active.manager_id] += 1
                    run.by_bot[conv.bot_id or "-"] += 1
                    continue
                login = await select_next_visa_manager(
                    session, roster=roster, is_available=_is_available)
                if not login:
                    raise RuntimeError("no available visa manager")
                if await _set_owner(session, run, conv, direction="visa", login=login,
                                    reason=REASON_VISA, allow_emergency=False):
                    run.visa[login] += 1
                    run.by_bot[conv.bot_id or "-"] += 1
            await _finish_batch(session, run.apply)


async def _pass_sezim_channel(sm, run: _Run, *, orphans: bool) -> None:
    """Канал Сезим: наследство (панель ИЛИ домен) и, по флагу, орфаны канала."""
    async with sm() as session:
        rows = (await session.execute(
            _active_query(cutoff=run.cutoff, min_messages=run.min_messages)
            .where(Conversation.bot_id == SEZIM_BOT_ID)
            .order_by(Conversation.id))).scalars().all()
        ids = [c.id for c in rows]
        orphan_total = len((await session.execute(
            select(Conversation.id).where(
                Conversation.bot_id == SEZIM_BOT_ID,
                Conversation.archived.is_not(True), _ownerless()))).scalars().all())
    print(f"канал {SEZIM_BOT_ID}: под отсечку попало {len(ids)}, "
          f"бесхозных всего {orphan_total} → владелец {run.owner!r} "
          f"[{_filters_label(run)}]"
          f"{'' if orphans else ' (орфаны НЕ трогаем, нужен --tours-orphans)'}")

    for chunk in _chunks(ids, run.batch_size):
        async with sm() as session:
            q = select(Conversation).where(Conversation.id.in_(chunk)).order_by(
                Conversation.id)
            if run.apply:
                q = q.with_for_update()
            for conv in (await session.execute(q)).scalars().all():
                panel_owner = (conv.assigned_to or "").strip()
                if panel_owner not in ("", SEZIM_LOGIN, run.owner):
                    continue                      # чужой живой владелец — не наше дело
                ident = _identity(conv)
                if ident is None:
                    if panel_owner == SEZIM_LOGIN or (orphans and not panel_owner):
                        run.skipped["нет идентичности"] += 1
                    continue
                channel, raw = ident
                try:
                    contact = await live_assign.contact_for_channel(
                        session, channel=channel, raw=raw)
                except DomainError as exc:
                    run.skipped[f"DomainError: {exc}"[:60]] += 1
                    continue
                active = await live_assign.active_assignment(session, contact.id, "tours")
                domain_owner = active.manager_id if active is not None else ""

                # Наследство: владелец Сезим в панели ИЛИ только в домене (дыра зеркала).
                is_legacy = panel_owner == SEZIM_LOGIN or domain_owner == SEZIM_LOGIN
                if is_legacy:
                    if domain_owner not in ("", SEZIM_LOGIN, run.owner):
                        run.conflict(conv, domain_owner, "tours")
                        continue
                    if await _set_owner(session, run, conv, direction="tours",
                                        login=run.owner, reason=REASON_SEZIM,
                                        allow_emergency=True):
                        run.sezim_moved += 1
                    continue

                if not panel_owner and domain_owner == run.owner:
                    await _repair_mirror(session, run, conv, active)
                    continue

                if orphans and not panel_owner and not domain_owner:
                    if await _set_owner(session, run, conv, direction="tours",
                                        login=run.owner, reason=REASON_ORPHANS,
                                        allow_emergency=False):
                        run.orphans_moved += 1
            await _finish_batch(session, run.apply)


def _known_logins() -> set[str]:
    """Логины, которые ещё существуют в MANAGERS. Всё остальное — призраки."""
    return {(m.login or "").strip().lower()
            for m in settings.manager_list() if (m.login or "").strip()}


async def _pass_departed(sm, run: _Run, *, extra: frozenset[str] = frozenset()) -> None:
    """Диалоги, висящие на логине, которого больше нет в MANAGERS (человек уволился).

    Такой диалог не видит НИКТО: панель фильтрует по скоупу живых логинов, а мгновенный
    пуш «заявка готова» адресуется владельцу, которого не существует. Отличие от `--sezim`:
    тот режим прибит к одному каналу, а наследство расползлось по обоим туровым номерам.

    Новый владелец — менеджер КАНАЛА (решение владельцев 30.07: «по турам менеджер
    получает канал целиком»), поэтому берём его из той же карты, что и авто-закрепление:
    два источника правды о владельце канала разъехались бы на первой же перестановке.
    """
    from app.domain.autoassign import tours_owner_for
    known = _known_logins() - extra

    def _movable(conv) -> bool:
        return (conv.assigned_to or "").strip().lower() not in known

    async with sm() as session:
        rows = (await session.execute(
            _active_query(cutoff=run.cutoff, min_messages=run.min_messages)
            .where(Conversation.assigned_to.is_not(None), Conversation.assigned_to != "")
            .order_by(Conversation.id))).scalars().all()
    plan = {c.id: tours_owner_for(c.bot_id or "") for c in rows
            if _movable(c) and tours_owner_for(c.bot_id or "")
            and tours_owner_for(c.bot_id or "") != (c.assigned_to or "").strip().lower()}
    ghosts = sorted({(c.assigned_to or "").strip() for c in rows if _movable(c)})
    print(f"владельцы-призраки: {ghosts or '—'} → под перенос {len(plan)} "
          f"[{_filters_label(run)}]")

    for chunk in _chunks(list(plan), run.batch_size):
        async with sm() as session:
            q = select(Conversation).where(Conversation.id.in_(chunk)).order_by(
                Conversation.id)
            if run.apply:
                q = q.with_for_update()
            for conv in (await session.execute(q)).scalars().all():
                new_owner = plan[conv.id]
                ident = _identity(conv)
                if ident is None:
                    run.skipped["нет идентичности"] += 1
                    continue
                channel, raw = ident
                try:
                    contact = await live_assign.contact_for_channel(
                        session, channel=channel, raw=raw)
                except DomainError as exc:
                    run.skipped[f"DomainError: {exc}"[:60]] += 1
                    continue
                active = await live_assign.active_assignment(session, contact.id, "tours")
                domain_owner = (active.manager_id if active is not None else "").lower()
                # В домене сидит ЖИВОЙ и это не тот, кому мы отдаём → руками, не скриптом.
                if domain_owner and domain_owner in known and domain_owner != new_owner:
                    run.conflict(conv, domain_owner, "tours")
                    continue
                if await _set_owner(session, run, conv, direction="tours",
                                    login=new_owner, reason=REASON_DEPARTED,
                                    allow_emergency=True):
                    run.departed_moved += 1
            await _finish_batch(session, run.apply)


async def _pass_rollback(sm, run: _Run, reason: str) -> None:
    """Отыграть прогон по аудит-записям: вернуть прежнего владельца (или снять)."""
    async with sm() as session:
        audits = (await session.execute(
            select(AuditLog).where(AuditLog.manager == "system",
                                   AuditLog.detail.startswith(f"{reason}: "))
            .order_by(AuditLog.id.desc()))).scalars().all()
        items = [(a.user_id, a.detail) for a in audits]
    print(f"откат {reason}: аудит-записей {len(items)}")

    for chunk in _chunks(items, run.batch_size):
        async with sm() as session:
            for user_id, detail in chunk:
                parsed = _parse_detail(detail, reason)
                if parsed is None:
                    continue
                prev, new = parsed
                q = select(Conversation).where(Conversation.user_id == user_id)
                if run.apply:
                    q = q.with_for_update()
                conv = (await session.execute(q)).scalar_one_or_none()
                if conv is None or (conv.assigned_to or "") != new:
                    continue      # уже откатили либо владельца сменил человек — не трогаем
                ident = _identity(conv)
                if ident is None:
                    run.skipped["нет идентичности"] += 1
                    continue
                channel, raw = ident
                direction = "visa" if (conv.funnel or "") == "visa" else "tours"
                try:
                    contact = await live_assign.contact_for_channel(
                        session, channel=channel, raw=raw)
                    await live_assign.end_active(session, contact.id, direction)
                    if prev:
                        a = await live_assign.assign_locked(
                            session, contact.id, direction, prev,
                            assigned_by="system", reason=f"rollback_{reason}",
                            allow_emergency=True)
                        a.assigned_at = run.stamp()
                except DomainError as exc:
                    run.skipped[f"DomainError: {exc}"[:60]] += 1
                    continue
                conv.assigned_to = prev
                conv.assigned_at = run.stamp() if prev else None
                session.add(AuditLog(
                    manager="system", action="reassign", user_id=conv.user_id,
                    detail=f"rollback {reason}: {new} -> {prev or '-'}"))
                run.rolled_back += 1
            await _finish_batch(session, run.apply)


# --------------------------------------------------------------------------- entry


async def run(*, apply: bool = False, since_days: int = 30, min_messages: int = 0,
              visa: bool = True, sezim: bool = True, tours_orphans: bool = False,
              departed: bool = False, from_logins: tuple[str, ...] = (),
              rollback: str | None = None, owner: str | None = None,
              batch_size: int = 50, sessionmaker=None,
              now: datetime | None = None) -> dict[str, object]:
    sm = sessionmaker or get_sessionmaker()
    state = _Run(apply=apply, owner=(owner or settings.tours_pilot_manager),
                 since_days=since_days, min_messages=max(0, min_messages),
                 batch_size=max(1, batch_size),
                 now=now or datetime.now(timezone.utc))
    if rollback:
        if rollback not in REASONS:
            raise ValueError(f"неизвестный reason для отката: {rollback!r} (из {REASONS})")
        await _pass_rollback(sm, state, rollback)
        return state.summary(("apply" if apply else "dry-run") + "-rollback")
    if visa:
        await _pass_visa(sm, state)
    if departed or from_logins:
        await _pass_departed(sm, state, extra=frozenset(
            l.strip().lower() for l in (from_logins or ()) if l.strip()))
    if sezim or tours_orphans:
        await _pass_sezim_channel(sm, state, orphans=tours_orphans)
    return state.summary("apply" if apply else "dry-run")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true",
                   help="применить изменения (по умолчанию только превью)")
    p.add_argument("--since-days", type=int, default=30,
                   help="брать диалоги с активностью за N дней; 0 = без отсечки")
    p.add_argument("--min-messages", type=int, default=0,
                   help="брать только диалоги с N+ сообщениями (отсекает «поздоровался "
                        "и ушёл»); на живых данных отсекает сильнее, чем давность")
    p.add_argument("--visa", dest="visa", action="store_true", default=None,
                   help="только визовый бэклог")
    p.add_argument("--sezim", dest="sezim", action="store_true", default=None,
                   help="только наследство Сезим")
    p.add_argument("--tours-orphans", action="store_true",
                   help="дополнительно раздать бесхозные диалоги канала Сезим")
    p.add_argument("--departed", action="store_true",
                   help="перенести диалоги с логинов, которых больше нет в MANAGERS, "
                        "менеджеру канала (карта tours_owner_by_bot)")
    p.add_argument("--from-login", action="append", default=[], metavar="LOGIN",
                   help="дополнительно забрать диалоги этого живого логина (напр. "
                        "служебного admin) менеджеру канала; можно повторять")
    p.add_argument("--owner", default=None,
                   help="кому отдавать туровые диалоги (по умолчанию tours_pilot_manager)")
    p.add_argument("--rollback", choices=REASONS, default=None,
                   help="отыграть прогон по аудит-записям")
    p.add_argument("--batch-size", type=int, default=50,
                   help="строк на транзакцию (одинаково в превью и применении)")
    args = p.parse_args()

    # Явно выбранные пассы отключают остальные; по умолчанию идут оба.
    explicit = args.visa or args.sezim or args.departed or args.from_login
    summary = asyncio.run(run(
        apply=args.apply, since_days=args.since_days, min_messages=args.min_messages,
        visa=bool(args.visa) if explicit else True,
        sezim=bool(args.sezim) if explicit else True,
        departed=bool(args.departed), from_logins=tuple(args.from_login),
        tours_orphans=args.tours_orphans, rollback=args.rollback,
        owner=args.owner, batch_size=args.batch_size))

    print()
    for key, value in summary.items():
        print(f"  {key}: {value}")
    if summary["conflicts"]:
        print(f"\n  ⚠ КОНФЛИКТЫ ({len(summary['conflicts'])}) — apply остановится на первом")
    if not args.apply:
        print("\nИзменений не внесено. Запускать с --apply только после бэкапа и сверки чисел.")


if __name__ == "__main__":
    main()
