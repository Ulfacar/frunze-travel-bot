"""B4 (план отказа §3.3): перенос ОТКРЫТЫХ лидов из архива Битрикса в панель. CRITICAL.

Источник — JSONL архива (`scripts/bitrix_archive_export.py`), не портал. Сначала план
без записи: «создам контакт / свяжу с существующим / уже перенесён / конфликт». Запись
(`apply_plan`) — только по явному решению: на проде по слову Алана.

Правила склейки — те же, что в `app/domain/legacy_match.py`, и они важнее удобства:

* **Человек = телефон.** Номер разбирается `legacy_match._phone_or_none` (не меньше 10
  цифр, `normalize_phone`). Имя, ID лида, ответственный — не признаки личности. План
  обещает только номер, который запись нормализует так же (иначе — реестр), а «8…» из
  11 цифр без «+» — «проверить вручную».
* **Одна карточка — один номер.** Лид с двумя разными номерами (общая карточка
  Открытой линии: менеджер дописал родственника) не переносится: это `mixed_card` в
  реестр, разводит человек (ТЗ §19 п.2: «автоматическое слияние по одному Bitrix ID
  запрещено»). Так же — если наш диалог с этим `bitrix_lead_id` принадлежит другому номеру.
* **Направление не угадываем.** Берём его из уже существующих диалогов этого номера
  (одно направление — значит оно), иначе из ответственного (`ASSIGNED_BY_ID` →
  направление по явной карте, которую даёт оператор). Нет или несколько — в реестр.
* **Идемпотентность.** Ключ — `ExternalReference(provider="bitrix", external_type="lead",
  external_id=<ID>)`. Уже связанный лид пропускается; второй прогон = 0 изменений.

Пишется только доменное: `Contact` + `ContactIdentity(phone)`, `Request` направления (если
активного нет), `ExternalReference`. Диалоги, сообщения, владельцы и Bitrix не трогаются.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import or_, select

from app.domain.legacy_match import KNOWN_DIRECTIONS, _phone_or_none
from app.domain.models import DomainError
from app.domain.phones import normalize_phone

PROVIDER, LEAD = "bitrix", "lead"
TERMINAL = frozenset({"CONVERTED", "JUNK", "UC_R8BD0W"})   # = bitrix_pipeline.TERMINAL_STATUSES

CREATE = "create_contact"          # контакта с этим номером нет — создам
LINK = "link_existing"             # контакт/диалог по номеру уже есть — свяжу
DONE = "already_linked"            # лид уже перенесён прежним прогоном
# Реестр: не переносим, решает человек. Строки стабильные — по ним группируют отчёт.
NO_PHONE = "no_phone"
BAD_PHONE = "unnormalizable_phone"
MIXED = "mixed_card"
FOREIGN_DIALOG = "lead_belongs_to_other_number"
NO_DIRECTION = "unknown_direction"
TWO_DIRECTIONS = "ambiguous_direction"
# «8 999 123 45 67» без «+»: это и российский 8…, и +7…; WhatsApp того же человека даст
# 7…, а не 8… — создать личность значит расщепить человека надвое (ревью pdf, 1.3).
CHECK_BY_HAND = "check_by_hand"
PROBLEMS = (NO_PHONE, BAD_PHONE, MIXED, FOREIGN_DIALOG, NO_DIRECTION, TWO_DIRECTIONS, CHECK_BY_HAND)


@dataclass(frozen=True)
class Item:
    lead_id: str
    action: str
    phone: str = ""                # нормализованный; в отчёте маскируется
    direction: str = ""
    dialogs: tuple[str, ...] = ()
    detail: str = ""


@dataclass
class Plan:
    items: list[Item] = field(default_factory=list)
    skipped_closed: int = 0
    duplicate_rows: int = 0

    @property
    def summary(self) -> dict[str, int]:
        out: dict[str, int] = {"open_leads": len(self.items), "closed_skipped": self.skipped_closed,
                               "duplicate_rows": self.duplicate_rows}
        for item in self.items:
            out[item.action] = out.get(item.action, 0) + 1
        return out


def _raw_phones(record: dict) -> list[str]:
    out = []
    for value in record.get("PHONE") or []:
        raw = value.get("VALUE") if isinstance(value, dict) else value
        if str(raw or "").strip():
            out.append(str(raw).strip())
    return out


def _trunk_eight(raw: str) -> bool:
    head = str(raw or "").split("@", 1)[0].strip()
    digits = "".join(ch for ch in head if ch.isdigit())
    return not head.startswith("+") and len(digits) == 11 and digits.startswith("8")


def _survives_write(phone: str) -> bool:
    """Запись (`find_or_create_by_identity(assume_e164=True)`) нормализует номер ещё раз.
    План обещает только то, что пройдёт эту повторную нормализацию без изменений:
    «+65 6123 4567» → `6561234567`, а 10 цифр без «+» запись уже не примет (ревью pdf, 1.1)."""
    try:
        return normalize_phone(phone, assume_e164=True) == phone
    except DomainError:
        return False


def open_leads(rows: Iterable[dict], plan: Plan):
    """Открытые лиды без повторов по ID. Закрытые и дубли строк — только счётчики."""
    seen = set()
    for row in rows:
        lead_id = str(row.get("ID") or "").strip()
        if not lead_id:
            continue
        if lead_id in seen:
            plan.duplicate_rows += 1
            continue
        seen.add(lead_id)
        if str(row.get("STATUS_ID") or "") in TERMINAL:
            plan.skipped_closed += 1
            continue
        yield row


class Existing:
    """Что уже есть в базе. Только чтение; в тестах и в сухом прогоне без базы — пусто."""

    async def contact_for(self, phone: str) -> int | None:
        return None

    async def dialogs_for(self, phone: str) -> list[tuple[str, str]]:
        return []

    async def dialogs_with_lead(self, lead_id: str) -> list[tuple[str, str]]:
        return []

    async def linked(self, lead_id: str) -> bool:
        return False


class DbExisting(Existing):
    """Чтение из одной базы, где лежат и `conversations`, и доменные таблицы (прод бота)."""

    def __init__(self, sessionmaker):
        self._sm = sessionmaker

    async def contact_for(self, phone):
        from app.domain.models import ContactIdentity
        async with self._sm() as s:
            return await s.scalar(select(ContactIdentity.contact_id).where(
                ContactIdentity.identity_type == "phone",
                ContactIdentity.normalized_value == phone).limit(1))

    async def dialogs_for(self, phone):
        from app.integrations.crm.db import Conversation
        async with self._sm() as s:
            rows = (await s.execute(select(Conversation.user_id, Conversation.funnel, Conversation.phone)
                                    .where(or_(Conversation.phone == phone,
                                               Conversation.user_id.like(f"%:{phone}"))))).all()
        return sorted((u, f or "") for u, f, p in rows
                      if _phone_or_none(p or u.split(":", 1)[-1]) == phone)

    async def dialogs_with_lead(self, lead_id):
        from app.integrations.crm.db import Conversation
        async with self._sm() as s:
            rows = (await s.execute(select(Conversation.user_id, Conversation.phone)
                                    .where(Conversation.bitrix_lead_id == lead_id))).all()
        return sorted((u, p or u.split(":", 1)[-1]) for u, p in rows)

    async def linked(self, lead_id):
        from app.domain.models import ExternalReference
        async with self._sm() as s:
            return await s.scalar(select(ExternalReference.id).where(
                ExternalReference.provider == PROVIDER, ExternalReference.external_type == LEAD,
                ExternalReference.external_id == lead_id,
                ExternalReference.active.is_(True))) is not None


async def build_plan(leads: Iterable[dict], contacts: dict[str, list[str]], existing: Existing,
                     *, assignee_direction: dict[str, str] | None = None) -> Plan:
    """План без записи. Порядок — по ID лида: один вход → один и тот же план."""
    assignee_direction = assignee_direction or {}
    plan = Plan()
    rows = sorted(open_leads(leads, plan), key=lambda r: (len(str(r["ID"])), str(r["ID"])))
    planned: dict[str, int] = {}        # номер → лидов этого прогона, создающих контакт
    for row in rows:
        lead_id = str(row["ID"])
        raw = _raw_phones(row) + list(contacts.get(str(row.get("CONTACT_ID") or ""), []))
        if await existing.linked(lead_id):
            plan.items.append(Item(lead_id, DONE))
            continue
        if not raw:
            plan.items.append(Item(lead_id, NO_PHONE, detail="ни в лиде, ни в контакте"))
            continue
        if any(_trunk_eight(r) for r in raw):
            plan.items.append(Item(lead_id, CHECK_BY_HAND,
                                   detail="номер через 8 без «+» — проверить вручную (8… или +7…)"))
            continue
        phones = sorted({p for p in (_phone_or_none(r) for r in raw) if p})
        if not phones:
            plan.items.append(Item(lead_id, BAD_PHONE, detail=f"номеров {len(raw)}, ни один не разобран"))
            continue
        if len(phones) > 1:
            plan.items.append(Item(lead_id, MIXED, detail=f"{len(phones)} разных номера в одной карточке"))
            continue
        phone = phones[0]
        if not _survives_write(phone):
            plan.items.append(Item(lead_id, BAD_PHONE, phone,
                                   detail="номер не проходит повторную нормализацию при записи "
                                          "(короткий международный номер) — внести вручную"))
            continue
        others = [u for u, p in await existing.dialogs_with_lead(lead_id) if _phone_or_none(p) != phone]
        if others:
            plan.items.append(Item(lead_id, FOREIGN_DIALOG, phone, dialogs=tuple(others),
                                   detail="этот лид уже привязан к диалогу другого номера"))
            continue
        dialogs = await existing.dialogs_for(phone)
        funnels = sorted({f for _, f in dialogs if f in KNOWN_DIRECTIONS})
        by_assignee = assignee_direction.get(str(row.get("ASSIGNED_BY_ID") or ""), "")
        if len(funnels) == 1:
            direction = funnels[0]
        elif len(funnels) > 1 and by_assignee in funnels:
            direction = by_assignee
        elif len(funnels) > 1:
            plan.items.append(Item(lead_id, TWO_DIRECTIONS, phone, dialogs=tuple(u for u, _ in dialogs),
                                   detail="у номера диалоги в разных направлениях: " + ", ".join(funnels)))
            continue
        elif by_assignee in KNOWN_DIRECTIONS:
            direction = by_assignee
        else:
            plan.items.append(Item(lead_id, NO_DIRECTION, phone,
                                   detail=f"ответственный {row.get('ASSIGNED_BY_ID') or '—'} не в карте"))
            continue
        known = await existing.contact_for(phone) is not None or bool(dialogs) or phone in planned
        plan.items.append(Item(lead_id, LINK if known else CREATE, phone, direction,
                               tuple(u for u, _ in dialogs)))
        planned[phone] = planned.get(phone, 0) + 1
    return plan


async def apply_plan(sessionmaker, plan: Plan) -> dict[str, int]:
    """Записать переносимое. Каждый лид — своя транзакция; уже связанные не трогаются.

    Возвращает счётчики РЕАЛЬНЫХ изменений (второй прогон по тому же архиву обязан
    дать нули) и `failed` — пары (ID лида, класс ошибки) для отчёта."""
    from app.domain.models import ContactIdentity, ExternalReference, link_external
    from app.domain.services import ContactService, RequestService
    changes = {"contacts_created": 0, "requests_opened": 0, "references_created": 0, "errors": 0,
               "failed": []}
    for item in plan.items:
        if item.action not in (CREATE, LINK):
            continue
        async with sessionmaker() as s:
            try:
                already = await s.scalar(select(ExternalReference.id).where(
                    ExternalReference.provider == PROVIDER, ExternalReference.external_type == LEAD,
                    ExternalReference.external_id == item.lead_id, ExternalReference.active.is_(True)))
                if already is not None:
                    continue
                had = await s.scalar(select(ContactIdentity.contact_id).where(
                    ContactIdentity.identity_type == "phone",
                    ContactIdentity.normalized_value == item.phone).limit(1))
                contact = await ContactService.find_or_create_by_identity(
                    s, "phone", item.phone, assume_e164=True)
                request = await RequestService.active_for(s, contact.id, item.direction)
                opened = request is None
                if opened:
                    request = await RequestService.open(s, contact.id, item.direction)
                await link_external(s, PROVIDER, LEAD, item.lead_id, request, item.direction)
                await s.commit()
                changes["contacts_created"] += had is None
                changes["requests_opened"] += opened
                changes["references_created"] += 1
            except Exception as exc:  # noqa: BLE001 — каждый лид отдельно; повтор доделает
                # Любая ошибка записи — с ID лида и классом ошибки. Текст ошибки не берём:
                # у ошибок базы в нём параметры SQL, то есть номер клиента.
                await s.rollback()
                changes["errors"] += 1
                changes["failed"].append((item.lead_id, type(exc).__name__))
    return changes
