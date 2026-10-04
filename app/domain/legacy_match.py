"""E1-04 — сопоставление старых обращений с новыми услугами (CRITICAL).

Здесь только РЕШЕНИЕ о том, что чему соответствует. Ничего не пишется в базу:
по ТЗ реальный перенос выполняется в E4, а на этом шаге нужна идемпотентная
репетиция и реестр того, что сопоставить не удалось.

Два правила, из которых следует всё остальное:

1. **Люди объединяются только по телефону.** Ни имя, ни `bitrix_lead_id` не
   служат признаком одного человека. Имена у нас совпадают постоянно («Азамат»),
   а одна карточка Bitrix регулярно собирает нескольких людей: лид создаёт
   коннектор Wappi, менеджер дописывает туда родственника, и в итоге за одним
   `lead_id` стоят два номера. Объединить их — значит склеить двух клиентов с их
   деньгами и переписками, а расклеить потом нельзя. Поэтому такая карточка
   попадает в реестр как спорная, а телефоны остаются раздельными.

2. **Старая сумма не становится договорной ценой** (AC-07). В legacy
   `sale_amount` — это `Float`, причём заполнял его менеджер по памяти, уже после
   продажи. Такое значение нельзя ни считать суммой договора, ни превращать во
   вторую оплату: оно идёт в реестр с пометкой «сверить», и решение принимает
   человек. Отдельно: `float` на деньгах теряет копейки, и `_contract_amount` в
   `service_cases` его прямо отклоняет — значит молча перелить сюда не получится.

План — чистая функция от входа: один и тот же вход даёт один и тот же план, в
одном и том же порядке. Это и есть идемпотентность репетиции (AC-36): прогон
дважды не создаёт ни дублей, ни расхождений.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.domain.models import DomainError
from app.domain.phones import normalize_phone

# Направления, которые существуют в новой схеме. `funnel` из legacy может быть
# пустым (диалог начался до того, как бот понял, чего хочет клиент) — угадывать
# направление по тексту мы не будем, это уход в реестр.
KNOWN_DIRECTIONS = ("tours", "visa", "tickets")

# Причины попадания в реестр. Строки стабильные: по ним группируют отчёт.
UNNORMALIZABLE_PHONE = "unnormalizable_phone"
UNKNOWN_DIRECTION = "unknown_direction"
MIXED_BITRIX_CARD = "mixed_bitrix_card"
AMOUNT_NEEDS_RECONCILIATION = "amount_needs_reconciliation"
AMOUNT_UNPARSEABLE = "amount_unparseable"
PHONE_KEY_MISMATCH = "phone_key_mismatch"


@dataclass(frozen=True)
class LegacyDialog:
    """Одно старое обращение — то, что нам нужно от `conversations`.

    Намеренно не ORM-объект: сопоставление не должно зависеть от legacy-схемы и
    должно проверяться без базы.
    """

    user_id: str                      # "<bot_id>:<номер>", ключ диалога в legacy
    phone: str = ""
    bot_id: str = ""
    funnel: str | None = None
    outcome: str = ""
    bitrix_lead_id: str = ""
    sale_amount: float | None = None
    sale_currency: str = ""


@dataclass(frozen=True)
class Link:
    """Предложенное соответствие: один человек, одно направление.

    `legacy_user_ids` может содержать несколько ключей: один и тот же номер
    писал и на туровый, и на визовый номер — это один человек с двумя услугами,
    и на каждое направление приходится своя связь.
    """

    phone: str                        # нормализованный номер — единственный признак личности
    direction: str
    legacy_user_ids: tuple[str, ...]
    bitrix_lead_ids: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Problem:
    """Строка реестра: что именно сопоставить не удалось и почему."""

    kind: str
    user_ids: tuple[str, ...]
    detail: str = ""


@dataclass(frozen=True)
class MatchPlan:
    links: tuple[Link, ...] = ()
    problems: tuple[Problem, ...] = ()

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {"links": len(self.links)}
        for problem in self.problems:
            counts[problem.kind] = counts.get(problem.kind, 0) + 1
        return counts


# Сторож «значение было, но разобрать не смогли» — отличается от «значения нет».
_UNPARSEABLE = object()

# Минимум цифр, при котором строку можно считать телефоном с кодом страны.
# Голые 9 цифр `normalize_phone` достраивает до киргизского номера, и
# telegram-идентификатор вида `tg:700111222` превращался в +996700111222,
# склеиваясь с реальным абонентом. Для переноса данных это недопустимо.
MIN_PHONE_DIGITS = 10


def _identity(user_id: str, raw_phone, problems: list) -> str | None:
    """Единственный признак личности — телефон. Вернуть его или записать проблему.

    Сверяются ДВА источника: колонка `phone` (для показа) и номер внутри ключа
    диалога `"<bot_id>:<номер>"`. Если оба разбираются и не совпадают, диалог не
    сопоставляется: первая версия молча доверяла колонке `phone`, и диалог одного
    человека утекал в связь другого — ровно та склейка, которую правило запрещает.
    """
    from_field = _phone_or_none(raw_phone)
    from_key = _phone_or_none(user_id.split(":", 1)[-1] if ":" in user_id else "")
    if from_field and from_key and from_field != from_key:
        problems.append(Problem(PHONE_KEY_MISMATCH, (user_id,),
                                "номер в ключе диалога не совпадает с полем phone"))
        return None
    phone = from_field or from_key
    if not phone:
        problems.append(Problem(UNNORMALIZABLE_PHONE, (user_id,),
                                "номер не разобран или слишком короткий"))
        return None
    return phone


def _phone_or_none(raw) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if sum(ch.isdigit() for ch in text.split("@", 1)[0]) < MIN_PHONE_DIGITS:
        # Слишком коротко для номера с кодом страны: telegram-id, внутренний
        # идентификатор или обрезанный номер. Достраивать не станем.
        return None
    try:
        return normalize_phone(text, assume_e164=True)
    except DomainError:
        return None


def _legacy_amount(value):
    """Старая сумма в виде, пригодном для ОТЧЁТА, а не для записи в договор.

    Возвращает Decimal для показа человеку, None если суммы нет, и `_UNPARSEABLE`
    если значение было, но разобрать его не удалось — такое нельзя терять молча.
    Ни один вызывающий не должен класть это в `agreed_amount`: решение о сумме
    договора принимает человек при сверке.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return _UNPARSEABLE
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError):
        return _UNPARSEABLE
    if not amount.is_finite():
        return _UNPARSEABLE
    if amount < 0:
        # Минус в сумме продажи — возможный возврат либо ошибка ввода. Решает человек.
        return _UNPARSEABLE
    if amount == 0:
        # Ноль означает «менеджер не заполнил», сверять тут нечего.
        return None
    if amount >= Decimal("10") ** 12:
        return _UNPARSEABLE
    # Две цифры после запятой: источник — float, и хвост вида 0.30000000000000004
    # в отчёте о деньгах только путает.
    return amount.quantize(Decimal("0.01"))


def plan_links(dialogs) -> MatchPlan:
    """Построить план сопоставления и реестр спорного.

    Результат полностью упорядочен и не зависит от порядка поданных обращений.
    Это пришлось доказывать отдельно: первая версия складывала ключи в порядке
    появления, и перестановка входа давала другой план — 50 проверок из 50. База
    читается `SELECT` без `ORDER BY`, то есть два прогона на живых данных могли
    разойтись. Поэтому сортируется всё, а не только ключи групп.
    """
    grouped: dict[tuple[str, str], dict[str, set]] = {}
    problems: list[Problem] = []
    by_lead: dict[str, set[str]] = {}
    lead_dialogs: dict[str, set[str]] = {}

    for dialog in dialogs:
        user_id = str(getattr(dialog, "user_id", "") or "")
        amount = _legacy_amount(getattr(dialog, "sale_amount", None))
        currency = str(getattr(dialog, "sale_currency", "") or "").strip().upper()
        if amount is _UNPARSEABLE:
            # Непустое, но неразобранное значение денег. Молча терять его нельзя:
            # это может быть ручная правка менеджера вида «1 500».
            problems.append(Problem(AMOUNT_UNPARSEABLE, (user_id,),
                                    "значение суммы не разобрано; проверить вручную"))
        elif amount is not None:
            # AC-07: сумма из legacy требует сверки человеком и НЕ едет в договор.
            # Записывается ДО всех ранних выходов ниже — иначе продажа с деньгами,
            # у которой не определилось направление, теряла пометку «сверить».
            problems.append(Problem(
                AMOUNT_NEEDS_RECONCILIATION, (user_id,),
                f"{amount} {currency}".strip() + "; требует сверки, не договорная цена"))

        phone = _identity(user_id, getattr(dialog, "phone", ""), problems)
        if phone is None:
            continue

        direction = str(getattr(dialog, "funnel", "") or "").strip().lower()
        if direction not in KNOWN_DIRECTIONS:
            # Направление неизвестно — в реестр. Угадывание означало бы услугу не
            # того продукта, с не теми этапами и сроками.
            problems.append(Problem(UNKNOWN_DIRECTION, (user_id,), direction or "(пусто)"))
            continue

        bucket = grouped.setdefault((phone, direction),
                                    {"user_ids": set(), "leads": set(), "outcomes": set()})
        bucket["user_ids"].add(user_id)

        lead = str(getattr(dialog, "bitrix_lead_id", "") or "").strip()
        if lead:
            bucket["leads"].add(lead)
            by_lead.setdefault(lead, set()).add(phone)
            lead_dialogs.setdefault(lead, set()).add(user_id)

        outcome = str(getattr(dialog, "outcome", "") or "").strip()
        if outcome:
            bucket["outcomes"].add(outcome)

    # Смешанные карточки Bitrix: один лид на несколько номеров. Телефоны НЕ
    # объединяем — только сообщаем, что карточка спорная. На боевых данных нашёлся
    # лид, указанный у 20 разных номеров: объединение по нему склеило бы 20 людей.
    for lead in sorted(by_lead):
        phones = by_lead[lead]
        if len(phones) > 1:
            affected = tuple(sorted(lead_dialogs.get(lead, ())))
            problems.append(Problem(
                MIXED_BITRIX_CARD, affected,
                f"лид {lead} указан у {len(phones)} разных номеров "
                f"({len(affected)} обращений); объединение запрещено, "
                "нужна ручная разводка"))

    links = tuple(
        Link(phone=phone, direction=direction,
             legacy_user_ids=tuple(sorted(bucket["user_ids"])),
             bitrix_lead_ids=tuple(sorted(bucket["leads"])),
             outcomes=tuple(sorted(bucket["outcomes"])))
        for (phone, direction), bucket in sorted(grouped.items()))
    return MatchPlan(links=links, problems=tuple(
        sorted(problems, key=lambda p: (p.kind, p.user_ids, p.detail))))
