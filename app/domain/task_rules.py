"""E2-04 — надёжные задачи: сроки, пересчёт, перенос владельцу (STANDARD).

Две вещи, которые здесь важнее остального.

1. **Задача не теряется и не срабатывает дважды** (AC-28). Исполнитель сначала
   ЗАБИРАЕТ задачу — ставит отметку захвата, — и только потом действует. Если
   процесс упал между захватом и результатом, отметка остаётся: при следующем
   запуске такая задача видна как «взята и неизвестно чем кончилась», и её
   сверяют вручную, а не отправляют слепо второй раз. Слепой повтор означает
   второе сообщение клиенту, а это хуже, чем задержка.

2. **Переназначение услуги переносит её открытые задачи** (AC-29). Именно ЭТОЙ
   услуги: в проекте уже был перенос по паре «контакт + направление», но он
   слишком широкий — у клиента может быть два тура, и смена менеджера на одном
   не должна трогать задачи другого. Выполненные задачи остаются за тем, кто их
   сделал: иначе из истории исчезает, кто работал.

Все функции принимают `now`. Это «управляемые часы» из ТЗ: поведение на сроках
проверяется подстановкой момента, а не ожиданием трёх дней.

Чего здесь нет: правил, КОГДА и ЧТО отправлять клиенту. Моменты, шаблоны и лимиты
клиентских сообщений бизнес не согласовал (DEC-12), и выдумывать их нельзя.
Модуль считает сроки и ведёт задачи людям.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.calendar_tasks import _log_event
from app.domain.models import (
    ACTIVE_TASK_STATUSES, CalendarTask, DomainError, Product, ServiceCase,
)
from app.domain.service_authz import Actor, can_view_case, require

BISHKEK = ZoneInfo("Asia/Bishkek")
# Через сколько считать захват «подвисшим». Не таймаут отмены: такую задачу
# НЕ забирают автоматически, её показывают человеку.
STALE_CLAIM_MINUTES = 15


@dataclass(frozen=True)
class ClaimResult:
    """Чем закончилась попытка забрать задачу."""

    task_id: int
    claimed: bool
    reason: str = ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _moment(value, field: str = "now") -> datetime:
    if value is None:
        return _now()
    if not isinstance(value, datetime):
        raise DomainError(f"{field} must be a datetime")
    if value.tzinfo is None:
        raise DomainError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


async def due_tasks(session: AsyncSession, *, now=None, manager_id: str | None = None,
                    limit: int = 100) -> list[CalendarTask]:
    """Задачи, у которых наступил срок и которые ещё никто не взял.

    Подвисшие захваты сюда НЕ попадают: их показывают отдельно
    (`stale_claims`), потому что неизвестно, выполнено ли действие.
    """
    moment = _moment(now)
    query = select(CalendarTask).where(
        CalendarTask.status.in_(ACTIVE_TASK_STATUSES),
        CalendarTask.claimed_at.is_(None),
        CalendarTask.scheduled_at.is_not(None))
    if manager_id is not None:
        query = query.where(CalendarTask.manager_id == str(manager_id).strip().lower())
    rows = await session.scalars(
        query.order_by(CalendarTask.scheduled_at, CalendarTask.id))
    # Срок сравниваем в Python, а не в SQL: SQLite хранит время без зоны, и
    # сравнение с tz-aware значением там даёт неверный результат. Приводим оба
    # момента к UTC — тогда поведение одинаково на SQLite и на PostgreSQL.
    due: list[CalendarTask] = []
    for task in rows:
        at = _as_utc(task.scheduled_at)
        if at is not None and at <= moment:
            due.append(task)
        if len(due) >= max(1, int(limit)):
            break
    return due


async def stale_claims(session: AsyncSession, *, now=None,
                       older_than_minutes: int = STALE_CLAIM_MINUTES
                       ) -> list[CalendarTask]:
    """Задачи, взятые в обработку и не завершённые — требуют сверки человеком.

    Это и есть ответ на «рестарт в момент отправки» (AC-28): мы не знаем, успело
    ли действие произойти. Автоматически повторять нельзя — повтор значит второе
    сообщение клиенту. Поэтому такие задачи видны и разбираются вручную.
    """
    moment = _moment(now)
    threshold = moment - timedelta(minutes=max(0, int(older_than_minutes)))
    rows = await session.scalars(select(CalendarTask).where(
        CalendarTask.status.in_(ACTIVE_TASK_STATUSES),
        CalendarTask.claimed_at.is_not(None)))
    stale: list[CalendarTask] = []
    for task in rows:
        claimed = _as_utc(task.claimed_at)
        if claimed is None:
            continue
        if claimed > moment:
            # Захват помечен будущим временем — разъехались часы процессов. Такая
            # задача иначе не попадала бы в подвисшие НИКОГДА и висела вечно.
            stale.append(task)
        elif claimed <= threshold:
            stale.append(task)
    return stale


async def claim_task(session: AsyncSession, task_id: int, *, worker: str,
                     now=None) -> ClaimResult:
    """Забрать задачу в обработку. Второй захват той же задачи не проходит.

    Захват делается ОДНИМ атомарным UPDATE с условием «ещё не занята», и успех
    определяется числом изменённых строк. Прежняя версия читала, проверяла в
    Python и писала — то есть два исполнителя оба видели «свободна», оба писали,
    и сообщение уходило клиенту дважды. Ровно от этого захват и должен защищать.

    Отдельно важно `populate_existing`: без него `session.get` отдаёт объект из
    кэша сессии, и захват, сделанный другим процессом, остаётся незамеченным.
    """
    name = str(worker or "").strip()
    if not name:
        raise DomainError("worker is required to claim a task")
    moment = _moment(now)
    result = await session.execute(
        update(CalendarTask)
        .where(CalendarTask.id == task_id,
               CalendarTask.claimed_at.is_(None),
               CalendarTask.status.in_(ACTIVE_TASK_STATUSES))
        .values(claimed_at=moment, claimed_by=name[:64]))
    if result.rowcount != 1:
        # Не захватили. Разбираемся, почему именно, — читаем ИЗ БАЗЫ, минуя кэш.
        task = await session.get(CalendarTask, task_id, populate_existing=True)
        if task is None:
            raise DomainError(f"unknown task {task_id}")
        if task.status not in ACTIVE_TASK_STATUSES:
            return ClaimResult(task_id, False, f"task is {task.status}")
        return ClaimResult(task_id, False,
                           f"already claimed by {task.claimed_by or 'unknown'}")
    task = await session.get(CalendarTask, task_id, populate_existing=True)
    await _log_event(session, task, "claimed", actor=name,
                     to_status=task.status, detail="взята в обработку")
    return ClaimResult(task_id, True)


async def finish_task(session: AsyncSession, task_id: int, *, worker: str,
                      outcome: str, now=None) -> CalendarTask:
    """Завершить взятую задачу: действие выполнено, захват снимается.

    Завершить может только тот, кто захватил, и толькоактивную задачу. Иначе чужой
    исполнитель закрывал чужую работу, а отменённая задача тихо превращалась в
    «выполненную» — в журнале это выглядело как «клиенту отправили».
    """
    moment = _moment(now)
    name = str(worker or "").strip()
    task = await session.get(CalendarTask, task_id, populate_existing=True)
    if task is None:
        raise DomainError(f"unknown task {task_id}")
    if task.claimed_at is None:
        raise DomainError("task was not claimed; claim it before finishing")
    if str(task.claimed_by or "").strip() != name:
        raise DomainError("only the worker that claimed the task can finish it")
    if task.status not in ACTIVE_TASK_STATUSES:
        # Задачу успели отменить. Тихо переводить её в «выполнено» нельзя: это
        # запись о том, что действие совершено по актуальной задаче.
        raise DomainError(f"task is {task.status}; it cannot be completed")
    previous = task.status
    task.status = "completed"
    task.completed_at = moment
    task.claimed_at = None
    task.claimed_by = None
    await session.flush()
    await _log_event(session, task, "completed", actor=name[:64],
                     from_status=previous, to_status="completed",
                     detail=str(outcome or "")[:500])
    return task


async def release_claim(session: AsyncSession, task_id: int, *, worker: str,
                        reason: str, force: bool = False) -> CalendarTask:
    """Отпустить задачу обратно, если действие НЕ состоялось.

    Снять захват может тот, кто его поставил. `force=True` — для разбора
    подвисших захватов человеком: процесс мог упасть и больше не вернуться.
    Автоматического освобождения по таймауту нет намеренно: оно привело бы к
    повтору действия, о котором неизвестно, случилось оно или нет.
    """
    if not str(reason or "").strip():
        raise DomainError("releasing a claim requires a reason")
    name = str(worker or "").strip()
    task = await session.get(CalendarTask, task_id, populate_existing=True)
    if task is None:
        raise DomainError(f"unknown task {task_id}")
    if task.claimed_at is None:
        raise DomainError("task is not claimed")
    previous_worker = task.claimed_by
    if not force and str(previous_worker or "").strip() != name:
        raise DomainError("only the worker that claimed the task can release it")
    task.claimed_at = None
    task.claimed_by = None
    await session.flush()
    await _log_event(session, task, "claim_released", actor=name[:64],
                     to_status=task.status,
                     detail=f"захват снят ({previous_worker}): {str(reason)[:300]}")
    return task


async def transfer_open_tasks(session: AsyncSession, case_id: int, *,
                              new_owner: str, actor: str, now=None) -> tuple[int, ...]:
    """Перенести ОТКРЫТЫЕ задачи услуги новому владельцу (AC-29).

    Только задачи этой услуги: перенос по паре «контакт + направление» задел бы
    второй тур того же клиента. Выполненные и отменённые не трогаются — иначе из
    истории исчезает, кто именно сделал работу.
    """
    owner = str(new_owner or "").strip().lower()
    if not owner:
        raise DomainError("new_owner is required")
    _moment(now)
    moved: list[int] = []
    rows = await session.scalars(select(CalendarTask).where(
        CalendarTask.service_case_id == case_id,
        CalendarTask.status.in_(ACTIVE_TASK_STATUSES),
        CalendarTask.manager_id != owner))
    for task in rows:
        previous = task.manager_id
        task.manager_id = owner
        await session.flush()
        await _log_event(session, task, "reassigned", actor=str(actor or "")[:64],
                         detail=f"{previous}->{owner} (услуга {case_id})")
        moved.append(task.id)
    await session.flush()
    return tuple(moved)


async def orphan_tasks(session: AsyncSession, *, contact_id: int,
                       direction: str) -> tuple[int, ...]:
    """Открытые задачи контакта БЕЗ ссылки на услугу.

    Такие задачи создавал прежний код (ссылка появилась только в E2-02), и в
    боевой базе они уже есть. Привязать их к услуге автоматически нельзя: у
    клиента бывает несколько услуг одного направления, и угадывание посадило бы
    задачу не туда. Поэтому мы их не трогаем, а делаем ВИДИМЫМИ — чтобы при
    переназначении человек знал, что осталось разобрать руками.
    """
    rows = await session.scalars(select(CalendarTask).where(
        CalendarTask.contact_id == contact_id,
        CalendarTask.direction == direction,
        CalendarTask.service_case_id.is_(None),
        CalendarTask.status.in_(ACTIVE_TASK_STATUSES)))
    return tuple(task.id for task in rows)


async def shift_future_tasks(session: AsyncSession, case_id: int, *, days: int,
                             actor: str, now=None) -> tuple[int, ...]:
    """Сдвинуть будущие задачи услуги на N дней — при переносе поездки.

    Прошедшие и выполненные задачи не двигаются: сдвигать то, что уже произошло,
    бессмысленно, а выполненную работу переписывать нельзя.
    """
    if not isinstance(days, int) or isinstance(days, bool) or days == 0:
        raise DomainError("days must be a non-zero whole number")
    if abs(days) > 3650:
        # Без границы 10**9 даёт OverflowError посреди цикла — часть задач уже
        # сдвинута, часть нет. Десять лет — заведомо больше любой поездки.
        raise DomainError("days must be within 3650 days")
    moment = _moment(now)
    shifted: list[int] = []
    rows = await session.scalars(select(CalendarTask).where(
        CalendarTask.service_case_id == case_id,
        CalendarTask.status.in_(ACTIVE_TASK_STATUSES)))
    for task in rows:
        if task.claimed_at is not None:
            # Задача прямо сейчас исполняется: сдвигать ей срок — значит менять
            # условия под работающим процессом.
            continue
        due = _as_utc(task.scheduled_at)
        if due is None or due <= moment:
            continue
        new_due = due + timedelta(days=days)
        if new_due <= moment:
            # Сдвиг уводит задачу в прошлое — она стала бы сразу просроченной.
            continue
        task.scheduled_at = new_due
        task.scheduled_date = new_due.astimezone(BISHKEK).date()
        await session.flush()
        await _log_event(session, task, "rescheduled", actor=str(actor or "")[:64],
                         from_at=due, to_at=new_due,
                         detail=f"поездка перенесена на {days:+d} дн.")
        shifted.append(task.id)
    await session.flush()
    return tuple(shifted)


async def case_tasks(session: AsyncSession, case_id: int, *, by: Actor,
                     include_finished: bool = True) -> list[CalendarTask]:
    """Задачи услуги — для карточки. Права проверяются как на саму услугу."""
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "view tasks")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_view_case(by, direction=product.direction if product else None,
                          owner_login=case.owner_login), "view tasks")
    query = select(CalendarTask).where(CalendarTask.service_case_id == case_id)
    if not include_finished:
        query = query.where(CalendarTask.status.in_(ACTIVE_TASK_STATUSES))
    return list(await session.scalars(
        query.order_by(CalendarTask.scheduled_at, CalendarTask.id)))


def overdue_on(task: CalendarTask, *, today: date | None = None) -> bool:
    """Просрочена ли задача на указанный день по календарю Бишкека."""
    if task.status not in ACTIVE_TASK_STATUSES:
        return False
    day = today or _now().astimezone(BISHKEK).date()
    return task.scheduled_date < day
