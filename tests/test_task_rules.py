"""E2-04 — приёмка надёжных задач: AC-28 и AC-29.

Доказательство из ТЗ: управляемые часы и рестарт; будущие задачи пересчитаны,
выполненные сохранены, открытые задачи у нового владельца.

«Управляемые часы» — все проверки подставляют момент параметром `now`, а не ждут
реального времени.
"""
from __future__ import annotations

import asyncio

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.domain.calendar_tasks import CalendarTaskService
from app.domain.models import (
    CalendarTask, CalendarTaskEvent, Contact, DomainError, ServiceEvent,
)
from app.domain.service_authz import Actor, PermissionDenied
from app.domain.service_cases import reassign_case, seed_products, sign_contract
from app.domain.task_rules import (
    STALE_CLAIM_MINUTES, case_tasks, claim_task, due_tasks, finish_task,
    overdue_on, release_claim, shift_future_tasks, stale_claims,
    transfer_open_tasks,
)
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="manager", allowed_directions=("tours",))
HEIR = Actor(manager_id="heir", allowed_directions=("tours",))
PEER = Actor(manager_id="other", allowed_directions=("tours",))
VISA = Actor(manager_id="visa_manager", allowed_directions=("visa",))
ADMIN = Actor(manager_id="admin", allowed_directions=("tours", "visa"),
              is_full_admin=True)
BISHKEK = ZoneInfo("Asia/Bishkek")

NOW = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)



class _Manager:
    """Запись менеджера для подмены настроек: `reassign_case` сверяет цель со списком."""

    def __init__(self, login: str) -> None:
        self.login = login


def known_managers(monkeypatch, *logins: str) -> None:
    """Объявить менеджеров известными.

    `reassign_case` отказывает, если цель не настроена — защита из E1-03 от
    передачи услуги в пустоту. В тестах список подменяем явно.
    """
    from app.config import settings
    # Патчим КЛАСС, а не экземпляр: Settings — модель pydantic, и подмена метода
    # на экземпляре запрещена («object has no field»).
    monkeypatch.setattr(type(settings), "manager_list",
                        lambda self: [_Manager(login) for login in logins],
                        raising=False)


async def tour_case(session, *, key="tr-1", reference="TR-1"):
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    tour = next(p for p in products if p.code == "tour_package")
    case = await sign_contract(
        session, contact_id=contact.id, product_id=tour.id,
        owner_login=OWNER.manager_id, by=OWNER, reference=reference,
        amount=Decimal("100000.00"), currency="KGS", idempotency_key=key)
    await session.flush()
    # Подписание договора заводит начальную задачу (E1-03, AC-01). Здесь она мешает
    # считать задачи самого E2-04, поэтому убираем её — проверки начальной задачи
    # живут в tests/test_contract_signing.py.
    for initial in await session.scalars(
            select(CalendarTask).where(CalendarTask.service_case_id == case.id)):
        await session.delete(initial)
    await session.flush()
    return case


async def add_task(session, case, *, at: datetime, kind="call", status="planned",
                   manager=None):
    task = CalendarTask(
        contact_id=case.contact_id, manager_id=manager or case.owner_login,
        direction="tours", kind=kind, comment="задача",
        scheduled_date=at.astimezone(BISHKEK).date(), scheduled_at=at,
        created_by="test", service_case_id=case.id, status=status)
    session.add(task)
    await session.flush()
    return task


async def journal(session, task_id):
    return [e.event for e in await session.scalars(
        select(CalendarTaskEvent).where(CalendarTaskEvent.task_id == task_id)
        .order_by(CalendarTaskEvent.id))]


def test_ac28_a_claimed_task_is_not_taken_twice():
    """AC-28: взятую задачу второй исполнитель не забирает."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            first = await claim_task(session, task.id, worker="worker-1", now=NOW)
            second = await claim_task(session, task.id, worker="worker-2", now=NOW)
            await session.commit()
            assert first.claimed is True
            assert second.claimed is False and "worker-1" in second.reason
            await session.refresh(task)
            assert task.claimed_by == "worker-1"
            assert "claimed" in await journal(session, task.id)
    run_with_db(scenario)


def test_ac28_a_claimed_task_disappears_from_the_due_list():
    """Взятая задача больше не выдаётся: иначе её возьмёт второй процесс."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            assert [t.id for t in await due_tasks(session, now=NOW)] == [task.id]
            await claim_task(session, task.id, worker="w", now=NOW)
            await session.commit()
            assert await due_tasks(session, now=NOW) == []
    run_with_db(scenario)


def test_ac28_an_interrupted_claim_is_visible_and_not_retried_automatically():
    """AC-28: после рестарта незавершённый захват ВИДЕН и не повторяется сам.

    Мы не знаем, успело ли действие произойти. Слепой повтор означает второе
    сообщение клиенту — поэтому такие задачи показываются человеку, а не
    забираются автоматически.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(hours=1))
            await claim_task(session, task.id, worker="worker-1", now=NOW)
            await session.commit()
            # «Рестарт»: прошло больше порога, результата нет.
            later = NOW + timedelta(minutes=STALE_CLAIM_MINUTES + 1)
            # Автоматически задача НЕ возвращается в очередь.
            assert await due_tasks(session, now=later) == []
            # Но она видна как требующая сверки.
            assert [t.id for t in await stale_claims(session, now=later)] == [task.id]
            # И повторный захват по-прежнему не проходит.
            retry = await claim_task(session, task.id, worker="worker-2", now=later)
            assert retry.claimed is False
    run_with_db(scenario)


def test_a_fresh_claim_is_not_reported_as_stale():
    """Только что взятая задача не считается подвисшей."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(hours=1))
            await claim_task(session, task.id, worker="w", now=NOW)
            await session.commit()
            assert await stale_claims(session, now=NOW + timedelta(minutes=1)) == []
    run_with_db(scenario)


def test_finishing_a_task_clears_the_claim_and_records_the_outcome():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="w", now=NOW)
            await finish_task(session, task.id, worker="w", outcome="клиент подтвердил",
                              now=NOW + timedelta(minutes=2))
            await session.commit()
            await session.refresh(task)
            assert task.status == "completed"
            assert task.claimed_at is None and task.claimed_by is None
            assert task.completed_at is not None
            assert "completed" in await journal(session, task.id)
    run_with_db(scenario)


def test_a_task_cannot_be_finished_without_being_claimed():
    """Завершить незахваченную задачу нельзя: иначе непонятно, кто её делал."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            with pytest.raises(DomainError, match="was not claimed"):
                await finish_task(session, task.id, worker="w", outcome="ок", now=NOW)
    run_with_db(scenario)


def test_releasing_a_claim_returns_the_task_and_requires_a_reason():
    """Отпустить задачу можно только явно и с причиной."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="w", now=NOW)
            for reason in ("", "   "):
                with pytest.raises(DomainError, match="requires a reason"):
                    await release_claim(session, task.id, worker="w", reason=reason)
            await release_claim(session, task.id, worker="w",
                                reason="действие не состоялось, канал молчал")
            await session.commit()
            await session.refresh(task)
            assert task.claimed_at is None
            # Задача снова в очереди.
            assert [t.id for t in await due_tasks(session, now=NOW)] == [task.id]
    run_with_db(scenario)


def test_due_tasks_respect_the_supplied_clock():
    """Управляемые часы: срок проверяется подставленным моментом."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            soon = await add_task(session, case, at=NOW + timedelta(hours=1))
            await session.commit()
            # До срока задача не выдаётся.
            assert await due_tasks(session, now=NOW) == []
            # После срока — выдаётся, без всякого ожидания.
            assert [t.id for t in await due_tasks(
                session, now=NOW + timedelta(hours=2))] == [soon.id]
    run_with_db(scenario)


def test_due_tasks_can_be_narrowed_to_one_manager():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            mine = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await add_task(session, case, at=NOW - timedelta(minutes=5),
                           manager="someone_else")
            await session.commit()
            assert [t.id for t in await due_tasks(
                session, now=NOW, manager_id=OWNER.manager_id)] == [mine.id]
    run_with_db(scenario)


def test_ac29_reassigning_a_case_moves_its_open_tasks_to_the_new_owner(monkeypatch):
    """AC-29: открытые задачи переходят новому владельцу, выполненные остаются."""
    known_managers(monkeypatch, OWNER.manager_id, HEIR.manager_id)

    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            open_task = await add_task(session, case, at=NOW + timedelta(days=1))
            done = await add_task(session, case, at=NOW - timedelta(days=1))
            await CalendarTaskService.complete(session, done, actor=OWNER.manager_id)
            await session.commit()

            await reassign_case(session, case.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="менеджер в отпуске")
            await session.commit()

            await session.refresh(open_task)
            await session.refresh(done)
            # Открытая — у нового владельца.
            assert open_task.manager_id == HEIR.manager_id
            # Выполненная осталась за тем, кто её сделал: иначе из истории
            # исчезает, кто работал.
            assert done.manager_id == OWNER.manager_id
            assert "reassigned" in await journal(session, open_task.id)
    run_with_db(scenario)


def test_ac29_reassigning_one_case_does_not_touch_another_case_of_the_same_client(
        monkeypatch):
    """Перенос задач касается ТОЛЬКО этой услуги.

    В проекте уже был перенос по паре «контакт + направление» — он задел бы
    второй тур того же клиента. У семьи бывает две поездки одновременно.
    """
    known_managers(monkeypatch, OWNER.manager_id, HEIR.manager_id)

    async def scenario(sm):
        async with sm() as session:
            first = await tour_case(session, key="tr-a", reference="TR-A")
            second = await sign_contract(
                session, contact_id=first.contact_id, product_id=first.product_id,
                owner_login=OWNER.manager_id, by=OWNER, reference="TR-B",
                amount=Decimal("50000.00"), currency="KGS", idempotency_key="tr-b")
            await session.flush()
            task_a = await add_task(session, first, at=NOW + timedelta(days=1))
            task_b = await add_task(session, second, at=NOW + timedelta(days=1))
            await session.commit()

            await reassign_case(session, first.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="передача одной услуги")
            await session.commit()

            await session.refresh(task_a)
            await session.refresh(task_b)
            assert task_a.manager_id == HEIR.manager_id
            assert task_b.manager_id == OWNER.manager_id, "задета чужая услуга"
    run_with_db(scenario)


def test_transfer_is_idempotent_and_skips_tasks_already_owned():
    """Повторный перенос ничего не делает: задачи уже у нового владельца."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW + timedelta(days=1))
            await session.commit()
            first = await transfer_open_tasks(session, case.id,
                                              new_owner=HEIR.manager_id, actor="admin")
            second = await transfer_open_tasks(session, case.id,
                                               new_owner=HEIR.manager_id, actor="admin")
            await session.commit()
            assert first == (task.id,)
            assert second == ()
            assert len([e for e in await journal(session, task.id)
                        if e == "reassigned"]) == 1
    run_with_db(scenario)


def test_transfer_requires_a_new_owner():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            for owner in ("", "   "):
                with pytest.raises(DomainError, match="new_owner is required"):
                    await transfer_open_tasks(session, case.id, new_owner=owner,
                                              actor="admin")
    run_with_db(scenario)


def test_shifting_a_trip_moves_future_tasks_and_keeps_the_past():
    """Будущие задачи пересчитаны, прошедшие и выполненные — нет."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            future = await add_task(session, case, at=NOW + timedelta(days=5))
            past = await add_task(session, case, at=NOW - timedelta(days=5))
            done = await add_task(session, case, at=NOW + timedelta(days=6))
            await CalendarTaskService.complete(session, done, actor="manager")
            await session.commit()

            shifted = await shift_future_tasks(session, case.id, days=3,
                                               actor="manager", now=NOW)
            await session.commit()
            assert shifted == (future.id,)

            await session.refresh(future)
            await session.refresh(past)
            assert future.scheduled_at.replace(tzinfo=timezone.utc) == (
                NOW + timedelta(days=8))
            assert future.scheduled_date == (NOW + timedelta(days=8)).astimezone(
                BISHKEK).date()
            # Прошедшая не двинулась.
            assert past.scheduled_at.replace(tzinfo=timezone.utc) == (
                NOW - timedelta(days=5))
            assert "rescheduled" in await journal(session, future.id)
    run_with_db(scenario)


def test_shifting_backwards_never_moves_a_task_into_the_past():
    """Сдвиг назад не делает задачу сразу просроченной."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            soon = await add_task(session, case, at=NOW + timedelta(days=2))
            await session.commit()
            shifted = await shift_future_tasks(session, case.id, days=-10,
                                               actor="manager", now=NOW)
            await session.commit()
            assert shifted == ()
            await session.refresh(soon)
            assert soon.scheduled_at.replace(tzinfo=timezone.utc) > NOW
    run_with_db(scenario)


@pytest.mark.parametrize("days", [0, True, 1.5, "3", None])
def test_shift_requires_a_non_zero_whole_number_of_days(days):
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            with pytest.raises(DomainError, match="days must be"):
                await shift_future_tasks(session, case.id, days=days, actor="m",
                                         now=NOW)
    run_with_db(scenario)


@pytest.mark.parametrize("moment", [None, "2026-11-10", 1762765200])
def test_a_naive_or_wrong_clock_is_rejected(moment):
    """Наивное время и не-дата отклоняются: ошибка на сутки дороже отказа."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await add_task(session, case, at=NOW)
            if moment is None:
                naive = datetime(2026, 11, 10, 9, 0)
                with pytest.raises(DomainError, match="timezone-aware"):
                    await due_tasks(session, now=naive)
            else:
                with pytest.raises(DomainError, match="must be a datetime"):
                    await due_tasks(session, now=moment)
    run_with_db(scenario)


def test_case_tasks_are_closed_for_other_managers():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await add_task(session, case, at=NOW)
            await session.commit()
            for by in (PEER, VISA, Actor(manager_id="", allowed_directions=())):
                with pytest.raises(PermissionDenied):
                    await case_tasks(session, case.id, by=by)
            assert len(await case_tasks(session, case.id, by=OWNER)) == 1
    run_with_db(scenario)


def test_overdue_is_computed_on_the_bishkek_calendar():
    """Просрочка считается по местному дню, а не по UTC."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW)
            await session.commit()
            day = task.scheduled_date
            assert not overdue_on(task, today=day)
            assert overdue_on(task, today=day + timedelta(days=1))
            # Завершённая задача просроченной не считается.
            await CalendarTaskService.complete(session, task, actor="m")
            assert not overdue_on(task, today=day + timedelta(days=30))
    run_with_db(scenario)


def test_case_tasks_can_hide_finished_ones():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            active = await add_task(session, case, at=NOW + timedelta(days=1))
            done = await add_task(session, case, at=NOW - timedelta(days=1))
            await CalendarTaskService.complete(session, done, actor="m")
            await session.commit()
            assert [t.id for t in await case_tasks(
                session, case.id, by=OWNER, include_finished=False)] == [active.id]
            assert len(await case_tasks(session, case.id, by=OWNER)) == 2
    run_with_db(scenario)


def run_two_sessions(scenario):
    """Запустить сценарий с ДВУМЯ независимыми подключениями к одной базе.

    Общий раннер держит одно соединение в памяти (StaticPool) — настоящую гонку
    на нём не воспроизвести: «cannot start a transaction within a transaction».
    Поэтому берём файл и два отдельных движка, как два живых воркера.
    """
    import tempfile
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.domain.models import DomainBase

    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            url = f"sqlite+aiosqlite:///{(Path(tmp) / 'race.db').as_posix()}"
            first = create_async_engine(url)
            second = create_async_engine(url)
            try:
                async with first.begin() as connection:
                    await connection.run_sync(DomainBase.metadata.create_all)
                await scenario(async_sessionmaker(first, expire_on_commit=False),
                               async_sessionmaker(second, expire_on_commit=False))
            finally:
                await first.dispose()
                await second.dispose()

    asyncio.run(main())


def test_ac28_two_sessions_cannot_both_claim_the_same_task():
    """AC-28: гонка ДВУХ ПОДКЛЮЧЕНИЙ — захватывает только один.

    Прежний тест делал последовательные вызовы в одной сессии и дефект не видел:
    захват был «прочитать, проверить, записать», и два исполнителя оба получали
    успех. Здесь каждая сессия заранее читает задачу — так и работает воркер:
    сначала опрашивает очередь, потом захватывает.
    """
    async def scenario(make_first, make_second):
        async with make_first() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await session.commit()
            task_id = task.id

        async with make_first() as a_session, make_second() as b_session:
            # Оба держат объект в кэше своей сессии — как после опроса очереди.
            assert await a_session.get(CalendarTask, task_id) is not None
            assert await b_session.get(CalendarTask, task_id) is not None
            a = await claim_task(a_session, task_id, worker="worker-A", now=NOW)
            await a_session.commit()
            b = await claim_task(b_session, task_id, worker="worker-B", now=NOW)
            await b_session.commit()
            assert [a.claimed, b.claimed] == [True, False], (a, b)
            assert "worker-A" in b.reason

        async with make_second() as session:
            stored = await session.get(CalendarTask, task_id)
            assert stored.claimed_by == "worker-A"

    run_two_sessions(scenario)


def test_ac28_a_stale_cached_object_does_not_let_a_second_claim_through():
    """Устаревший объект в кэше сессии не даёт захватить дважды."""
    async def scenario(make_first, make_second):
        async with make_first() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await session.commit()
            task_id = task.id

        async with make_first() as watcher:
            # Читаем до чужого захвата — объект устаревает.
            cached = await watcher.get(CalendarTask, task_id)
            assert cached.claimed_at is None
            async with make_second() as other:
                await claim_task(other, task_id, worker="fast", now=NOW)
                await other.commit()
            late = await claim_task(watcher, task_id, worker="slow", now=NOW)
            await watcher.commit()
            assert late.claimed is False
            assert "fast" in late.reason

    run_two_sessions(scenario)


def test_only_the_claiming_worker_can_finish_the_task():
    """Чужой исполнитель не закрывает чужую работу."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="worker-A", now=NOW)
            with pytest.raises(DomainError, match="that claimed the task"):
                await finish_task(session, task.id, worker="worker-C",
                                  outcome="я за него", now=NOW)
            await session.commit()
            await session.refresh(task)
            assert task.status == "planned" and task.claimed_by == "worker-A"
    run_with_db(scenario)


def test_a_cancelled_task_cannot_be_quietly_completed():
    """Отменённую задачу нельзя тихо перевести в «выполнено».

    Менеджер отменил задачу, пока исполнитель её держал. Прежняя версия писала
    «completed» — в журнале это выглядело как «клиенту отправили».
    """
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="w", now=NOW)
            await CalendarTaskService.cancel(session, task, actor="manager")
            with pytest.raises(DomainError, match="cannot be completed"):
                await finish_task(session, task.id, worker="w", outcome="готово",
                                  now=NOW)
            await session.commit()
            await session.refresh(task)
            assert task.status == "cancelled"
            assert task.completed_at is None
    run_with_db(scenario)


def test_a_stranger_cannot_release_someone_elses_claim():
    """Чужой захват не снимается: действие может выполняться прямо сейчас."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="worker-A", now=NOW)
            with pytest.raises(DomainError, match="that claimed the task"):
                await release_claim(session, task.id, worker="stranger",
                                    reason="отпущу-ка")
            await session.commit()
            await session.refresh(task)
            assert task.claimed_by == "worker-A"
            # Разбор подвисшего захвата человеком — отдельное явное действие.
            await release_claim(session, task.id, worker="admin", force=True,
                                reason="процесс не вернулся, сверено вручную")
            await session.commit()
            await session.refresh(task)
            assert task.claimed_at is None
            assert "claim_released" in await journal(session, task.id)
    run_with_db(scenario)


def test_a_task_can_be_claimed_again_after_an_honest_release():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(minutes=5))
            await claim_task(session, task.id, worker="w1", now=NOW)
            await release_claim(session, task.id, worker="w1",
                                reason="канал не ответил")
            again = await claim_task(session, task.id, worker="w2", now=NOW)
            await session.commit()
            assert again.claimed is True
            await session.refresh(task)
            assert task.claimed_by == "w2"
    run_with_db(scenario)


def test_shifting_does_not_move_a_task_that_is_being_worked_on():
    """Задачу в работе не сдвигаем: условия менялись бы под процессом."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            working = await add_task(session, case, at=NOW + timedelta(days=2))
            free = await add_task(session, case, at=NOW + timedelta(days=3))
            await claim_task(session, working.id, worker="w", now=NOW)
            await session.commit()
            shifted = await shift_future_tasks(session, case.id, days=5,
                                               actor="manager", now=NOW)
            await session.commit()
            assert shifted == (free.id,)
            await session.refresh(working)
            assert working.scheduled_at.replace(tzinfo=timezone.utc) == (
                NOW + timedelta(days=2))
    run_with_db(scenario)


@pytest.mark.parametrize("days", [3651, -3651, 10 ** 9])
def test_an_absurd_shift_is_refused_before_anything_moves(days):
    """Огромный сдвиг отклоняется до работы, а не падает посреди цикла."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW + timedelta(days=2))
            await session.commit()
            with pytest.raises(DomainError, match="within 3650 days"):
                await shift_future_tasks(session, case.id, days=days,
                                         actor="m", now=NOW)
            await session.commit()
            await session.refresh(task)
            assert task.scheduled_at.replace(tzinfo=timezone.utc) == (
                NOW + timedelta(days=2))
    run_with_db(scenario)


def test_tasks_without_a_case_link_are_reported_on_reassignment(monkeypatch):
    """Задачи без ссылки на услугу остаются, но о них СООБЩАЮТ.

    Такие задачи создавал прежний код, и в боевой базе они уже есть. Привязать
    их автоматически нельзя: у клиента бывает несколько услуг одного направления.
    Поэтому их не трогаем, но делаем видимыми в истории переназначения.
    """
    known_managers(monkeypatch, OWNER.manager_id, HEIR.manager_id)

    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            orphan = CalendarTask(
                contact_id=case.contact_id, manager_id=OWNER.manager_id,
                direction="tours", kind="call", comment="задача из прежнего кода",
                scheduled_date=(NOW + timedelta(days=1)).astimezone(BISHKEK).date(),
                scheduled_at=NOW + timedelta(days=1), created_by="old",
                service_case_id=None)
            session.add(orphan)
            await session.flush()
            await session.commit()

            await reassign_case(session, case.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="передача")
            await session.commit()

            await session.refresh(orphan)
            # Задача не переехала — её нельзя привязать наверняка.
            assert orphan.manager_id == OWNER.manager_id
            # Но в истории она названа.
            event = next(e for e in await session.scalars(
                select(ServiceEvent).where(
                    ServiceEvent.event_type == "tasks_transferred")))
            assert orphan.id in event.payload["orphan_task_ids"]
    run_with_db(scenario)


def test_repeating_a_reassignment_pulls_tasks_created_later(monkeypatch):
    """Повторное переназначение дотягивает задачи, появившиеся позже.

    Ранний выход «владелец уже этот» не давал исправить расхождение: задача,
    созданная после первой передачи, оставалась у прежнего менеджера навсегда.
    """
    known_managers(monkeypatch, OWNER.manager_id, HEIR.manager_id)

    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await session.commit()
            await reassign_case(session, case.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="первая передача")
            await session.commit()
            # Задача появилась уже после передачи, на прежнего менеджера.
            late = await add_task(session, case, at=NOW + timedelta(days=1),
                                  manager=OWNER.manager_id)
            await session.commit()
            await reassign_case(session, case.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="повторная передача")
            await session.commit()
            await session.refresh(late)
            assert late.manager_id == HEIR.manager_id
    run_with_db(scenario)


def test_a_claim_dated_in_the_future_is_still_reported_as_stale():
    """Захват с датой в будущем (разъезд часов) не должен прятаться навсегда."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task = await add_task(session, case, at=NOW - timedelta(hours=1))
            await claim_task(session, task.id, worker="w",
                             now=NOW + timedelta(days=1))
            await session.commit()
            # Смотрим «сейчас»: захват помечен будущим временем.
            found = await stale_claims(session, now=NOW, older_than_minutes=0)
            assert [t.id for t in found] == [task.id]
    run_with_db(scenario)


def test_the_initial_task_of_a_contract_moves_to_the_new_owner(monkeypatch):
    """Начальная задача договора переезжает при переназначении.

    Проверяется БЕЗ удаления начальной задачи: именно она раньше оставалась у
    прежнего владельца, потому что не имела ссылки на услугу.
    """
    known_managers(monkeypatch, OWNER.manager_id, HEIR.manager_id)

    async def scenario(sm):
        async with sm() as session:
            contact = Contact()
            session.add(contact)
            await session.flush()
            products = await seed_products(session, published_by="admin",
                                           by=SYSTEM_ACTOR)
            tour = next(p for p in products if p.code == "tour_package")
            case = await sign_contract(
                session, contact_id=contact.id, product_id=tour.id,
                owner_login=OWNER.manager_id, by=OWNER, reference="TR-INIT",
                amount=Decimal("100000.00"), currency="KGS",
                idempotency_key="tr-init")
            await session.commit()
            initial = list(await session.scalars(select(CalendarTask).where(
                CalendarTask.service_case_id == case.id)))
            assert initial, "начальная задача не создана"

            await reassign_case(session, case.id, target_login=HEIR.manager_id,
                                by=ADMIN, reason="передача")
            await session.commit()
            for task in initial:
                await session.refresh(task)
                assert task.manager_id == HEIR.manager_id
    run_with_db(scenario)
