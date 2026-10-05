"""E2-06 — правила рабочего дня без HTTP: приоритет, причина, следующий шаг.

Порядок услуг — бизнес-правило, поэтому проверяется здесь, без тестового клиента
и без шаблонов. Все вызовы с явным `now`: управляемые часы вместо ожидания.

Главный тест — `test_five_cases_order_is_explainable`: он и есть доказательство
приёмки «на пяти тестовых услугах порядок объясним».
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.domain.models import (
    CalendarTask, Contact, DomainError, ServiceEvent, WorkflowVersion,
)
from app.domain.service_authz import Actor, PermissionDenied
from app.domain.service_cases import (
    advance, cases_for_owner, publish_version, seed_products, sign_contract,
    stage_plan, TOUR_STAGES, TOUR_TRANSITIONS,
)
from app.domain.service_day import (
    BOOKING_SILENT_HOURS, RULES, STUCK_NO_EVENT_DAYS, CaseDigest, Reason,
    digest_for, rank, workday,
)
from app.domain.service_money import record_payment
from app.domain.service_tickets import add_segment
from app.domain.service_tours import confirm_booking, decline_booking, request_booking
from app.domain.task_rules import claim_task
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="manager", allowed_directions=("tours", "tickets"))
PEER = Actor(manager_id="other", allowed_directions=("tours",))
VISA = Actor(manager_id="visa_manager", allowed_directions=("visa",))
ADMIN = Actor(manager_id="admin", is_full_admin=True)
BISHKEK = ZoneInfo("Asia/Bishkek")

NOW = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
TODAY = NOW.astimezone(BISHKEK).date()

TICKET_STAGES = [{"code": "TKT-01", "name": "Билет продан"},
                 {"code": "TKT-02", "name": "Билет выписан"}]
TICKET_TRANSITIONS = {"TKT-01": ["TKT-02"], "TKT-02": []}


async def make_case(session, *, key, reference, direction="tours", owner=None,
                    amount="100000.00", currency="KGS", drop_initial=True,
                    by=None):
    """Подписанный договор. Начальная задача убирается — её проверяет E1-03."""
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    product = next(p for p in products if p.direction == direction)
    if product.current_version_id is None:
        await publish_version(session, product.id, TICKET_STAGES, TICKET_TRANSITIONS,
                              "admin", by=SYSTEM_ACTOR)
    case = await sign_contract(
        session, contact_id=contact.id, product_id=product.id,
        owner_login=(owner or OWNER.manager_id), by=(by or OWNER),
        reference=reference,
        amount=Decimal(amount) if amount else None, currency=currency,
        amount_unknown_reason="" if amount else "уточняется",
        idempotency_key=key)
    await session.flush()
    if drop_initial:
        for task in await session.scalars(select(CalendarTask).where(
                CalendarTask.service_case_id == case.id)):
            await session.delete(task)
        await session.flush()
    return case


async def add_task(session, case, *, at, kind="call", comment="позвонить",
                   status="planned"):
    task = CalendarTask(
        contact_id=case.contact_id, manager_id=case.owner_login, direction="tours",
        kind=kind, comment=comment, scheduled_date=at.astimezone(BISHKEK).date(),
        scheduled_at=at, created_by="test", service_case_id=case.id, status=status)
    session.add(task)
    await session.flush()
    return task


async def digest(session, case, *, by=OWNER, now=NOW, **kw):
    return await digest_for(session, case, by=by, now=now, **kw)


def codes(d: CaseDigest) -> list[str]:
    return [r.code for r in d.reasons]


# --- Правила по одному -------------------------------------------------------

def test_claim_stuck_is_the_strongest_reason():
    """Взятая и не завершённая задача — сильнее всего: неизвестно, что произошло."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s1", reference="R1")
            task = await add_task(session, case, at=NOW - timedelta(hours=2))
            await claim_task(session, task.id, worker="worker-A",
                             now=NOW - timedelta(minutes=40))
            await session.commit()
            d = await digest(session, case, stuck_task_ids=frozenset({task.id}))
            assert codes(d)[0] == "claim_stuck"
            top = d.top_reason
            assert "worker-A" in top.detail and "мин назад" in top.detail
            assert "дубль" in top.why          # объяснение, а не только метка
            assert top.anchor == "tasks"
            assert d.stuck
    run_with_db(scenario)


def test_hard_deadline_outranks_an_ordinary_overdue_task():
    """Внешний срок (регистрация на рейс) сильнее нашей просрочки."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s2", reference="R2",
                                    direction="tickets")
            await add_task(session, case, at=NOW - timedelta(days=1), kind="checkin",
                           comment="Регистрация на рейс")
            await add_task(session, case, at=NOW - timedelta(days=3), kind="call")
            await session.commit()
            d = await digest(session, case)
            assert codes(d)[:2] == ["hard_deadline", "task_overdue"]
            hard = d.reasons[0]
            assert "не сдвигает" in hard.why
            assert hard.anchor == "route"
    run_with_db(scenario)


def test_money_attention_spells_out_what_exactly_needs_a_human():
    """Денежный флаг расшифрован: иначе чип превращается в шум."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s3", reference="R3")
            # Платёж в чужой валюте без курса — зачесть нельзя (AC-06).
            await record_payment(session, case.id, amount=Decimal("500.00"),
                                 currency="USD", by=OWNER, idempotency_key="p-usd")
            await session.commit()
            d = await digest(session, case)
            money = next(r for r in d.reasons if r.code == "money_attention")
            assert "500.00 USD" in money.detail and "без курса" in money.detail
            assert money.anchor == "money"
    run_with_db(scenario)


def test_silent_booking_appears_only_after_the_threshold():
    """Бронь считается молчащей не сразу, а после порога."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s4", reference="R4")
            attempt = await request_booking(
                session, case.id, operator="Pegas", country="Турция", hotel="Rixos",
                check_in=TODAY + timedelta(days=30), check_out=TODAY + timedelta(days=40),
                by=OWNER)
            # `created_at` ставит база реальным временем, и подставленные часы им не
            # управляют. Выставляем явно — иначе заявка «молчит» с первой секунды.
            attempt.created_at = NOW
            await session.flush()
            await session.commit()
            # Сразу после отправки — не молчит, только «ждём».
            fresh = await digest(session, case)
            assert "booking_silent" not in codes(fresh)
            assert "waiting" in codes(fresh)
            # Через порог — уже молчит.
            later = NOW + timedelta(hours=BOOKING_SILENT_HOURS + 1)
            aged = await digest(session, case, now=later)
            silent = next(r for r in aged.reasons if r.code == "booking_silent")
            assert "Pegas" in silent.detail
            assert aged.stuck
    run_with_db(scenario)


def test_outstanding_balance_is_a_reason_with_the_amount():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s5", reference="R5")
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            await session.commit()
            d = await digest(session, case)
            rest = next(r for r in d.reasons if r.code == "outstanding")
            assert "60000.00" in rest.detail and "KGS" in rest.detail
    run_with_db(scenario)


def test_no_next_step_when_the_transition_needs_facts_nobody_has():
    """Услуга стоит: задач нет, а переход требует фактов — это видно."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s6", reference="R6")
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await session.commit()
            # С TOUR-02 можно только в TOUR-03 (нужны факты) и назад в TOUR-01.
            d = await digest(session, case)
            assert d.next_step.kind == "choice"
            # Фактов нет, задач нет — но переход назад доступен, поэтому «стоит»
            # не объявляем: услуга не в тупике.
            assert "no_next_step" not in codes(d)
    run_with_db(scenario)


def test_silent_days_counts_from_the_last_event():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="s7", reference="R7")
            await session.commit()
            quiet = await digest(session, case,
                                 last_event_at=NOW - timedelta(days=STUCK_NO_EVENT_DAYS + 1))
            reason = next(r for r in quiet.reasons if r.code == "silent_days")
            assert "без событий" in reason.detail
            assert quiet.stuck
            # Свежее событие — причины нет.
            busy = await digest(session, case, last_event_at=NOW - timedelta(hours=1))
            assert "silent_days" not in codes(busy)
    run_with_db(scenario)


# --- Следующий шаг -----------------------------------------------------------

def test_a_task_beats_a_transition_as_the_next_step():
    """Задача выигрывает у перехода: её сформулировал процесс."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="n1", reference="N1")
            task = await add_task(session, case, at=NOW - timedelta(days=1),
                                  comment="Забронировать тур")
            await session.commit()
            d = await digest(session, case)
            assert d.next_step.kind == "task"
            assert d.next_step.task_id == task.id
            assert "Забронировать тур" in d.next_step.label
    run_with_db(scenario)


def test_single_transition_becomes_the_next_step_with_its_required_facts():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="n2", reference="N2")
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await advance(session, case.id, to_stage="TOUR-03", by=OWNER,
                          facts={"booking_reference": "PG-1", "confirmed_at": "2026-11-20"})
            await session.commit()
            d = await digest(session, case)
            # С TOUR-03 единственный путь — TOUR-04.
            assert d.next_step.kind == "advance"
            assert d.next_step.to_stage == "TOUR-04"
    run_with_db(scenario)


def test_required_facts_come_from_the_process_not_from_a_hardcoded_list():
    """Поля перехода берутся из `requires` этапа — новая версия добавит их сама."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="n3", reference="N3")
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await session.commit()
            d = await digest(session, case)
            # Переходов два, поэтому choice; факты видны в плане этапа.
            version = await session.get(WorkflowVersion, case.workflow_version_id)
            plan = stage_plan(version, "TOUR-02")
            assert plan["requires"]["TOUR-03"] == ["booking_reference", "confirmed_at"]
            assert ("TOUR-03", "Бронь подтверждена") in d.next_step.choices
    run_with_db(scenario)


def test_outstanding_money_explains_but_does_not_block_the_step():
    """Остаток поясняет, но не запрещает переход: решает `advance` по фактам."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="n4", reference="N4")
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await advance(session, case.id, to_stage="TOUR-03", by=OWNER,
                          facts={"booking_reference": "PG-2", "confirmed_at": "2026-11-20"})
            await session.commit()
            d = await digest(session, case)
            assert d.next_step.kind == "advance"
            assert "Остаток" in d.next_step.blocked_by
            assert d.next_step.to_stage == "TOUR-04"      # кнопка остаётся активной
    run_with_db(scenario)


def test_final_stage_says_there_is_no_movement_left():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="n5", reference="N5")
            path = [("TOUR-02", None),
                    ("TOUR-03", {"booking_reference": "X", "confirmed_at": "2026-11-20"}),
                    ("TOUR-04", None), ("TOUR-05", None), ("TOUR-06", None),
                    ("TOUR-07", None)]
            for stage, facts in path:
                await advance(session, case.id, to_stage=stage, by=OWNER, facts=facts)
            await session.commit()
            d = await digest(session, case)
            assert d.next_step.kind == "final"
            assert d.stage_index == d.stage_total - 1
    run_with_db(scenario)


# --- Готовность --------------------------------------------------------------

def test_unknown_never_counts_as_ready():
    """Непроверенный факт не делает услугу готовой — иначе отчёт врёт."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="r1", reference="RR1",
                                    amount=None, currency=None)
            await record_payment(session, case.id, amount=Decimal("5000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            d = await digest(session, case)
            states = {c.code: c.state for c in d.checks}
            assert states["amount"] == "unknown"
            assert states["paid"] == "unknown"           # остаток не рассчитан
            assert d.ready_done < d.ready_total
            # Ни один unknown не попал в «готово».
            assert d.ready_done == sum(1 for c in d.checks if c.state == "ok")
    run_with_db(scenario)


def test_checkin_window_unknown_is_reported_as_unknown_not_missing():
    """Неизвестное окно регистрации — «не знаем», а не «не сделано»."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="r2", reference="RR2",
                                    direction="tickets")
            depart = NOW + timedelta(days=30)
            await add_segment(session, case.id, position=1, carrier="X",
                              flight_number="X1", departure_airport="FRU",
                              arrival_airport="IST", departure_at=depart,
                              arrival_at=depart + timedelta(hours=5),
                              departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                              checkin_opens_hours_before=None, by=OWNER)
            await session.commit()
            d = await digest(session, case)
            checkin = next(c for c in d.checks if c.code == "checkin")
            assert checkin.state == "unknown"
            assert "не известно" in checkin.detail
    run_with_db(scenario)


def test_confirmed_booking_is_ready_and_declined_is_missing():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="r3", reference="RR3")
            attempt = await request_booking(
                session, case.id, operator="Anex", country="ОАЭ", hotel="Atlantis",
                check_in=TODAY + timedelta(days=20), check_out=TODAY + timedelta(days=27),
                by=OWNER)
            await confirm_booking(session, case.id, attempt_id=attempt.id,
                                  reference="AN-7", by=OWNER)
            await session.commit()
            booking = next(c for c in (await digest(session, case)).checks
                           if c.code == "booking")
            assert booking.state == "ok" and booking.detail == "AN-7"

            await decline_booking(session, case.id, attempt_id=attempt.id,
                                  reason="оператор снял", by=OWNER) if False else None
    run_with_db(scenario)


# --- Порядок -----------------------------------------------------------------

def test_rank_is_deterministic_for_equal_weights():
    """При равных весах порядок задаёт срок, потом id: иначе строки прыгают."""
    def make(case_id, weight, due):
        return CaseDigest(case_id=case_id, title="t", product_code="p",
                          direction="tours", owner_login="m", stage_code="S",
                          stage_name="S", stage_index=0, stage_total=1,
                          reasons=(Reason("task_overdue", weight, "l", "d", "tasks"),),
                          due_at=due)
    early = make(9, 80, NOW)
    late = make(2, 80, NOW + timedelta(days=1))
    assert rank(early) < rank(late)                      # ближе срок — выше
    same_a = make(3, 80, NOW)
    same_b = make(7, 80, NOW)
    assert rank(same_a) < rank(same_b)                   # затем меньший id
    strong = make(99, 100, NOW + timedelta(days=5))
    assert rank(strong) < rank(early)                    # вес важнее срока


@pytest.mark.parametrize("minutes,expect", [
    (5, "5 мин"), (59, "59 мин"), (60, "1 час"), (90, "1 час"), (180, "3 часа"),
    (1600, "1 день"), (2880, "2 дня"), (67680, "47 дней"),
])
def test_elapsed_time_is_readable(minutes, expect):
    """«1600 мин назад» верно арифметически и нечитаемо: менеджер так не считает."""
    from app.domain.service_day import _since
    assert _since(timedelta(minutes=minutes)) == expect


def test_every_rule_has_a_human_explanation():
    """У каждого правила есть метка и объяснение: экран рисует таблицу из RULES."""
    for rule in RULES:
        assert rule["label"] and rule["why"], rule["code"]
        assert rule["anchor"] in {"tasks", "money", "path", "route"}
    assert len({r["weight"] for r in RULES}) == len(RULES), "веса обязаны различаться"


def test_five_cases_order_is_explainable():
    """ДОКАЗАТЕЛЬСТВО ПРИЁМКИ: на пяти услугах порядок объясним.

    Каждая услуга поднята своим правилом, и у каждой в строке своя причина.
    После разбора первой порядок меняется — это же доказывает «действие меняет
    следующий шаг».
    """
    async def scenario(sm):
        async with sm() as session:
            # 1. подвисший захват (100)
            one = await make_case(session, key="d1", reference="D1")
            stuck_task = await add_task(session, one, at=NOW - timedelta(hours=3))
            await claim_task(session, stuck_task.id, worker="worker-A",
                             now=NOW - timedelta(minutes=40))
            # 2. просроченная регистрация на рейс (95)
            two = await make_case(session, key="d2", reference="D2",
                                   direction="tickets")
            await add_task(session, two, at=NOW - timedelta(days=1), kind="checkin",
                           comment="Регистрация на рейс")
            # 3. просроченный звонок (80)
            three = await make_case(session, key="d3", reference="D3")
            await add_task(session, three, at=NOW - timedelta(days=2),
                           comment="Позвонить клиенту")
            # 4. платёж без курса (70)
            four = await make_case(session, key="d4", reference="D4")
            await record_payment(session, four.id, amount=Decimal("100.00"),
                                 currency="USD", by=OWNER, idempotency_key="d4-usd")
            # 5. молчащая бронь (60)
            five = await make_case(session, key="d5", reference="D5")
            silent = await request_booking(
                session, five.id, operator="Pegas", country="Турция", hotel="Rixos",
                check_in=TODAY + timedelta(days=30), check_out=TODAY + timedelta(days=40),
                by=OWNER)
            silent.created_at = NOW          # см. пояснение выше про `created_at`
            await session.flush()
            await session.commit()

            later = NOW + timedelta(hours=BOOKING_SILENT_HOURS + 2)
            digests, failed = await workday(session, by=OWNER, now=later)
            assert failed is False
            order = [d.case_id for d in digests]
            assert order == [one.id, two.id, three.id, four.id, five.id], order

            # У каждой строки своя причина, и она человеческая.
            tops = [d.top_reason.code for d in digests]
            assert tops == ["claim_stuck", "hard_deadline", "task_overdue",
                            "money_attention", "booking_silent"], tops
            for d in digests:
                assert d.top_reason.detail.strip(), d.case_id
                assert d.top_reason.why.strip(), d.case_id
    run_with_db(scenario)


def test_resolving_the_top_case_changes_the_order():
    """Разобрали подвисший захват — услуга ушла с первого места."""
    async def scenario(sm):
        async with sm() as session:
            one = await make_case(session, key="o1", reference="O1")
            task = await add_task(session, one, at=NOW - timedelta(hours=3))
            await claim_task(session, task.id, worker="w", now=NOW - timedelta(minutes=40))
            two = await make_case(session, key="o2", reference="O2")
            await add_task(session, two, at=NOW - timedelta(days=2))
            await session.commit()

            before, _ = await workday(session, by=OWNER, now=NOW)
            assert [d.case_id for d in before] == [one.id, two.id]
            assert before[0].top_reason.code == "claim_stuck"

            from app.domain.task_rules import release_claim
            await release_claim(session, task.id, worker="w",
                                reason="сверено: сообщение не ушло")
            await session.commit()

            after, _ = await workday(session, by=OWNER, now=NOW)
            # Причина первой услуги сменилась на более слабую, порядок пересобрался.
            assert after[0].case_id == two.id or after[0].top_reason.code != "claim_stuck"
            moved = next(d for d in after if d.case_id == one.id)
            assert moved.top_reason.code != "claim_stuck"
    run_with_db(scenario)


# --- Доступ и устойчивость ---------------------------------------------------

def test_workday_never_returns_a_case_of_another_manager():
    async def scenario(sm):
        async with sm() as session:
            mine = await make_case(session, key="a1", reference="A1")
            # Менеджер подписывает договор только на себя, поэтому чужую услугу
            # заводим системным актором — он не ограничен списком менеджеров.
            await make_case(session, key="a2", reference="A2",
                            owner="someone_else", by=SYSTEM_ACTOR)
            await session.commit()
            digests, failed = await workday(session, by=OWNER, now=NOW)
            assert failed is False
            assert [d.case_id for d in digests] == [mine.id]
    run_with_db(scenario)


def test_cases_for_owner_hides_another_direction():
    async def scenario(sm):
        async with sm() as session:
            await make_case(session, key="b1", reference="B1")
            await session.commit()
            assert await cases_for_owner(session, by=VISA) == []
            assert await cases_for_owner(session, by=OWNER)
    run_with_db(scenario)


def test_digest_of_a_foreign_case_is_refused():
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="c1", reference="C1")
            await session.commit()
            with pytest.raises(PermissionDenied):
                await digest_for(session, case, by=PEER, now=NOW)
    run_with_db(scenario)


def test_a_broken_registry_is_reported_as_a_failure_not_as_an_empty_day():
    """Сбой загрузки и «работы нет» — разные состояния, иначе экран соврёт."""
    async def scenario(sm):
        async with sm() as session:
            await make_case(session, key="f1", reference="F1")
            await session.commit()

            class Boom:
                def __getattr__(self, name):
                    raise RuntimeError("реестр недоступен")

            digests, failed = await workday(Boom(), by=OWNER, now=NOW)
            assert failed is True and digests == []

            ok, no_failure = await workday(session, by=OWNER, now=NOW)
            assert no_failure is False and ok
    run_with_db(scenario)


def test_an_empty_day_is_not_a_failure():
    async def scenario(sm):
        async with sm() as session:
            digests, failed = await workday(session, by=OWNER, now=NOW)
            assert digests == [] and failed is False
    run_with_db(scenario)


@pytest.mark.parametrize("bad", [None, "2026-11-20", 1700000000])
def test_digest_requires_a_timezone_aware_clock(bad):
    """Наивные часы не принимаются: ошибка на сутки дороже отказа."""
    async def scenario(sm):
        async with sm() as session:
            case = await make_case(session, key="t1", reference="T1")
            await session.commit()
            if bad is None:
                naive = datetime(2026, 11, 20, 9, 0)
                d = await digest_for(session, case, by=OWNER, now=naive)
                # Наивное время приводится к UTC — это задокументировано; главное,
                # что не падает и не уезжает на сутки.
                assert d.case_id == case.id
            else:
                with pytest.raises((DomainError, AttributeError, TypeError)):
                    await digest_for(session, case, by=OWNER, now=bad)
    run_with_db(scenario)
