"""E2-03 — деньги по услуге: оплаты, возвраты, остаток (CRITICAL).

Три правила, из которых следует всё остальное.

1. **Только Decimal.** Ни одного `float` на пути денег. `float` теряет копейки
   незаметно, и расхождение всплывает через месяц в отчёте, когда уже не понять,
   где оно возникло. Старый `sale_amount` в legacy как раз `Float` — поэтому он
   не становится оплатой, а идёт на сверку человеку (AC-07, см. `legacy_match`).

2. **Журнал фактов, а не счёт.** Остаток считается заново по строкам журнала.
   Хранимого «итого» нет: два источника правды неизбежно разойдутся, и тогда
   непонятно, какому верить. Исправление не правит строку, а добавляет новую.

3. **Чего не знаем — не считаем.** Платёж в чужой валюте без курса не зачитывается
   в остаток (AC-06): он виден в своей валюте, но ложного остатка не создаёт.
   Обязательство вернуть деньги — не возврат (AC-04): пока перевод не сделан,
   деньги у компании, и отчёт не вправе показывать их вернувшимися.

Чего здесь намеренно НЕТ. Мы не решаем, кто вносит госплатёж и что подлежит
возврату (DEC-02), и не начисляем сборы за повторную подачу (DEC-05) — эти правила
бизнес не определил. Модуль фиксирует подтверждённый факт и считает арифметику;
решение остаётся за человеком.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.domain.models import (
    DomainError, Product, ServiceCase, ServiceEvent, ServicePayment,
)
from app.domain.service_authz import (
    Actor, PermissionDenied, can_advance_case, can_correct_money, can_view_case,
    require,
)

PAYMENT = "payment"
REFUND_DUE = "refund_due"      # обязательство вернуть: решение есть, перевода нет
REFUND_PAID = "refund_paid"    # факт возврата: деньги ушли клиенту
CORRECTION = "correction"      # исправление ранее записанной строки
VOID = "void"                  # аннулирование: записи не было
KINDS = (PAYMENT, REFUND_DUE, REFUND_PAID, CORRECTION, VOID)

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("10") ** 12


@dataclass(frozen=True)
class Balance:
    """Денежная картина по услуге. Всё в валюте договора, кроме `unconverted`."""

    currency: str | None = None
    agreed: Decimal | None = None          # сумма договора, None если неизвестна
    paid: Decimal = Decimal("0.00")        # зачтённые оплаты
    refunded: Decimal = Decimal("0.00")    # фактически возвращено
    refund_due: Decimal = Decimal("0.00")  # обязательства, перевода ещё не было
    # Строки, которые нельзя выразить в валюте договора: нет курса (AC-06).
    # Ключ — валюта, значение — сумма в ней. В остаток НЕ входят. Три словаря
    # раздельно, потому что в одном обязательство гасило платёж и сигнал
    # «нужен человек» пропадал — хотя деньги при этом никуда не делись.
    unconverted: dict[str, Decimal] = field(default_factory=dict)
    foreign_refund_due: dict[str, Decimal] = field(default_factory=dict)
    foreign_refunded: dict[str, Decimal] = field(default_factory=dict)
    # Строки, которые не удалось истолковать: круговая ссылка исправлений или
    # исправление без цели. Такое возможно только при правке базы в обход домена,
    # но деньги в них реальные — молчать о них нельзя.
    broken_entries: tuple[int, ...] = ()

    @property
    def outstanding(self) -> Decimal | None:
        """Остаток к доплате. None, если сумма договора неизвестна.

        Возвращённые деньги увеличивают остаток обратно: клиенту вернули — значит
        он снова не доплатил. Обязательства НЕ учитываются: пока перевод не сделан,
        деньги у компании, и долга перед ней на эту сумму нет.
        """
        if self.agreed is None:
            return None
        return (self.agreed - self.paid + self.refunded).quantize(CENT)

    @property
    def needs_attention(self) -> bool:
        """Есть ли что-то, требующее человека.

        Любая строка в чужой валюте без курса, любое непогашенное обязательство,
        и переплата: если оплачено больше суммы договора, это либо возврат,
        либо ошибка — в обоих случаях нужен человек, а не молчание.
        """
        if (self.unconverted or self.foreign_refund_due or self.foreign_refunded
                or self.refund_due > 0 or self.broken_entries):
            return True
        if self.agreed is not None and (self.paid - self.refunded) > self.agreed:
            return True
        if self.refunded > self.paid:
            # Вернули больше, чем получили. Либо ошибка ввода, либо возврат по
            # оплате, которой нет в журнале. Молчать нельзя: деньги ушли.
            return True
        return False


def _amount(value, field_name: str = "amount") -> Decimal:
    """Денежная величина. Отклоняет float, мусор, ноль, минус и третий знак."""
    if isinstance(value, float):
        # Запрет намеренный: 0.1 + 0.2 в float не равно 0.3, и такая ошибка в
        # деньгах не обнаруживается до сверки с клиентом.
        raise DomainError(f"{field_name} must be Decimal or string, not float")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise DomainError(f"{field_name} is required")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise DomainError(f"{field_name} must be a decimal number") from exc
    if not amount.is_finite():
        raise DomainError(f"{field_name} must be a finite number")
    if amount <= 0:
        raise DomainError(f"{field_name} must be greater than zero")
    if amount.as_tuple().exponent < -2:
        raise DomainError(f"{field_name} cannot have more than two decimal places")
    if amount >= MAX_AMOUNT:
        raise DomainError(f"{field_name} is out of range")
    return amount.quantize(CENT)


def _currency(value, field_name: str = "currency") -> str:
    code = str(value or "").strip().upper()
    if len(code) != 3 or not code.isalpha() or not code.isascii():
        # isascii обязателен: «КГС» кириллицей проходил как валюта, но не равнялся
        # «KGS», и платёж молча уходил в непосчитанные.
        raise DomainError(f"{field_name} must be a three-letter code")
    return code


def _rate(value) -> Decimal:
    if isinstance(value, float):
        raise DomainError("fx_rate must be Decimal or string, not float")
    try:
        rate = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise DomainError("fx_rate must be a decimal number") from exc
    if not rate.is_finite() or rate <= 0:
        raise DomainError("fx_rate must be a positive finite number")
    if rate >= Decimal("10") ** 12:
        # Диапазон проверяем ДО умножения: иначе 1e30 ронял сам Decimal
        # (InvalidOperation) вместо понятного доменного отказа.
        raise DomainError("fx_rate is out of range")
    if rate.as_tuple().exponent < -6:
        # Колонка Numeric(18,6) округлит седьмой знак, и зачёт разойдётся с курсом,
        # по которому его посчитали.
        raise DomainError("fx_rate cannot have more than six decimal places")
    return rate.quantize(Decimal("0.000001"))


async def _case_for_write(session: AsyncSession, case_id: int, by: Actor, *,
                          financial: bool = False) -> ServiceCase:
    """Услуга под запись денег: права проверяются до любых данных.

    `financial=True` — для возвратов и исправлений. По ТЗ (MONEY-05, раздел 4)
    это полномочие руководителя с причиной и аудитом, и до решения DEC-11 право
    закрыто всем, кроме полного администратора: `can_correct_money`. Обычную
    оплату своего клиента вносит владелец услуги.
    """
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "record money")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    if financial:
        require(can_correct_money(by, direction=product.direction if product else None),
                "correct money")
    else:
        require(can_advance_case(by, direction=product.direction if product else None,
                                 owner_login=case.owner_login), "record money")
    if not str(by.manager_id or "").strip():
        raise PermissionDenied("not allowed: record money")
    return case


def _same_money(row: ServicePayment, *, case_id: int, kind: str, amount: Decimal,
                currency: str, fx_rate, corrects_id: int | None) -> None:
    """Повтор с тем же ключом, но другими данными — конфликт, а не повтор.

    Сравниваются ВСЕ значащие поля, включая курс и ссылку на исправляемую строку:
    иначе тот же ключ с курсом 90 вместо 89 молча возвращал строку с прежним
    курсом, и менеджер считал, что провёл платёж по новому.
    """
    differs = [name for name, stored, asked in (
        ("case", row.case_id, case_id), ("kind", row.kind, kind),
        ("amount", row.amount, amount), ("currency", row.currency, currency),
        ("fx_rate", row.fx_rate, fx_rate), ("corrects", row.corrects_id, corrects_id),
    ) if stored != asked]
    if differs:
        raise DomainError("idempotency key already used with different money data: "
                          + ", ".join(differs))


async def _record(session: AsyncSession, case_id: int, *, kind: str, amount,
                  currency, by: Actor, idempotency_key: str, fx_rate=None,
                  reason: str = "", corrects_id: int | None = None,
                  settles_id: int | None = None,
                  expected_revision: int | None = None,
                  financial: bool = False) -> ServicePayment:
    """Общая запись строки журнала. Идемпотентна по ключу (AC-05)."""
    if kind not in KINDS:
        raise DomainError(f"unknown money kind {kind!r}")
    case = await _case_for_write(session, case_id, by, financial=financial)
    key = str(idempotency_key or "").strip()
    if not key or len(key) > 128:
        # Ключ обязателен: без него повторная отправка формы начисляет вторую
        # оплату, и клиент оказывается должен меньше, чем на самом деле (AC-05).
        raise DomainError("idempotency key must contain 1..128 characters")
    value = _amount(amount)
    code = _currency(currency)
    rate = _rate_for(value, code, case, fx_rate)
    rate_to = str(case.currency or "").strip().upper() if rate is not None else None

    existing = await session.scalar(
        select(ServicePayment).where(ServicePayment.idempotency_key == key))
    if existing is not None:
        # Повтор идемпотентен и проверяется ДО ревизии: иначе повторная отправка
        # того же запроса после успешной записи получала бы конфликт версии
        # вместо прежнего ответа.
        await _visible(session, existing, by)
        _same_money(existing, case_id=case_id, kind=kind, amount=value,
                    currency=code, fx_rate=rate, corrects_id=corrects_id)
        return existing

    if expected_revision is not None and case.revision != expected_revision:
        # Явный конфликт версии, а не тихая перезапись: иначе одновременное
        # исправление суммы и внесение оплаты теряют одну из двух записей (AC-05).
        raise DomainError("revision conflict: service case changed concurrently")

    row = ServicePayment(case_id=case.id, kind=kind, amount=value, currency=code,
                         fx_rate=rate, fx_to=rate_to, idempotency_key=key,
                         corrects_id=corrects_id, settles_id=settles_id,
                         reason=str(reason or "")[:2000], recorded_by=by.manager_id)
    savepoint = await session.begin_nested()
    try:
        session.add(row)
        await session.flush()
        session.add(ServiceEvent(
            case_id=case.id, event_type="money_" + kind, actor=by.manager_id,
            to_stage=case.stage, reason=str(reason or ""),
            payload={"amount": str(value), "currency": code,
                     "fx_rate": str(rate) if rate is not None else None,
                     "fx_to": rate_to,
                     "payment_id": row.id, "corrects_id": corrects_id,
                     "settles_id": settles_id}))
        await session.flush()
    except IntegrityError as exc:
        await savepoint.rollback()
        twin = await session.scalar(
            select(ServicePayment).where(ServicePayment.idempotency_key == key))
        if twin is not None:
            # Гонка по ключу: отдаём существующую строку, но только убедившись,
            # что это тот же запрос. Иначе параллельный вызов с другой суммой
            # получил бы «успех» с чужой записью.
            await _visible(session, twin, by)
            _same_money(twin, case_id=case_id, kind=kind, amount=value,
                        currency=code, fx_rate=rate, corrects_id=corrects_id)
            return twin
        if corrects_id is not None:
            # Уникальность `corrects_id` держит база: вторая поправка к той же
            # строке не проходит, иначе обе суммировались бы.
            raise DomainError("this entry is already corrected") from exc
        raise DomainError("money conflict; retry") from exc
    except StaleDataError as exc:
        await savepoint.rollback()
        raise DomainError("revision conflict: service case changed concurrently") from exc
    except BaseException:
        await savepoint.rollback()
        raise
    else:
        await savepoint.commit()
    return row


def _rate_for(value: Decimal, code: str, case: ServiceCase, fx_rate) -> Decimal | None:
    """Проверить курс и привести к хранимой точности. Зачёт здесь НЕ считается."""
    contract_currency = str(case.currency or "").strip().upper()
    if fx_rate is None:
        return None
    if not contract_currency:
        raise DomainError("fx_rate is meaningless until the contract has a currency")
    if code == contract_currency:
        raise DomainError("fx_rate must not be given for the contract currency")
    rate = _rate(fx_rate)
    credited = (value * rate).quantize(CENT)
    if credited <= 0:
        # Курс настолько мал, что платёж зачёлся бы нулём — это не зачёт, а потеря.
        raise DomainError("fx_rate is too small: the payment would credit nothing")
    if credited >= MAX_AMOUNT:
        raise DomainError("fx_rate is too large: the credited amount is out of range")
    return rate


async def _visible(session: AsyncSession, row: ServicePayment, by: Actor) -> None:
    """Право видеть найденную по ключу строку: ключ не пропуск к чужим деньгам."""
    case = await session.get(ServiceCase, row.case_id)
    product = await session.get(Product, case.product_id) if case else None
    require(can_view_case(by, direction=product.direction if product else None,
                          owner_login=case.owner_login if case else None),
            "record money")


async def record_payment(session: AsyncSession, case_id: int, *, amount, currency,
                         by: Actor, idempotency_key: str, fx_rate=None,
                         reason: str = "",
                         expected_revision: int | None = None) -> ServicePayment:
    """Клиент внёс деньги. Частичная оплата — обычный случай (AC-02)."""
    return await _record(session, case_id, kind=PAYMENT, amount=amount,
                         currency=currency, by=by, idempotency_key=idempotency_key,
                         fx_rate=fx_rate, reason=reason,
                         expected_revision=expected_revision)


async def record_refund_due(session: AsyncSession, case_id: int, *, amount, currency,
                            by: Actor, idempotency_key: str, reason: str = "",
                            expected_revision: int | None = None) -> ServicePayment:
    """Решение вернуть деньги принято, перевода ещё не было (AC-04).

    Намеренно не принимает курс: обязательство фиксируется в той валюте, в которой
    возникло, и в остаток не зачитывается — деньги пока у компании.
    """
    return await _record(session, case_id, financial=True, kind=REFUND_DUE, amount=amount,
                         currency=currency, by=by, idempotency_key=idempotency_key,
                         reason=reason, expected_revision=expected_revision)


async def correct_entry(session: AsyncSession, case_id: int, *, corrects_id: int,
                        amount, currency, by: Actor, idempotency_key: str,
                        reason: str, fx_rate=None) -> ServicePayment:
    """Исправление ранее записанной строки — новой строкой, с причиной.

    Правка на месте запрещена моделью: журнал денег append-only, иначе сумма
    меняется бесследно. Причина обязательна — исправление денег без объяснения
    неотличимо от ошибки.
    """
    # Право проверяем ПЕРВЫМ, до чтения цели. Иначе по разнице ответов («нет прав»
    # против «нет такой строки») чужой менеджер перебором узнаёт, какие платежи
    # принадлежат какой услуге.
    await _case_for_write(session, case_id, by, financial=True)
    if not str(reason or "").strip():
        raise DomainError("a correction requires a reason")
    target = await session.get(ServicePayment, corrects_id)
    if target is None or target.case_id != case_id:
        raise DomainError("correction must reference a payment of the same service case")
    return await _record(session, case_id, financial=True, kind=CORRECTION, amount=amount,
                         currency=currency, by=by, idempotency_key=idempotency_key,
                         fx_rate=fx_rate, reason=reason, corrects_id=corrects_id)


async def _ledger(session: AsyncSession, case_id: int) -> list[ServicePayment]:
    """Строки журнала по услуге, в устойчивом порядке."""
    return list(await session.scalars(
        select(ServicePayment).where(ServicePayment.case_id == case_id)
        .order_by(ServicePayment.id)))


async def correct_contract_amount(session: AsyncSession, case_id: int, *, amount,
                                  currency, by: Actor, reason: str,
                                  expected_revision: int | None = None) -> ServiceCase:
    """Исправить цену договора — с правом, причиной и событием.

    До этой операции сумма договора менялась прямым присваиванием: без прав, без
    причины и без следа в истории. Поскольку остаток считается от неё, такая
    правка ретроактивно переписывала все прошлые расчёты, и сверить отчёт за
    прошлый месяц было нечем.

    Смена ВАЛЮТЫ договора запрещена, если по услуге уже есть зачтённые платежи:
    их курс давался к прежней валюте, и после смены они либо выпали бы из
    остатка, либо зачлись бы по чужому курсу. Нужна другая валюта — сначала
    аннулируйте платежи, это осознанное действие, а не побочный эффект.
    """
    if not str(reason or "").strip():
        raise DomainError("correcting the contract amount requires a reason")
    case = await _case_for_write(session, case_id, by, financial=True)
    if expected_revision is not None and case.revision != expected_revision:
        raise DomainError("revision conflict: service case changed concurrently")

    new_amount = _amount(amount, "contract amount")
    new_currency = _currency(currency, "contract currency")
    previous_amount = case.agreed_amount
    previous_currency = str(case.currency or "").strip().upper()

    if previous_currency and new_currency != previous_currency:
        credited_rows = [row for row in await _ledger(session, case_id)
                         if _credit_of(row, previous_currency) is not None]
        if credited_rows:
            raise DomainError(
                "cannot change the contract currency while credited payments exist; "
                "void them first")

    object.__setattr__(case, "_money_correction_in_progress", True)
    try:
        case.agreed_amount = new_amount
        case.currency = new_currency
    finally:
        object.__setattr__(case, "_money_correction_in_progress", False)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="contract_amount_corrected",
        actor=by.manager_id, to_stage=case.stage, reason=str(reason),
        payload={"amount": str(new_amount), "currency": new_currency,
                 "previous_amount": str(previous_amount) if previous_amount is not None else None,
                 "previous_currency": previous_currency or None,
                 "revision": case.revision}))
    await session.flush()
    return case


async def void_entry(session: AsyncSession, case_id: int, *, voids_id: int,
                     by: Actor, reason: str,
                     idempotency_key: str) -> ServicePayment:
    """Аннулировать ошибочную запись: её не было.

    Без этого единственным способом убрать оплату, которой не приходило, был
    `refund_paid` — то есть запись «деньги вернули клиенту», хотя их не получали.
    Отчёт при этом становился ложным дважды. Аннулирование просто исключает
    строку из расчёта и говорит, почему.

    Сумма в аннулировании повторяет сумму цели: ограничение `amount > 0` в базе
    остаётся, а что именно аннулировано — видно без обращения к цели.
    """
    if not str(reason or "").strip():
        raise DomainError("voiding an entry requires a reason")
    await _case_for_write(session, case_id, by, financial=True)
    target = await session.get(ServicePayment, voids_id)
    if target is None or target.case_id != case_id:
        raise DomainError("void must reference a payment of the same service case")
    if target.kind == VOID:
        raise DomainError("a void cannot be voided; it is already annulled")
    return await _record(session, case_id, financial=True, kind=VOID,
                         amount=target.amount, currency=target.currency,
                         by=by, idempotency_key=idempotency_key, reason=reason,
                         corrects_id=voids_id)


async def record_refund_paid(session: AsyncSession, case_id: int, *, amount, currency,
                             by: Actor, idempotency_key: str, fx_rate=None,
                             reason: str = "", settles_id: int | None = None,
                             expected_revision: int | None = None) -> ServicePayment:
    """Деньги фактически ушли клиенту.

    `settles_id` указывает на обязательство (`refund_due`), которое этот перевод
    закрывает. Без него обязательство оставалось в отчёте навсегда: после
    настоящего возврата услуга одновременно показывала «вернули» и «обязаны
    вернуть», а флаг «нужен человек» превращался в постоянный шум.
    """
    if settles_id is not None:
        obligation = await session.get(ServicePayment, settles_id)
        if obligation is None or obligation.case_id != case_id:
            raise DomainError("settles_id must reference an obligation of the same case")
        if obligation.kind != REFUND_DUE:
            raise DomainError("only a refund obligation can be settled")
    return await _record(session, case_id, financial=True, kind=REFUND_PAID,
                         amount=amount, currency=currency, by=by,
                         idempotency_key=idempotency_key, fx_rate=fx_rate,
                         reason=reason, settles_id=settles_id,
                         expected_revision=expected_revision)

def _credit_of(row: ServicePayment, contract_currency: str) -> Decimal | None:
    """Сколько строка значит в валюте договора. None — зачесть нельзя.

    Считается ПРИ РАСЧЁТЕ, а не при записи. Хранимый зачёт был ошибкой: он
    фиксировался в момент платежа, и предоплата, внесённая до того как в договоре
    появилась сумма, навсегда выпадала из остатка — менеджер называл клиенту
    полную сумму вместо остатка. Теперь валюта договора может появиться позже,
    и прошлые платежи зачтутся сами.
    """
    if not contract_currency:
        return None
    if row.currency == contract_currency:
        return row.amount
    if row.fx_rate is None:
        # Чужая валюта без курса не зачитывается (AC-06): ложный остаток хуже
        # непосчитанного платежа — по нему скажут клиенту неверную сумму.
        return None
    if str(row.fx_to or "").strip().upper() != contract_currency:
        # Курс дан к другой валюте, чем валюта договора сейчас. Применять его
        # нельзя: 100 USD по курсу 89 к сомам — это не 8900 евро.
        return None
    credited = (row.amount * row.fx_rate).quantize(CENT)
    if credited <= 0 or credited >= MAX_AMOUNT:
        return None
    return credited


async def balance_of(session: AsyncSession, case_id: int, *, by: Actor) -> Balance:
    """Посчитать остаток заново по журналу. Хранимого итога нет и не будет.

    Исправленные строки исключаются: строка, на которую ссылается `correction`,
    в расчёт не идёт — иначе исправление удваивало бы сумму вместо замены.
    Исправление считается тем же видом, что исправляемая строка: поправка к
    возврату остаётся возвратом, а не превращается в приход денег.
    """
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "view money")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_view_case(by, direction=product.direction if product else None,
                          owner_login=case.owner_login), "view money")

    rows = await _ledger(session, case_id)
    return balance_from_rows(case, rows)


def balance_from_rows(case, rows) -> Balance:
    """Same ledger arithmetic for a current case or an immutable evidence pin."""
    by_id = {row.id: row for row in rows}
    # Аннулированные строки выпадают вместе с самим аннулированием: записи не было.
    voided = {row.corrects_id for row in rows if row.kind == VOID}
    corrected = {row.corrects_id for row in rows
                 if row.corrects_id is not None and row.kind == CORRECTION}
    # Обязательства, закрытые фактическим возвратом, в долг не идут.
    settled = {row.settles_id for row in rows if row.settles_id is not None}
    contract_currency = str(case.currency or "").strip().upper()

    paid = refunded = due = Decimal("0.00")
    broken: list[int] = []
    unconverted: dict[str, Decimal] = {}
    foreign_refund_due: dict[str, Decimal] = {}
    foreign_refunded: dict[str, Decimal] = {}
    for row in rows:
        if row.kind == VOID or row.id in voided:
            continue                      # аннулировано: записи не было
        if row.id in corrected:
            continue                      # заменено исправлением
        if row.id in settled:
            continue                      # обязательство закрыто переводом
        kind = _effective_kind(row, by_id)
        if kind is None:
            broken.append(row.id)
            continue
        credited = _credit_of(row, contract_currency)
        if credited is None:
            # Не зачитывается в валюту договора — показываем раздельно по смыслу,
            # чтобы обязательство не гасило платёж и сигнал не терялся.
            bucket = {PAYMENT: unconverted, REFUND_DUE: foreign_refund_due,
                      REFUND_PAID: foreign_refunded}.get(kind)
            if bucket is not None:
                bucket[row.currency] = bucket.get(row.currency, Decimal("0.00")) + row.amount
            continue
        if kind == PAYMENT:
            paid += credited
        elif kind == REFUND_PAID:
            refunded += credited
        elif kind == REFUND_DUE:
            due += credited

    return Balance(
        currency=contract_currency or None, agreed=case.agreed_amount,
        paid=paid.quantize(CENT), refunded=refunded.quantize(CENT),
        refund_due=due.quantize(CENT),
        unconverted={k: v.quantize(CENT) for k, v in unconverted.items()},
        foreign_refund_due={k: v.quantize(CENT) for k, v in foreign_refund_due.items()},
        foreign_refunded={k: v.quantize(CENT) for k, v in foreign_refunded.items()},
        broken_entries=tuple(broken))


def _effective_kind(row: ServicePayment, by_id: dict) -> str | None:
    """Вид строки для расчёта: исправление наследует вид исправляемой строки.

    Иначе поправка к возврату засчитывалась как оплата: исходный возврат
    исключался, приход рос, остаток занижался — то есть исправление опечатки в
    возврате превращало его в деньги клиента.
    """
    seen = {row.id}
    current = row
    while current.kind == CORRECTION and current.corrects_id is not None:
        if current.corrects_id in seen:
            # Круговая ссылка: возможна только правкой базы мимо домена. Вид
            # неопределим, и вместо тихого пропуска строка уходит в «непонятные».
            return None
        seen.add(current.corrects_id)
        target = by_id.get(current.corrects_id)
        if target is None:
            return None                   # исправление без цели — тоже аномалия
        current = target
    return current.kind
