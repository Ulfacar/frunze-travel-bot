"""B3 — продажа = полная оплата по договору (решение Алана 14.10, ТЗ §20). CRITICAL.

Правило: зачтённые оплаты минус возвраты в валюте договора ≥ сумме договора
(`service_money.is_fully_paid`). Частичная оплата — не продажа. Переплата — отдельно.
Валюта без курса — не считается. Тогда у диалога(ов) этого клиента в направлении дела
ставится `outcome=won`, с основанием в журнале: дело, сумма, валюта.

Как устроено и почему именно так.

* **Считается после записи денег, не вместо неё.** Оплата уже закоммичена
  (`workday._write`); здесь только вывод из баланса. Любой сбой этого шага — предупреждение
  в лог и ответ `error`, но оплата менеджера не теряется. Следующая денежная операция по
  делу пересчитает снова: якорь идемпотентности — событие `sale_full_payment` в домене.
* **Один `sale_full_payment` на дело в журнале панели.** Его считает
  `scripts/pilot_daily_summary.py`; по диалогам — отдельные записи `sale_fp_dialog`.
* **Диалог ищется так же, как при подписании договора**: `contracts._identity(conv)` даёт
  ту же нормализованную идентичность, что легла в `ContactIdentity`. Прямой связи
  «контакт → диалоги» в данных нет, и заводить колонку ради неё (миграция) здесь не стали.
* **Финал не перезатирается.** `store.claim_outcome` — атомарная защёлка: если менеджер
  уже поставил `won`/`lost`, пишем `sale_fp_conflict` и ничего не меняем.
* **S6 (Алан, 15.10): возврат после продажи `won` не снимает.** Пометка в домене
  (`sale_reversal_flag`) и в журнале (`sale_fp_reversal`), баланс и так подсвечен.
* **Bitrix не трогаем.** Это замена CONVERTED, а не ещё один писатель в портал.

Флаг `sale_by_full_payment_enabled`, дефолт OFF: без него функция возвращает `off`
и ничего не читает.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.core import flags, live_authz
from app.domain.models import ContactIdentity, DomainError, Product, ServiceCase
from app.domain.service_money import (
    SALE_EVENT, balance_of, is_fully_paid, lock_case, record_sale, record_sale_reversal,
    sale_events,
)

log = logging.getLogger("sale_by_payment")

FLAG = "sale_by_full_payment_enabled"
AUDIT_SALE = "sale_full_payment"      # ровно один на дело; его считает pilot_daily_summary
AUDIT_DIALOG = "sale_fp_dialog"       # исход диалога поставлен
AUDIT_CONFLICT = "sale_fp_conflict"   # у диалога уже стоял финал — не трогали
AUDIT_REVERSAL = "sale_fp_reversal"   # после продажи оплаты перестали покрывать договор

RESULTS = ("off", "unsigned", "not_full", "already", "won", "no_dialog", "conflict",
           "reversal", "error")


async def enabled() -> bool:
    """Флаг. Сбой чтения флагов = OFF: без него нельзя ни ошибочно включить, ни показать
    менеджеру «проверка продажи не удалась» на пустом месте."""
    try:
        return bool(await flags.get_flag(FLAG, settings.sale_by_full_payment_enabled))
    except Exception:  # noqa: BLE001
        log.warning("sale by payment: flag store unavailable, treating as off", exc_info=False)
        return False


async def evaluate_after_money_write(case_id: int, actor: Any, manager_login: str, *,
                                     sessionmaker, store=None) -> str:
    """Пересчитать баланс дела после денежной операции и вывести продажу.

    Возвращает одно из `RESULTS`. Никогда не бросает: оплата уже записана, и ответ
    менеджеру об оплате не должен зависеть от этого шага.
    """
    if not await enabled():
        return "off"
    try:
        if store is None:
            from app.integrations.panel.store import get_conversation_store
            store = get_conversation_store()
        return await _evaluate(case_id, actor, str(manager_login or ""),
                               sessionmaker=sessionmaker, store=store)
    except Exception:  # noqa: BLE001 — оплата сохранена, продажа досчитается на следующем шаге
        log.warning("sale by payment: evaluation failed case=%s", case_id, exc_info=True)
        return "error"


async def _evaluate(case_id: int, actor: Any, login: str, *, sessionmaker, store) -> str:
    async with sessionmaker() as session:
        # Сначала блокировка дела, потом баланс: иначе параллельный возврат успевает
        # между чтением «полностью оплачено» и записью продажи (ревью 15.10, п.2).
        # Блокировка держится до коммита, и запись о продаже в журнал панели делается
        # ПОД ней: две одновременные операции по одному делу не запишут её дважды
        # (ревью 15.10 р.2). Упадёт журнал — событие в домене откатится вместе с ним.
        case = await lock_case(session, case_id)
        if case.signed_at is None:
            # Предварительное дело без подписи: деньги в нём бывают, продажи — нет
            # (FLOW-02: отправленный договор ≠ подписанный; аудит 15.10, зам. 2).
            await session.commit()
            return "unsigned"
        balance = await balance_of(session, case_id, by=actor)
        product = await session.get(Product, case.product_id)
        direction = product.direction if product else ""
        identities = await _identities(session, case.contact_id)
        dialogs = await _dialogs_for(store, identities, direction)
        primary = dialogs[0].user_id if dialogs else ""
        if not is_fully_paid(balance):
            event = await record_sale_reversal(session, case_id, by=actor, balance=balance)
            if event is None:
                await session.commit()
                return "not_full"
            for conv in dialogs or [None]:
                await store.add_audit(login, AUDIT_REVERSAL,
                                      conv.user_id if conv is not None else "",
                                      f"case={case_id} после продажи оплаты не покрывают договор")
            await session.commit()
            log.warning("sale by payment: reversal after sale case=%s dialogs=%d",
                        case_id, len(dialogs))
            return "reversal"

        event = await record_sale(session, case_id, by=actor, balance=balance,
                                  dialogs=tuple(c.user_id for c in dialogs))
        if event is None:
            # Досмотр: только диалоги, найденные В МОМЕНТ продажи. Новые обращения клиента
            # после неё — отдельные лиды, им `won` ставить нельзя (аудит 15.10, H1).
            sale = next(e for e in await sale_events(session, case_id)
                        if e.event_type == SALE_EVENT)
            known = set(sale.payload.get("dialogs") or [])
            dialogs = [c for c in dialogs if c.user_id in known]
        sale_detail = f"case={case_id} {balance.agreed} {balance.currency}"
        # Ровно одна запись о продаже на дело — её считает отчёт пилота. Журнал панели
        # живёт в другой базе и коммитится сам, поэтому проверка «уже есть» стоит перед
        # КАЖДОЙ записью, а не только в ветке досмотра: иначе упавший после журнала коммит
        # домена даёт вторую строку на следующем проходе (аудит 15.10, блокер B1). Пишем
        # до защёлок: упадёт панель на защёлке — продажа уже в журнале, диалог дозакроется.
        if not await store.audit_exists(AUDIT_SALE, f"case={case_id} "):
            await store.add_audit(login, AUDIT_SALE, primary, sale_detail)
        await session.commit()

    if event is None:
        # Диалоги досматриваем и здесь: если защёлка в прошлый раз сорвалась, исход ещё
        # не стоит. Только те, кому исход по этому делу ещё не ставили (есть запись
        # `sale_fp_dialog` — человек мог с тех пор поменять исход, не трогаем). Защёлка
        # идемпотентна; конфликты молчат (о них сказали в первый раз).
        pending = [c for c in dialogs
                   if not await store.audit_exists(AUDIT_DIALOG, f"case={case_id} {c.user_id}")]
        claimed = await _claim(store, pending, login, case_id, balance, audit_conflicts=False)
        return "won" if claimed else "already"

    claimed = await _claim(store, dialogs, login, case_id, balance, audit_conflicts=True)
    conflicts = [c.user_id for c in dialogs if c.user_id not in claimed]
    if claimed:
        log.info("sale by payment: won case=%s dialogs=%d", case_id, len(claimed))
        return "won"
    if conflicts:
        return "conflict"
    log.warning("sale by payment: no dialog for case=%s direction=%s", case_id, direction)
    return "no_dialog"


async def _claim(store, dialogs: list, login: str, case_id: int, balance,
                 *, audit_conflicts: bool) -> list[str]:
    """Поставить `won` каждому диалогу через атомарную защёлку. Возвращает, кому поставили."""
    claimed: list[str] = []
    for conv in dialogs:
        if await store.claim_outcome(conv.user_id, "won"):
            # Сумма — как у вечерней ссылки: отчёты читают `sale_amount`. Пишем ПОСЛЕ
            # защёлки, чтобы чужую сумму на уже отмеченном диалоге не переписать.
            await store.update_meta(conv.user_id, sale_amount=float(balance.agreed),
                                    sale_currency=str(balance.currency or ""))
            await store.add_audit(login, AUDIT_DIALOG, conv.user_id,
                                  f"case={case_id} {conv.user_id}")
            claimed.append(conv.user_id)
        elif audit_conflicts:
            await store.add_audit(login, AUDIT_CONFLICT, conv.user_id,
                                  f"case={case_id} у диалога уже стоял финальный исход")
            log.warning("sale by payment: dialog already final, outcome kept case=%s", case_id)
    return claimed


async def _identities(session, contact_id: int) -> list[tuple[str, str]]:
    rows = await session.scalars(select(ContactIdentity).where(
        ContactIdentity.contact_id == contact_id, ContactIdentity.provider_scope == ""))
    return [(row.identity_type, row.normalized_value) for row in rows]


def _direction(conv: Any) -> str:
    """То же правило, что `router._authz_direction`: воронка, иначе сценарий бота."""
    funnel = str(getattr(conv, "funnel", "") or "").strip()
    if funnel in ("visa", "tours"):
        return funnel
    bot_id = str(getattr(conv, "bot_id", "") or "").strip()
    if not bot_id:
        bot_id = str(getattr(conv, "user_id", "") or "").partition(":")[0]
    return live_authz.direction_for_bot(bot_id)


async def _dialogs_for(store, identities: list[tuple[str, str]], direction: str) -> list:
    """Диалоги клиента в направлении дела. Идентичность считается как при подписании."""
    if not identities or not direction:
        return []
    # Ленивый импорт: модуль договоров регистрирует маршруты на админском роутере.
    from app.admin.contracts import _identity
    wanted = set(identities)
    found = []
    for conv in await store.all_conversations_light():
        if _direction(conv) != direction:
            continue
        try:
            identity = _identity(conv)
        except DomainError:
            continue
        if identity in wanted:
            found.append(conv)
    return found
