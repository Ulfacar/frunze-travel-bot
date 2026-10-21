"""Движок режима въезда в Кыргызстан. Чистые функции, без БД и без LLM.

ТЗ требует этого прямо (с. 2, «что куда загружать»): «Проверка кодом режима въезда —
Б.5». Модель не считает лимиты дней и сроки регистрации — она только пересказывает то,
что вычислил этот модуль, и только то, что разрешено произносить.

Устройство ответа. `evaluate` возвращает не «да/нет», а четыре разных вещи сразу:
что вычислено (`regime`, `stay_limit_days`, …), из чего вычислено (`units` с основанием
и страницей ТЗ), **что из этого можно сказать клиенту** (`sayable`) и почему остальное
нельзя (`withheld`). Такая форма нужна, потому что подтверждение единиц приходит
неравномерно: режим для австрийца подтвердят раньше, чем 93 единицы освобождения от
регистрации. С одним флагом «можно/нельзя» бот замолчал бы целиком; с множеством полей
он честно скажет режим и лимит, а срок регистрации оставит менеджеру.

Три жёстких запрета, зашитых здесь, а не в промпте:

1. **Точный остаток дней клиенту не называется никогда.** ТЗ 2.9: «точный остаток дней
   клиенту не обещать по расчёту в уме», считает его государственная система ЕСУВМ,
   доступа к ней нет, а политика подсчёта (считать ли день въезда и выезда) в данных не
   подтверждена. Клиенту — лимит из самой единицы («90 дней в окне 180»).
2. **Метка сильнее подтверждения.** Единица с `label` в `{verify, decision}` не
   произносится даже после подтверждения человеком: так ТЗ помечает сведения, которые
   само считает непроверенными (например 60/120 по Таджикистану, Азербайджану и Грузии —
   известно «по сообщениям СМИ»).
3. **Особый режим и необычный паспорт — всегда человек.** Все четыре единицы
   `special_regime` имеют пустое значение; дипломатический паспорт, документ ООН, статус
   беженца и апатрида — стоп-факторы 4.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Regime = Literal["visa_free", "visa_required", "special", "unknown"]

# Поля, которые бот в принципе может произнести. Остальное — только менеджеру.
FIELDS = ("regime", "stay_limit", "registration", "unified_permit")

# Документы, по которым бот не консультирует по существу (стоп-фактор 4.1).
HUMAN_ONLY_DOCUMENTS = frozenset({
    "diplomatic", "service", "un_lp", "stateless", "refugee", "other",
    "id_card", "internal",
})

# Метки ТЗ, которые запрещают произносить факт. `verify` = [ПРОВЕРИТЬ],
# `decision` = [РЕШЕНИЕ] (последнее клиенту не озвучивается вообще).
UNSAYABLE_LABELS = frozenset({"verify", "decision"})


@dataclass(frozen=True)
class UnitRef:
    """Единица знаний, на которой держится вывод, — вместе с основанием."""
    unit_id: str
    kind: str
    label: str
    confirmation_status: str
    section: str
    page: str
    source_ref: str


@dataclass(frozen=True)
class RegistrationTerm:
    """Либо освобождение на N дней, либо срок постановки на учёт в рабочих днях."""
    exempt_days: int | None = None
    working_days_from_border: int | None = None
    registered_for_days: int | None = None


@dataclass(frozen=True)
class EntryQuery:
    citizenship_iso3: str
    document_type: str = "ordinary"
    purpose: str | None = None
    entry_on: str | None = None
    exit_on: str | None = None
    location: str | None = None                      # abroad | in_kg
    history: tuple[tuple[str, str], ...] = ()        # пары (въезд, выезд)


@dataclass(frozen=True)
class EntryVerdict:
    regime: Regime = "unknown"
    stay_limit_days: int | None = None
    window_days: int | None = None
    registration: RegistrationTerm | None = None
    unified_permit_required: bool | None = None
    gknb_approval: bool | None = None
    units: tuple[UnitRef, ...] = ()
    sayable: frozenset[str] = frozenset()
    withheld: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())


def available() -> bool:
    """Есть ли бандл знаний. False — движок отвечает «не знаю» на всё."""
    from app.knowledge.entry_bundle import loaded
    return loaded() is not None


def resolve_citizenship(text: str) -> str | None:
    """Строка от клиента → ISO3. Сначала английский слой, потом алиасы бандла."""
    if not text or not str(text).strip():
        return None
    from app.knowledge.country_aliases_en import iso3_for_en
    from app.knowledge.entry_bundle import loaded

    iso = iso3_for_en(str(text))
    if iso:
        return iso
    bundle = loaded()
    if bundle is None:
        return None
    found = bundle.index.lookup(str(text).strip())
    return found.get("country_iso3") if found.get("status") == "found" else None


def _ref(unit: dict[str, Any]) -> UnitRef:
    return UnitRef(unit_id=str(unit.get("unit_id") or ""),
                   kind=str(unit.get("kind") or ""),
                   label=str(unit.get("label") or ""),
                   confirmation_status=str(unit.get("confirmation_status") or ""),
                   section=str(unit.get("section") or ""),
                   page=str(unit.get("page") or ""),
                   source_ref=str(unit.get("source_ref") or ""))


def _sayable(unit: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Можно ли произнести эту единицу как факт. Второе — причина отказа."""
    if unit is None:
        return False, "unit_missing"
    uid = unit.get("unit_id") or "?"
    if unit.get("value") is None:
        return False, f"value_missing:{uid}"
    if str(unit.get("label") or "") in UNSAYABLE_LABELS:
        # Метка ТЗ сильнее любого нашего подтверждения.
        return False, f"source_label_{unit.get('label')}:{uid}"
    if unit.get("conflict_ref"):
        return False, f"source_conflict:{uid}"
    from app.knowledge import entry_confirmations
    if not entry_confirmations.confirmed(unit):
        return False, f"not_confirmed:{uid}"
    return True, None


def _scope_allows(unit: dict[str, Any], purpose: str | None) -> bool:
    """Упрощённый порядок Ирана действует только для деловой и туристической цели."""
    scope = str((unit.get("value") or {}).get("scope") or "all_types")
    if scope == "all_types":
        return True
    if scope == "business_tourist":
        if purpose is None:
            return True            # цель не названа — правило ещё может подойти
        return purpose in ("tourism", "business_meeting", "private_visit", "event")
    return False


def _registration(links: dict[str, list], iso3: str,
                  withheld: list[str], units: list[UnitRef]) -> tuple[RegistrationTerm | None, set[str]]:
    """Срок регистрации: освобождение по стране, иначе общий срок, иначе пробел."""
    ok_fields: set[str] = set()
    exempt = next(iter(links.get("registration_exemption") or []), None)
    term = next(iter(links.get("registration_term") or []), None)
    default = next(iter(links.get("registration_default") or []), None)

    registered_for = None
    if term is not None:
        units.append(_ref(term))
        registered_for = (term.get("value") or {}).get("days")

    if exempt is not None and (exempt.get("value") or {}).get("days") is not None:
        units.append(_ref(exempt))
        can, why = _sayable(exempt)
        if can:
            ok_fields.add("registration")
        elif why:
            withheld.append(why)
        return RegistrationTerm(exempt_days=(exempt["value"]["days"]),
                                registered_for_days=registered_for), ok_fields

    if default is not None:
        value = default.get("value") or {}
        if iso3 in set(value.get("not_in_list") or ()):
            units.append(_ref(default))
            can, why = _sayable(default)
            if can:
                ok_fields.add("registration")
            elif why:
                withheld.append(why)
            return RegistrationTerm(
                working_days_from_border=value.get("deadline_working_days_from_border"),
                registered_for_days=registered_for), ok_fields

    # Ни освобождения, ни попадания в общий список: по этой стране данных нет.
    # Так выглядит Молдова, по которой ТЗ противоречит сам себе.
    withheld.append(f"registration_coverage_missing:{iso3}")
    if exempt is not None:
        units.append(_ref(exempt))
    return (RegistrationTerm(registered_for_days=registered_for)
            if registered_for is not None else None), ok_fields


def evaluate(query: EntryQuery) -> EntryVerdict:
    """Режим въезда по гражданству, типу документа и цели. Никогда не бросает."""
    from app.knowledge.entry_bundle import loaded

    bundle = loaded()
    if bundle is None:
        return EntryVerdict(withheld=("knowledge_unavailable",))

    iso3 = (query.citizenship_iso3 or "").strip().upper()
    if not iso3:
        return EntryVerdict(withheld=("citizenship_unknown",))

    if query.document_type in HUMAN_ONLY_DOCUMENTS:
        # Стоп-фактор 4.1: бот не консультирует по существу, сразу человек.
        return EntryVerdict(withheld=(f"document_review_required:{query.document_type}",))

    found = bundle.index.lookup(iso3, document_type=query.document_type or "ordinary")
    if found.get("status") != "found":
        return EntryVerdict(withheld=(f"unknown_country:{iso3}",))

    links = found.get("country_links") or {}
    withheld: list[str] = []
    units: list[UnitRef] = []
    ok_fields: set[str] = set()

    # Особый режим (Гонконг/Макао, документ ООН, короткий безвиз для КНР и Индии при
    # долгосрочной визе США/UK/Шенгена) — решаем не мы. Все четыре единицы пустые.
    special = next(iter(links.get("special_regime") or []), None)
    if special is not None:
        units.append(_ref(special))
        return EntryVerdict(regime="special", units=tuple(units),
                            withheld=(f"special_regime_review_required:{iso3}",))

    regime: Regime = "unknown"
    stay_limit = window = None
    permit = gknb = None

    free = next(iter(links.get("visa_free_regime") or []), None)
    if free is not None and (free.get("value") or {}).get("days") is not None:
        regime = "visa_free"
        value = free["value"]
        stay_limit, window = value.get("days"), value.get("window_days")
        permit = value.get("work_needs_unified_permit")
        units.append(_ref(free))
        can, why = _sayable(free)
        if can:
            ok_fields |= {"regime", "stay_limit", "unified_permit"}
        elif why:
            withheld.append(why)
    else:
        # Единица без значения ничего определить не может. У Индии, например, привязано
        # правило об упрощённом порядке для резидентов Залива (`value: null`): по ТЗ это
        # повод ЗАДАТЬ вопрос про ВНЖ Залива, а не вывод о режиме. Поэтому такие единицы
        # пропускаем и падаем в общий порядок, но отмечаем — менеджер должен знать, что
        # по этой стране есть неразрешённый особый случай.
        linked = links.get("visa_required_regime") or []
        for skipped in linked:
            if (skipped.get("value") or {}).get("procedure") is None:
                withheld.append(f"special_case_unresolved:{skipped.get('unit_id')}")
                units.append(_ref(skipped))
        required = [u for u in linked
                    if (u.get("value") or {}).get("procedure") is not None
                    and _scope_allows(u, query.purpose)]
        if not required:
            # «Все остальные» — общий порядок с согласованием ГКНБ (KG.VR.GENERAL).
            required = [u for u in (found.get("source_fallbacks") or [])
                        if u.get("kind") == "visa_required_regime"
                        and (u.get("value") or {}).get("countries") == "all_others"]
        pick = next(iter(required), None)
        if pick is not None:
            regime = "visa_required"
            gknb = (pick.get("value") or {}).get("gknb_approval")
            units.append(_ref(pick))
            can, why = _sayable(pick)
            if can:
                ok_fields.add("regime")
            elif why:
                withheld.append(why)
        else:
            withheld.append(f"regime_coverage_missing:{iso3}")

    registration, reg_ok = _registration(links, iso3, withheld, units)
    ok_fields |= reg_ok

    # Остаток дней не произносится никогда — см. запрет 1 в docstring модуля.
    notes: list[str] = []
    if regime == "visa_free" and query.entry_on and (query.history or query.exit_on):
        notes.append("stay_window_check_required_by_manager")

    if regime == "unknown":
        ok_fields = set()

    return EntryVerdict(regime=regime, stay_limit_days=stay_limit, window_days=window,
                        registration=registration, unified_permit_required=permit,
                        gknb_approval=gknb, units=tuple(units),
                        sayable=frozenset(ok_fields & set(FIELDS)),
                        withheld=tuple(dict.fromkeys(withheld)), notes=tuple(notes))
