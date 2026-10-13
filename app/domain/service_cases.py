"""E1-01: операции используют транзакцию вызывающего кода и никогда не делают commit.

JSON процесса: stages = [{"code": "…", "name": "…"}],
transitions = {"код этапа": ["код допустимого следующего этапа", …]}.
Реестр и туровый процесс создаются только явным вызовом seed_products.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.config import settings
from app.domain.permissions import Actor
from app.domain.service_authz import (
    SYSTEM_ACTOR, PermissionDenied, can_advance_case, can_manage_products,
    can_open_case, can_reassign_case, can_view_case, require,
)
from app.domain.models import (
    CalendarTask,
    DIRECTIONS, Contact, DomainError, Product, Request, ServiceCase, ServiceEvent,
    WorkflowVersion, _now,
)


INITIAL_PRODUCTS = (
    ("tour_package", "Пакетный тур", "tours"),
    ("air_ticket", "Авиабилет", "tickets"),
    ("hotel_booking", "Бронь отеля", "tours"),
    ("visa_usa", "Виза США", "visa"),
    ("visa_schengen", "Шенген/Европа", "visa"),
    ("visa_china", "Китай", "visa"),
    ("visa_korea", "Корея", "visa"),
    ("visa_japan", "Япония", "visa"),
    ("visa_italy", "Италия", "visa"),
)
# `requires` — факты, без которых переход НА этот этап не принимается (FLOW-03:
# «сервер проверяет обязательные факты», кнопка «Бронь подтверждена» запрашивает
# номер и дату). `first_task` на первом этапе — начальная задача из AC-01.
# Смещение Бишкека. Дублируется из `app.core.calendar_brief`, чтобы доменный слой не
# зависел от операционного: смысл один и тот же — календарный день местный, не UTC.
BISHKEK_UTC_OFFSET = 6

TOUR_STAGES = [
    {"code": "TOUR-01", "name": "Договор",
     "first_task": {"kind": "call", "comment": "Забронировать тур у оператора",
                    "due_in_days": 1}},
    {"code": "TOUR-02", "name": "Бронь отправлена"},
    {"code": "TOUR-03", "name": "Бронь подтверждена",
     "requires": ["booking_reference", "confirmed_at"]},
    {"code": "TOUR-04", "name": "Выкуп и расчёт"},
    {"code": "TOUR-05", "name": "Документы переданы"},
    {"code": "TOUR-06", "name": "Поездка"},
    {"code": "TOUR-07", "name": "Отзыв и завершение"},
]
TOUR_TRANSITIONS = {
    "TOUR-01": ["TOUR-02"],
    "TOUR-02": ["TOUR-03", "TOUR-01"],
    "TOUR-03": ["TOUR-04"],
    "TOUR-04": ["TOUR-05"],
    "TOUR-05": ["TOUR-06"],
    "TOUR-06": ["TOUR-07"],
    "TOUR-07": [],
}


def _required_text(value: str, field: str, limit: int) -> str:
    """Обязательный текст с нормализацией краёв.

    Длина считается ПОСЛЕ обрезки пробелов: ограничение относится к содержимому, а
    не к случайному пробелу из буфера обмена. Прежний порядок отклонял ключ из 128
    значащих символов только потому, что при копировании прилип пробел.
    """
    if not isinstance(value, str):
        raise DomainError(f"{field} must contain 1..{limit} characters")
    value = value.strip()
    if not value or len(value) > limit:
        raise DomainError(f"{field} must contain 1..{limit} characters")
    return value


def _validate_workflow(stages: list[dict], transitions: dict[str, list[str]]) -> None:
    if not isinstance(stages, list) or not stages:
        raise DomainError("workflow requires a non-empty list of stages")
    codes = set()
    for stage in stages:
        # Код и название обязательны; `requires` и `first_task` — необязательные
        # описания процесса (обязательные факты перехода и начальная задача).
        # Список ключей закрытый: опечатка в имени поля должна падать на публикации
        # версии, а не превращаться в молча проигнорированное правило.
        allowed = {"code", "name", "requires", "first_task"}
        if (not isinstance(stage, dict) or not {"code", "name"} <= set(stage)
                or not set(stage) <= allowed):
            raise DomainError("each stage requires code and name")
        code = _required_text(stage["code"], "stage code", 64)
        _required_text(stage["name"], "stage name", 255)
        requires = stage.get("requires")
        if requires is not None and (not isinstance(requires, list)
                                     or not all(isinstance(x, str) and x.strip() for x in requires)):
            raise DomainError("stage requires must be a list of fact names")
        first_task = stage.get("first_task")
        if first_task is not None:
            # Содержимое задачи проверяется ЗДЕСЬ, при публикации версии, а не при
            # подписании договора. Иначе `due_in_days="abc"` публиковался молча, а
            # падал потом на живом договоре — то есть ошибка настройки процесса
            # ломала продажу, и чинить её приходилось бы в худший момент.
            if not isinstance(first_task, dict):
                raise DomainError("stage first_task must be an object")
            if not set(first_task) <= {"kind", "comment", "due_in_days"}:
                raise DomainError("stage first_task allows only kind, comment, due_in_days")
            kind = first_task.get("kind")
            if kind is not None and (not isinstance(kind, str) or not kind.strip()
                                     or len(kind.strip()) > 24):
                raise DomainError("first_task kind must be text of at most 24 characters")
            comment = first_task.get("comment")
            if comment is not None and not isinstance(comment, str):
                raise DomainError("first_task comment must be text")
            due = first_task.get("due_in_days")
            if due is not None and (isinstance(due, bool) or not isinstance(due, int)
                                    or not 0 <= due <= 365):
                raise DomainError("first_task due_in_days must be an integer of 0..365 days")
        if code != stage["code"] or code in codes:
            raise DomainError("stage codes must be unique and have no surrounding whitespace")
        codes.add(code)
    if not isinstance(transitions, dict):
        raise DomainError("transitions must map stage codes to lists of stage codes")
    for source, targets in transitions.items():
        if source not in codes or not isinstance(targets, list):
            raise DomainError("transitions must reference known stages")
        if any(not isinstance(target, str) or target not in codes for target in targets):
            raise DomainError("transitions must reference known stages")
        if len(targets) != len(set(targets)) or source in targets:
            raise DomainError("duplicate transitions and self-transitions are not allowed")


async def _product(session: AsyncSession, product_id: int) -> Product:
    # Публикация и открытие услуги согласованы с архивированием в PostgreSQL.
    product = await session.scalar(select(Product).where(Product.id == product_id)
                                   .with_for_update().execution_options(populate_existing=True))
    if product is None:
        raise DomainError(f"unknown product {product_id}")
    return product


async def create_product(session: AsyncSession, *, code: str, name: str,
                         direction: str, by: Actor) -> Product:
    # Право проверяем первым: отказ не должен зависеть от того, валидны ли данные,
    # иначе по разным сообщениям об ошибке можно изучать чужое направление.
    require(can_manage_products(by), "manage products")
    code = _required_text(code, "product code", 64)
    name = _required_text(name, "product name", 255)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", code):
        raise DomainError("product code must be stable lowercase Latin letters, digits or underscores")
    if direction not in DIRECTIONS:
        raise DomainError(f"unknown direction {direction!r}")
    if await session.scalar(select(Product.id).where(Product.code == code)) is not None:
        raise DomainError(f"product code {code!r} already exists")
    try:
        async with session.begin_nested():
            product = Product(code=code, name=name, direction=direction, active=True)
            session.add(product)
            await session.flush()
    except IntegrityError as exc:
        # Уникальность кода держит база, а не только проверка выше: между проверкой
        # и вставкой мог вклиниться другой запрос.
        raise DomainError(f"product code {code!r} already exists") from exc
    return product


def _audit_actor(by: Actor, claimed: str | None) -> str:
    """Автор события — всегда действующий актор, а не то, что передали параметром.

    Аудит нашёл подделку: параметр `actor` писался в историю как есть, и менеджер
    мог оставить запись от чужого имени. Исключение — системный актор: при переносе
    старых данных автор берётся из истории, и там стоят реальные люди.
    """
    if by.manager_id == SYSTEM_ACTOR.manager_id and claimed:
        return str(claimed).strip()[:64]
    if claimed and str(claimed).strip().lower() != by.manager_id:
        raise DomainError("event author must match the acting manager")
    return by.manager_id


async def _create_initial_tasks(session: AsyncSession, case: ServiceCase,
                                version: WorkflowVersion, *, direction: str,
                                by: Actor) -> int:
    """Начальные задачи после подписания договора (AC-01, FLOW-02).

    «Событие создаёт исполнение, начальный чек-лист и задачи ровно один раз» —
    поэтому задачи заводятся здесь, в той же транзакции, что и договор: если
    подписание откатится, задач тоже не останется.

    Что заводить, описано в самом процессе (`first_task` у первого этапа), а не
    зашито в код: у виз и билетов первый шаг другой, и переписывать функцию ради
    каждого продукта нельзя.

    Задача привязана к услуге (`service_case_id`): иначе она не переедет к новому
    владельцу при переназначении и не попадёт в карточку услуги.
    """
    stage = next((s for s in version.stages if s["code"] == case.stage), {})
    spec = stage.get("first_task")
    if not spec:
        return 0
    # Срок считается по календарю Бишкека, как и всё остальное в календаре задач
    # (`budget._bishkek_day`, `calendar_brief.BISHKEK_UTC_OFFSET`). В UTC задача,
    # заведённая после 18:00 местного времени, уезжала на сутки назад.
    due = (case.signed_at or _now()) + timedelta(days=int(spec.get("due_in_days", 1)))
    due_local = due.astimezone(timezone.utc) + timedelta(hours=BISHKEK_UTC_OFFSET)
    session.add(CalendarTask(
        contact_id=case.contact_id, request_id=case.request_id,
        # Нижний регистр — требование модели (`manager_id` = owner login, lowercased).
        # Логин сюда приходит уже нормализованным, но задача попадает в выборки
        # менеджера по точному совпадению, и полагаться на вызывающего здесь нельзя.
        manager_id=str(case.owner_login or "").strip().lower(), direction=direction,
        kind=str(spec.get("kind") or "call"),
        comment=str(spec.get("comment") or "")[:500],
        scheduled_date=due_local.date(), scheduled_at=due,
        created_by=by.manager_id,
        # Ссылка на услугу обязательна: без неё задача не переезжает к новому
        # владельцу при переназначении (AC-29) и не попадает в карточку услуги.
        # Поле появилось в E2-02, и этот вызов его не использовал — долг закрыт.
        service_case_id=case.id))
    return 1


async def _twin_for(session: AsyncSession, case: ServiceCase, by: Actor) -> ServiceCase:
    """Проверить доступ к НАЙДЕННОЙ по ключу услуге, прежде чем её отдать.

    Права в начале операции проверяются на запрошенный продукт, а по ключу может
    найтись услуга другого направления — тогда ключ становится пропуском к чужим
    данным. Проверяющая модель нашла именно это.
    """
    twin_product = await session.get(Product, case.product_id)
    # Именно can_view_case, а не can_open_case: право завести услугу в своём
    # направлении не означает право увидеть чужую. Иначе ключ открывал бы договор
    # коллеги по тому же направлению — с номером, суммой и клиентом.
    require(can_view_case(by, direction=twin_product.direction if twin_product else None,
                          owner_login=case.owner_login), "sign contract")
    return case


def _moment(value: datetime | None) -> datetime | None:
    """Момент времени для сравнения, независимо от того, как его вернула СУБД.

    SQLite отдаёт время без зоны, и прямое сравнение с tz-aware значением всегда
    давало «различие» — повтор с той же датой подписи считался конфликтом. Наивное
    значение из базы толкуем как UTC: именно в UTC оно туда и записано.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _assert_same_contract(case: ServiceCase, *, contact_id: int, product_id: int,
                          reference: str, amount, currency, owner_login: str = "",
                          unknown_reason: str = "", request_id: int | None = None,
                          signed_at: datetime | None = None) -> None:
    """Повтор с тем же ключом, но другими данными — конфликт, а не повтор.

    Сравниваются ВСЕ поля договора, а не только деньги. Сначала проверялись лишь
    контакт, продукт, номер, сумма и валюта — и повтор с другим владельцем, другой
    заявкой или другой причиной неизвестной суммы возвращал «успех», хотя
    применились старые данные. Это тот же обман вызывающего, что и опечатка в сумме.

    `signed_at` сверяется только когда передан явно: иначе повтор без даты сравнивал
    бы её с моментом первого вызова и конфликтовал всегда.
    """
    differs = [name for name, stored, asked in (
        ("contact", case.contact_id, contact_id),
        ("product", case.product_id, product_id),
        ("reference", case.contract_reference, reference),
        ("amount", case.agreed_amount, amount),
        ("currency", case.currency, currency),
        ("owner", (case.owner_login or "").strip().lower(),
         (owner_login or "").strip().lower()),
        ("amount_unknown_reason", case.amount_unknown_reason or "", unknown_reason or ""),
        ("request", case.request_id, request_id),
        ("signed_at", _moment(case.signed_at),
         _moment(signed_at) if signed_at is not None else _moment(case.signed_at)),
    ) if stored != asked]
    if differs:
        # Называем разошедшиеся ПОЛЯ, но не значения: в них сумма договора и клиент,
        # а текст ошибки может уйти в лог или дойти до чужих глаз.
        raise DomainError("idempotency key already used with different contract data: "
                          + ", ".join(differs))


def _fact_value(name: str, value):
    """Факт перехода приводится к записываемому в историю виду.

    Фильтр «непустая строка» пропускал `False` и `[]`: они превращались в "False"
    и "[]" и считались заполненными, то есть бронь подтверждалась без даты. Поэтому
    типы перечислены явно, а `datetime`/`date` приводятся к ISO — иначе JSON истории
    падал бы с StatementError вместо понятного отказа.
    """
    if isinstance(value, bool):
        raise DomainError(f"fact {name!r} must be text, a number or a date")
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return None
    raise DomainError(f"fact {name!r} must be text, a number or a date")


def _optional_text(value, field: str, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise DomainError(f"{field} must be text")
    value = value.strip()
    if len(value) > limit:
        raise DomainError(f"{field} must contain at most {limit} characters")
    return value


def _contract_amount(amount, currency: str | None, unknown_reason: str) -> Decimal | None:
    """Сумма договора либо явная причина её отсутствия (FLOW-02)."""
    if amount is None or (isinstance(amount, str) and not amount.strip()):
        if not unknown_reason:
            raise DomainError("either contract amount or a reason for it being unknown")
        return None
    if isinstance(amount, float):
        # float на деньгах — источник расхождений в копейку; просим Decimal или строку.
        raise DomainError("contract amount must be given as Decimal or string, not float")
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise DomainError("contract amount must be a decimal number") from exc
    if not value.is_finite():
        # NaN и бесконечность проходят Decimal(), но деньгами не являются.
        raise DomainError("contract amount must be a finite number")
    if unknown_reason:
        # Либо сумма, либо причина её отсутствия — не одновременно. Иначе в отчётах
        # по деньгам непонятно, что считать суммой договора. Решение 05.10.
        raise DomainError("contract amount and a reason for unknown amount are exclusive")
    if value < 0:
        raise DomainError("contract amount cannot be negative")
    if value == 0:
        # Нуль в сумме договора — почти всегда опечатка: бесплатных договоров нет,
        # визы идут по прайсу, туры вилкой. Если появится акция, предохранитель
        # снимается этой строкой. Решение 05.10.
        raise DomainError("contract amount must be greater than zero")
    if value.as_tuple().exponent < -2:
        # Колонка Numeric(14,2) молча округлит третий знак, и история разойдётся с базой.
        raise DomainError("contract amount cannot have more than two decimal places")
    if value >= Decimal("10") ** 12:
        raise DomainError("contract amount is out of range")
    if not currency:
        raise DomainError("contract amount requires a currency")
    # Одна форма записи для базы и для истории. Без этого в событии оставалось
    # «1E+2» или «-0», а в колонке Numeric(14,2) лежало «100.00» — одна и та же
    # сумма выглядела по-разному в договоре и в его истории.
    return value.quantize(Decimal("0.01")) + Decimal("0")


async def publish_version(session: AsyncSession, product_id: int, stages: list[dict],
                          transitions: dict[str, list[str]], published_by: str, *,
                          by: Actor, version_id: int | None = None) -> WorkflowVersion:
    """Опубликовать версию процесса продукта. Публикует только полный админ.

    Опубликованная версия неизменяема: подписанные услуги держатся за свою версию
    (AC-17), и правка этапов задним числом переписала бы историю их переходов.
    Новая версия становится текущей у продукта, старые услуги остаются на прежней.
    """
    require(can_manage_products(by), "publish workflow version")
    product = await _product(session, product_id)
    if not product.active:
        raise DomainError("cannot publish a workflow for an archived product")
    _validate_workflow(stages, transitions)
    if version_id is not None:
        # Опубликованную версию нельзя опубликовать повторно: подписанные услуги
        # держатся за неё, и правка задним числом переписала бы их историю (AC-17).
        existing = await session.get(WorkflowVersion, version_id)
        if existing is not None and existing.published_at is not None:
            raise DomainError(f"workflow version {version_id} is already published")
    published = _required_text(published_by, "published_by", 64)
    # Номер версии растёт по продукту: (product_id, version) уникальна, и по номеру
    # человек понимает, какая версия процесса старше, не сверяя даты.
    last = await session.scalar(select(func.max(WorkflowVersion.version))
                                .where(WorkflowVersion.product_id == product.id))
    version = WorkflowVersion(product_id=product.id, version=int(last or 0) + 1,
                              stages=stages, transitions=transitions,
                              published_by=published, published_at=_now())
    session.add(version)
    await session.flush()
    product.current_version_id = version.id
    await session.flush()
    return version


async def active_products(session: AsyncSession) -> list[Product]:
    """Продукты, доступные для новых услуг. Порядок устойчивый — по коду."""
    rows = await session.scalars(
        select(Product).where(Product.active.is_(True)).order_by(Product.code))
    return list(rows)


async def archive_product(session: AsyncSession, product_id: int, *,
                          by: Actor) -> Product:
    """Убрать продукт из выдачи. Архивирует только полный админ.

    Архивация не удаляет ни продукт, ни его версии, ни уже открытые услуги:
    по ним люди продолжают работать. Закрывается только вход для новых.
    """
    require(can_manage_products(by), "archive product")
    product = await _product(session, product_id)
    product.active = False
    await session.flush()
    return product


async def open_case(session: AsyncSession, *, contact_id: int, product_id: int,
                    owner_login: str, by: Actor,
                    request_id: int | None = None) -> ServiceCase:
    """Открыть услугу на первом этапе процесса продукта.

    Права проверяются ДО валидации данных: иначе по разным сообщениям об ошибке
    можно изучать чужое направление и существование объектов.
    """
    product = await session.get(Product, product_id)
    if product is None:
        require(by.is_full_admin, "open service case")
        raise DomainError(f"unknown product {product_id}")
    require(can_open_case(by, direction=product.direction), "open service case")
    if not product.active:
        raise DomainError("cannot open a service case for an archived product")
    if product.current_version_id is None:
        raise DomainError("product has no current published workflow version")
    version = await session.get(WorkflowVersion, product.current_version_id)
    if version is None or version.published_at is None:
        raise DomainError("product has no current published workflow version")
    owner = _required_text(owner_login, "owner_login", 64).lower()
    # Контакт проверяем сами: иначе наружу уходит IntegrityError от внешнего ключа
    # вместо понятного доменного отказа, и вызывающий не отличит «нет клиента» от
    # поломки базы.
    if await session.get(Contact, contact_id) is None:
        raise DomainError(f"unknown contact {contact_id}")
    if request_id is not None:
        # Заявка должна принадлежать ТОМУ ЖЕ клиенту и тому же направлению: иначе
        # услуга повиснет на чужом обращении, и отчёты свяжут разных людей.
        request = await session.get(Request, request_id)
        if (request is None or request.contact_id != contact_id
                or request.direction != product.direction):
            raise DomainError("request must belong to the same contact and direction")
    first_stage = version.stages[0]["code"]
    case = ServiceCase(contact_id=contact_id, product_id=product.id,
                       workflow_version_id=version.id, stage=first_stage,
                       owner_login=owner, request_id=request_id)
    session.add(case)
    await session.flush()
    session.add(ServiceEvent(case_id=case.id, event_type="case_opened",
                             actor=_audit_actor(by, None), to_stage=first_stage,
                             payload={"revision": case.revision,
                                      "workflow_version_id": version.id}))
    await session.flush()
    return case


async def advance(session: AsyncSession, case_id: int, *, to_stage: str, by: Actor,
                  actor: str | None = None, reason: str = "",
                  facts: dict | None = None,
                  expected_revision: int | None = None) -> ServiceCase:
    """Перевести услугу на следующий этап — только разрешённым переходом.

    Каждый успешный переход оставляет событие в той же транзакции, что и сама
    смена этапа: иначе история расходится с состоянием, и восстановить прежний
    этап нечем.
    """
    # Коды этапов объявляются без пробелов по краям (_validate_workflow это
    # требует), поэтому вход с пробелами — не тот же самый этап, а другой.
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "advance service case")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_advance_case(by, direction=product.direction if product else None,
                             owner_login=case.owner_login), "advance service case")
    # Данные проверяются ПОСЛЕ прав: иначе чужой менеджер по разным сообщениям об
    # ошибке отличает «нет прав» от «плохой этап» и изучает чужое направление.
    if not isinstance(to_stage, str):
        raise DomainError("to_stage must contain 1..64 characters")
    if to_stage != to_stage.strip():
        # Код этапа объявляется без пробелов по краям, значит « TOUR-02 » — это не
        # тот же этап, а другой, которого в процессе нет. Проверяется раньше
        # пустоты: строка из одних пробелов — это тоже про пробелы, а не про длину.
        raise DomainError("stage codes must have no surrounding whitespace")
    if not to_stage:
        raise DomainError("to_stage must contain 1..64 characters")
    if expected_revision is not None and case.revision != expected_revision:
        raise DomainError("revision conflict: service case changed concurrently")
    version = await session.get(WorkflowVersion, case.workflow_version_id)
    if version is None or version.published_at is None:
        raise DomainError("service case has no published workflow version")
    if to_stage not in {stage["code"] for stage in version.stages}:
        raise DomainError(f"unknown stage {to_stage!r}")
    if to_stage not in version.transitions.get(case.stage, []):
        raise DomainError(f"transition {case.stage!r} -> {to_stage!r} is not allowed")
    # FLOW-03: сервер проверяет обязательные факты перехода. Без этого «Бронь
    # подтверждена» ставилась бы без номера и даты — то есть менеджер утверждал бы
    # факт, которого в системе нет, и восстановить его потом было бы неоткуда.
    target = next((s for s in version.stages if s["code"] == to_stage), {})
    required = [str(name) for name in (target.get("requires") or [])]
    if facts is not None and not isinstance(facts, dict):
        raise DomainError("facts must be a mapping of fact names to values")
    given = {}
    for raw_name, raw in (facts or {}).items():
        prepared = _fact_value(str(raw_name), raw)
        if prepared is not None:
            given[str(raw_name)] = prepared
    missing = [name for name in required if name not in given]
    if missing:
        raise DomainError(
            "stage %s requires facts: %s" % (to_stage, ", ".join(sorted(missing))))

    actor_login = _audit_actor(by, actor)
    previous_stage = case.stage
    try:
        # Ошибка записи истории откатывает и переход; commit остаётся за вызывающим кодом.
        async with session.begin_nested():
            # Защита поля снимается ровно на это присваивание: вне `advance` этап
            # не меняется, иначе переход происходит без проверок и без истории.
            object.__setattr__(case, "_advance_in_progress", True)
            try:
                case.stage = to_stage
            finally:
                object.__setattr__(case, "_advance_in_progress", False)
            await session.flush()
            session.add(ServiceEvent(case_id=case.id, event_type="stage_changed",
                                     actor=actor_login, from_stage=previous_stage,
                                     to_stage=to_stage, reason=reason,
                                     payload={"revision": case.revision,
                                              "workflow_version_id": case.workflow_version_id,
                                              "facts": given or None}))
            await session.flush()
    except StaleDataError as exc:
        await session.refresh(case)
        raise DomainError("revision conflict: service case changed concurrently") from exc
    return case


async def sign_contract(session: AsyncSession, *, contact_id: int, product_id: int,
                        owner_login: str, by: Actor, reference: str,
                        signed_at: datetime | None = None,
                        amount: Decimal | str | None = None, currency: str | None = None,
                        amount_unknown_reason: str = "",
                        request_id: int | None = None,
                        idempotency_key: str) -> ServiceCase:
    """Подписан договор — заводится исполнение. Ровно один раз (AC-01, FLOW-02).

    Порядок здесь выстрадан проверками: сначала права, потом данные, и только потом
    запись. Первая версия делала наоборот — валидация номера шла ПОСЛЕ создания
    услуги, и отказ оставлял в базе незавершённую операцию.

    Повтор с тем же ключом возвращает ту же услугу. Но тот же ключ с ДРУГИМИ данными
    это не повтор, а конфликт: иначе опечатка в сумме молча вернула бы старый договор
    как успешно подписанный.
    """
    # 1. Права — раньше всего. Отказ не должен зависеть от того, валидны ли данные:
    #    иначе по разным сообщениям об ошибке изучают чужое направление.
    product = await session.get(Product, product_id)
    if product is None:
        require(by.is_full_admin, "sign contract")
        raise DomainError(f"unknown product {product_id}")
    require(can_open_case(by, direction=product.direction), "sign contract")
    if not str(by.manager_id or "").strip():
        # Подпись обязана принадлежать человеку: пустой актор не фиксирует продажу.
        raise PermissionDenied("not allowed: sign contract")

    # Владелец услуги. Без этой проверки менеджер заводил договор на чужой или вовсе
    # несуществующий логин: услуга создавалась, но автор не мог её ни видеть, ни
    # двигать, а начальная задача падала на человека без прав на это направление.
    # Это обходило правила переназначения, где цель сверяется со списком менеджеров.
    owner = _required_text(owner_login, "owner_login", 64).lower()
    if not by.is_full_admin:
        # Менеджер подписывает договор только на себя. Отдать услугу другому — это
        # отдельная операция переназначения, со своей проверкой и записью в историю.
        if owner != by.manager_id.strip().lower():
            raise PermissionDenied("not allowed: sign contract for another manager")
    elif by.manager_id != SYSTEM_ACTOR.manager_id:
        known = {str(m.login or "").strip().lower() for m in settings.manager_list()}
        if known and owner not in known:
            raise DomainError("owner manager is not configured")
    # Системный актор сверке со списком не подлежит: при переносе старых обращений
    # (E1-04) владелец берётся из истории, и в нынешнем списке менеджеров его может
    # уже не быть — Сезим уволилась, а её услуги существуют.

    # 2. Данные — до единой записи в базу.
    #
    # Ключ ОБЯЗАТЕЛЕН. Без него AC-01 не держится: два вызова подряд создавали две
    # услуги и две задачи, то есть повторный клик менеджера превращался во второй
    # договор. Жёсткий запрет «одна услуга на клиента и продукт» вместо этого ввести
    # нельзя — семья покупает два тура, себе и родителям, и это законный случай.
    # Ключ разводит их: случайный повтор приходит с тем же ключом, намеренный второй
    # тур — с новым. При переносе старых данных (E4) ключ берётся из legacy `user_id`.
    key = _required_text(idempotency_key, "idempotency key", 128)
    reference = _required_text(reference, "contract reference", 128)
    currency_code = str(currency or "").strip().upper() or None
    if currency_code is not None and not re.fullmatch(r"[A-Z]{3}", currency_code):
        raise DomainError("currency must be a three-letter code")
    unknown_reason = _optional_text(amount_unknown_reason, "amount_unknown_reason", 255)
    amount_value = _contract_amount(amount, currency_code, unknown_reason)
    if signed_at is not None:
        if not isinstance(signed_at, datetime):
            raise DomainError("signed_at must be a datetime")
        if signed_at.tzinfo is None:
            # Наивное время молча толковалось как UTC, и дата задачи уезжала на сутки
            # относительно Бишкека. Пусть вызывающий скажет зону явно.
            raise DomainError("signed_at must be timezone-aware")
    signed_moment = signed_at or _now()

    # 3. Повтор: та же услуга, но только если данные совпадают.
    #
    # Принятый риск: ключ глобальный, а не свой у каждого менеджера. По отличию
    # отказа от успеха можно узнать, занят ли конкретный ключ — но не чьей услугой
    # и с какими данными (тексты отказов одинаковые, `_twin_for` проверяет право
    # видеть). Ключи выдаёт интерфейс, это UUID: подобрать существующий нельзя.
    existing = await session.scalar(
        select(ServiceCase).where(ServiceCase.idempotency_key == key))
    if existing is not None:
        await _twin_for(session, existing, by)
        _assert_same_contract(existing, contact_id=contact_id, product_id=product_id,
                              reference=reference, amount=amount_value,
                              currency=currency_code, owner_login=owner,
                              unknown_reason=unknown_reason, request_id=request_id,
                              signed_at=signed_at)
        return existing

    # SAVEPOINT охватывает ВСЮ запись: услугу, договор, событие и начальные задачи.
    # Откатывается он при ЛЮБОМ исключении, а не только при конфликте ключа. Иначе
    # ошибка внутри (неизвестный контакт, архивный продукт, мусор в описании задачи)
    # оставляла точку сохранения открытой, и если вызывающий перехватывал ошибку и
    # делал commit — в базе оседал полусозданный договор: услуга с ключом и номером,
    # но без события подписи и без задач. Повтор с тем же ключом возвращал бы её как
    # успешную, то есть починить такую запись подписанием уже нельзя.
    #
    # И это savepoint, а не откат всей транзакции: вызывающий мог записать до нас
    # своё, сносить его работу из-за нашей гонки нельзя.
    savepoint = await session.begin_nested()
    try:
        case = await open_case(session, contact_id=contact_id, product_id=product_id,
                               owner_login=owner, by=by, request_id=request_id)
        case.contract_reference = reference
        case.signed_at = signed_moment
        case.signed_by = by.manager_id
        # Поля цены закрыты валидатором: их меняет только денежная операция с
        # правом и событием. Первичное заполнение при подписании — исключение,
        # и оно объявляется явно, на один вызов.
        object.__setattr__(case, "_money_correction_in_progress", True)
        try:
            case.agreed_amount = amount_value
            case.currency = currency_code
        finally:
            object.__setattr__(case, "_money_correction_in_progress", False)
        case.amount_unknown_reason = unknown_reason or None
        case.idempotency_key = key
        await session.flush()
        session.add(ServiceEvent(
            case_id=case.id, event_type="contract_signed",
            actor=_audit_actor(by, None), to_stage=case.stage,
            reason=unknown_reason or "",
            payload={"reference": reference,
                     "amount": str(amount_value) if amount_value is not None else None,
                     "currency": currency_code, "revision": case.revision}))
        version = await session.get(WorkflowVersion, case.workflow_version_id)
        if version is not None:
            await _create_initial_tasks(session, case, version,
                                        direction=product.direction, by=by)
        await session.flush()
    except IntegrityError as exc:
        await savepoint.rollback()
        twin = await session.scalar(
            select(ServiceCase).where(ServiceCase.idempotency_key == key))
        if twin is not None:
            await _twin_for(session, twin, by)
            _assert_same_contract(twin, contact_id=contact_id, product_id=product_id,
                                  reference=reference, amount=amount_value,
                                  currency=currency_code, owner_login=owner,
                                  unknown_reason=unknown_reason, request_id=request_id,
                                  signed_at=signed_at)
            return twin
        raise DomainError("contract conflict; retry") from exc
    except BaseException:
        # Любая другая ошибка — тоже полный откат нашей части, чтобы в базе не осталось
        # половины операции. Отмену (CancelledError) это покрывает тоже.
        await savepoint.rollback()
        raise
    else:
        await savepoint.commit()
    return case


async def _follow_assignment(session: AsyncSession, *, contact_id: int, direction: str | None,
                             manager_login: str, by: Actor, reason: str) -> None:
    """Назначение диалога следует за владельцем услуги.

    Решение Алана 05.10 по находке аудита: две модели владения разъезжались —
    менеджер владел услугой, но не мог написать клиенту, а писал другой, который
    услуги не видел. Ведущим выбран коммерческий объект: услуга первична, переписка
    вокруг неё. Так же сказано в техническом приложении ТЗ: «новый владелец и
    согласованный перенос».

    Отбирать активное назначение у другого менеджера вправе только администратор —
    то же правило, что в `permissions.can_reassign` для диалогов.
    """
    if not direction or manager_login == SYSTEM_ACTOR.manager_id:
        return
    from app.domain.services import AssignmentService
    try:
        await AssignmentService.assign(session, contact_id, direction, manager_login,
                                       assigned_by=by.manager_id, reason=reason,
                                       allow_emergency=by.is_full_admin)
    except DomainError:
        # Назначение занято другим менеджером, а прав на перехват нет. Услуга уже
        # передана — расходиться им нельзя, поэтому отказываем целиком.
        raise DomainError(
            "dialog is assigned to another manager; reassign it first or ask an admin")


async def reassign_case(session: AsyncSession, case_id: int, *, target_login: str,
                        by: Actor, reason: str = "",
                        expected_revision: int | None = None) -> ServiceCase:
    """Передать услугу другому менеджеру — с событием в истории.

    Без этой операции модель прав была тупиком, и аудит это показал: услугу
    уволившегося сотрудника не мог двинуть никто, включая администратора, а
    единственным выходом было прямое присваивание владельца — бесследное.

    Правило «этап двигает только владелец» работает лишь в паре с переназначением,
    которое оставляет след: кто передал, кому, когда и почему.
    """
    case = await session.get(ServiceCase, case_id, populate_existing=True)
    if case is None:
        require(by.is_full_admin, "reassign case")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    direction = product.direction if product else None
    require(can_reassign_case(by, direction=direction, owner_login=case.owner_login,
                              target_login=target_login), "reassign case")
    target_login = _required_text(target_login, "target_login", 64).strip().lower()
    # Цель сверяем со списком менеджеров: в переназначении диалогов это уже делается,
    # а здесь услугу можно было отдать логину, которого нет ни в одной настройке —
    # и она становилась недоступна всем. Системный владелец допустим для джоб.
    known = {str(m.login or "").strip().lower() for m in settings.manager_list()}
    known.add(SYSTEM_ACTOR.manager_id)
    if known and target_login not in known:
        raise DomainError("target manager is not configured")
    if expected_revision is not None and case.revision != expected_revision:
        raise DomainError("revision conflict: service case changed concurrently")
    previous = case.owner_login
    if previous.strip().lower() == target_login:
        # Владелец уже этот — но задачи могли появиться позже или не доехать с
        # прошлого раза. Перенос идемпотентен, поэтому дотягиваем их и выходим:
        # иначе повторный вызов не мог исправить расхождение.
        from app.domain.task_rules import transfer_open_tasks
        await transfer_open_tasks(session, case.id, new_owner=target_login,
                                  actor=by.manager_id)
        await session.flush()
        return case                      # повтор не плодит событие и не двигает ревизию
    object.__setattr__(case, "_reassign_in_progress", True)
    try:
        case.owner_login = target_login
    finally:
        object.__setattr__(case, "_reassign_in_progress", False)
    session.add(ServiceEvent(case_id=case.id, event_type="owner_changed",
                             actor=_audit_actor(by, None), reason=reason,
                             payload={"from": previous, "to": target_login,
                                      "revision": case.revision}))
    await _follow_assignment(session, contact_id=case.contact_id, direction=direction,
                             manager_login=target_login, by=by,
                             reason=reason or "передача услуги")
    # Открытые задачи услуги переходят новому владельцу (AC-29). Импорт локальный:
    # `task_rules` читает `service_cases`, и на уровне модуля вышел бы цикл.
    from app.domain.task_rules import transfer_open_tasks
    moved = await transfer_open_tasks(session, case.id, new_owner=target_login,
                                      actor=by.manager_id)
    from app.domain.task_rules import orphan_tasks
    orphans = await orphan_tasks(session, contact_id=case.contact_id,
                                 direction=direction or "")
    if moved or orphans:
        session.add(ServiceEvent(
            case_id=case.id, event_type="tasks_transferred",
            actor=_audit_actor(by, None), reason=reason,
            payload={"task_ids": list(moved), "to": target_login,
                     # Задачи без ссылки на услугу остались у прежнего владельца:
                     # привязать их автоматически нельзя, но молчать о них тоже.
                     "orphan_task_ids": list(orphans)}))
    await session.flush()
    return case


def stage_plan(version: WorkflowVersion, stage_code: str) -> dict:
    """Положение этапа в процессе и что с него доступно. Чистая функция.

    Нужна и для полосы пути в карточке, и для вывода следующего шага: без неё
    интерфейс пересказывал бы содержимое `version.stages` своими словами и
    однажды разошёлся бы с процессом. Процесс версионирован — читаем его, а не
    хардкодим этапы.
    """
    stages = list(version.stages or [])
    codes = [str(s.get("code") or "") for s in stages]
    index = codes.index(stage_code) if stage_code in codes else -1
    current = stages[index] if index >= 0 else {}
    allowed = [str(c) for c in (version.transitions or {}).get(stage_code, [])]
    by_code = {str(s.get("code") or ""): s for s in stages}
    return {
        "index": index,
        "total": len(stages),
        "name": str(current.get("name") or stage_code),
        "next": allowed,
        # Обязательные факты КАЖДОГО доступного перехода: интерфейс спрашивает ровно
        # их, а имена полей берёт отсюда, а не из захардкоженного списка.
        "requires": {code: [str(f) for f in (by_code.get(code, {}).get("requires") or [])]
                     for code in allowed},
        "next_names": {code: str(by_code.get(code, {}).get("name") or code)
                       for code in allowed},
    }


async def cases_for_owner(session: AsyncSession, *, by: Actor,
                          owner_login: str | None = None,
                          direction: str | None = None,
                          limit: int = 200) -> list[ServiceCase]:
    """Услуги, которые менеджер вправе видеть. Только чтение.

    Фильтр по направлению и владению идёт в SQL, но результат ДОПОЛНИТЕЛЬНО
    прогоняется через `can_view_case`: запрос — оптимизация, право — правило.
    Так же сделано в `task_rules.case_tasks`.
    """
    query = select(ServiceCase).join(Product, Product.id == ServiceCase.product_id)
    if owner_login:
        query = query.where(ServiceCase.owner_login == str(owner_login).strip().lower())
    if direction:
        query = query.where(Product.direction == direction)
    elif not by.is_full_admin and by.allowed_directions:
        query = query.where(Product.direction.in_(tuple(by.allowed_directions)))
    # Берём кандидатов ШИРОКО: порядок по срочности считается выше, и обрезать до
    # него по id нельзя — услуга с просроченным вылетом, заведённая раньше
    # последних пятидесяти, иначе не попадёт на экран вовсе. Потолок всё же есть,
    # чтобы запрос не стал неограниченным.
    rows = list(await session.scalars(
        query.order_by(ServiceCase.id.desc()).limit(max(1, int(limit)))))

    visible: list[ServiceCase] = []
    for case in rows:
        product = await session.get(Product, case.product_id)
        if can_view_case(by, direction=product.direction if product else None,
                         owner_login=case.owner_login):
            visible.append(case)
    return visible


async def cases_for_contact(session: AsyncSession, contact_id: int) -> list[ServiceCase]:
    return list((await session.scalars(select(ServiceCase).where(
        ServiceCase.contact_id == contact_id).order_by(ServiceCase.id))).all())


async def seed_products(session: AsyncSession, *, published_by: str, by: Actor) -> list[Product]:
    """Повторный явный запуск не реактивирует архив и не заменяет уже выбранный процесс.

    ВАЖНО для выкатки: версия процесса публикуется только если её ещё нет. Значит
    изменения в `TOUR_STAGES` — в том числе обязательные факты (`requires`) и
    начальная задача (`first_task`) — НЕ применятся к продукту, у которого версия
    уже опубликована. Это намеренно (AC-17: подписанные услуги сохраняют свою
    версию), но чтобы новые правила заработали, нужна отдельная публикация новой
    версии, а не повторный запуск сидера.
    """
    products = []
    for code, name, direction in INITIAL_PRODUCTS:
        product = await session.scalar(select(Product).where(Product.code == code))
        if product is None:
            product = await create_product(session, code=code, name=name,
                                           direction=direction, by=by)
        elif product.direction != direction:
            raise DomainError(f"product code {code!r} already has a different direction")
        products.append(product)
        if code == "tour_package" and product.active and product.current_version_id is None:
            await publish_version(session, product.id, TOUR_STAGES, TOUR_TRANSITIONS,
                                  published_by, by=by)
    return products
