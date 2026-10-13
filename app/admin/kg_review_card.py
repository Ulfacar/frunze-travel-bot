"""Human-readable review card, using existing interview labels and pinned facts."""
from app.admin.kg_entry_form import FIELDS, country_options, report_view, values_from_request
from app.knowledge.intake import known
from app.admin.kg_history_form import BASES as HISTORY_BASES, EVIDENCE as HISTORY_EVIDENCE, history_overlaps


BLOCKERS = {
    "publication_not_approved": "Правила базы ещё не утверждены для ответа клиенту.",
    "eligibility_not_evaluated": "Право въезда по этим сведениям не определено.",
    "stay_calculation_required": "Допустимый срок пребывания требует отдельного расчёта.",
    "registration_review_required": "Обязанность и срок регистрации требуют проверки.",
    "condition_catalog_missing": "Набор специальных условий не загружен.",
    "multiple_candidates_require_review": "Найдено несколько вариантов правил; специалист должен сверить применимость.",
    "source_conflict": "В источниках есть противоречие.",
    "no_candidate_resolved": "Подходящее правило не определено.",
    "history_not_attached": "История поездок не приложена.",
    "history_incomplete": "Полнота истории поездок не подтверждена.",
    "history_unconfirmed": "В истории есть неподтверждённые поездки.",
    "history_cutoff_differs": "История поездок составлена на другую дату.",
}
FINDINGS = {
    "source_conflict": "противоречие источников", "not_confirmed": "правило не подтверждено",
    "value_missing": "есть незаполненные значения", "unresolved_evidence": "есть нерешённые вопросы",
    "owner_unassigned": "не назначен ответственный за правило", "verification_missing": "нет отметки проверки",
    "effective_from_unknown": "неизвестно начало действия", "review_due_unknown": "не назначена следующая проверка",
}


def _display(field, values, countries):
    value = values.get(field["path"], "")
    if field["kind"] in ("date", "integer"):
        state = values.get(field["path"] + "_state", "")
        return value if state == "value" else {"unknown": "Клиент не знает",
            "not_applicable": "Не применимо"}.get(state, "Не спрашивали")
    if field["kind"] == "text":
        return value or "Не спрашивали"
    labels = {"": "Не спрашивали", "unknown": "Клиент не знает", "not_applicable": "Не применимо"}
    if field["kind"] in ("country", "countries"):
        labels.update(countries)
        items = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(item, item) for item in items) if items else "Не спрашивали"
    return dict(field["options"]).get(value, "Значение требует проверки")


def _condition_groups(facts, countries):
    """Show attached specialist facts, including incomplete and empty inventories."""
    def row(source, key, label, options=None):
        if key not in source:
            value = "Не спрашивали"
        elif source[key] is None:
            value = "Неизвестно"
        elif source[key] is True or source[key] is False:
            value = "Да" if source[key] else "Нет"
        else:
            value = {"unknown": "Клиент не знает", **(options or {})}.get(source[key], str(source[key]))
        return {"label": label, "value": value}

    groups = []
    for key, title in (("residence_documents", "Документы на проживание за рубежом"),
                       ("foreign_visas", "Иностранные визы")):
        if key not in facts:
            continue
        inventory = facts[key]
        rows = [row(inventory, "complete", "Клиент перечислил все документы"),
                {"label": "Документов в сохранённом списке", "value": str(len(inventory["items"]))}]
        for number, item in enumerate(inventory["items"], 1):
            prefix = f"Документ {number}: "
            if key == "residence_documents":
                rows += [row(item, "country", prefix + "страна", countries),
                         row(item, "kind", prefix + "тип", {"residence_permit": "Вид на жительство",
                             "resident_card": "Резидент-карта", "other": "Другой документ"}),
                         row(item, "permanent", prefix + "постоянное проживание")]
            else:
                rows += [row(item, "issuer", prefix + "кем выдан", {"USA": "США", "GBR": "Великобритания",
                             "SCHENGEN": "Шенген", "other": "Другой орган"}),
                         row(item, "over_three_years_verified", prefix + "проверен срок действия свыше трёх лет")]
        groups.append({"title": title, "rows": rows})
    if "tour_group" in facts:
        group = facts["tour_group"]
        groups.append({"title": "Сведения о туристической группе", "rows": [
            row(group, "organized", "Организованная группа"),
            row(group, "participants_count", "Число участников"),
            row(group, "all_members_country", "Общее гражданство участников", countries),
            row(group, "tourism_authority_petition", "Есть ходатайство уполномоченного органа по туризму")]})
    groups.append({"title": "Другие сведения для проверки условий", "rows": [
        row(facts, "requested_visa_type", "Запрошенный тип визы"),
        row(facts, "stay_within_one_month_verified", "Проверено пребывание в пределах одного месяца")]})
    return groups


def card_view(card):
    saved = card["saved"]
    result = saved["result"]
    profile = saved["input"]["profile"]
    values = values_from_request(saved["input"])
    countries = dict(country_options(card["countries"]))
    groups = []
    for key, title in (("party", "Обращение и заявители"), ("profile", "Документ и поездка"),
                       ("current", "Текущее пребывание в Кыргызстане"), ("inviter", "Приглашающая сторона"),
                       ("risks", "Нарушения и отказы"), ("conversation", "Поводы для проверки специалистом")):
        if key == "current" and profile.get("current_location") == "abroad":
            continue
        if key == "conversation" and not profile.get("escalation"):
            continue
        if key == "inviter" and not profile.get("inviting_party") and profile.get("purpose") in ("tourism", "transit"):
            continue
        groups.append({"title": title, "rows": [{"label": f["label"], "value": _display(f, values, countries)}
                                               for f in FIELDS if f["group"] == key]})
    family = profile.get("family")
    if isinstance(family, list) and family:
        for index in range(len(family)):
            prefix = f"family.{index}."
            groups.append({"title": f"Член семьи №{index + 1}", "rows": [
                {"label": f["label"], "value": _display(f, values, countries)} for f in FIELDS if f["path"].startswith(prefix)]})
    else:
        label = "Члены семьи не едут" if family == [] else {"unknown": "Клиент не знает", "not_applicable": "Не применимо"}.get(family, "Не спрашивали")
        groups.append({"title": "Семья", "rows": [{"label": "Состав семьи", "value": label}]})

    # PDF 3.4 has more requirements than the partial-profile form. Do not mark
    # handoff complete merely because this form has no missing_facts remaining.
    gaps = ["Режим въезда, рекомендуемый продукт и альтернативы — после проверки специалистом."]
    if not known(profile.get("client_type")) or not known(profile.get("applicants_count")):
        gaps.append("Личная, семейная, групповая или корпоративная заявка (A5).")
    if not isinstance(family, list):
        gaps.append("Состав семьи и группы, отдельные заявители (G1).")
    purpose = profile.get("purpose")
    inviter = profile.get("inviting_party", {})
    if purpose not in ("tourism", "transit") and not known(inviter.get("exists")):
        gaps.append("Приглашающая сторона (F1): уточнить после подтверждения цели поездки." if purpose in (None, "unknown")
                    else "Наличие и сведения приглашающей стороны (F1).")
    if inviter.get("exists") is True:
        gaps.append("Реквизиты и контакт приглашающей стороны (F2) — для дальнейшего оформления.")
    if profile.get("current_location") == "in_kg" and not known(profile.get("in_kg_entry_point")):
        gaps.append("Пункт фактического въезда в Кыргызстан (B8).")
    if profile.get("previous_refusals_kg") is True and not profile.get("previous_refusals_details", "").strip():
        gaps.append("Даты и типы прежних отказов по Кыргызстану (D4).")
    if profile.get("violations", {}).get("fines") in (None, "unknown", "not_applicable"):
        gaps.append("Сведения о штрафах (D3).")

    sources = []
    for kind, rows in (("Правило въезда", result["candidate_rules"]),
                       ("Регистрация", result["registration_rules"])):
        for row in rows:
            sources.append({"kind": kind, "id": row["unit_id"], **row["source"],
                            "notes": [FINDINGS.get(f, "Требует дополнительной проверки") for f in row["findings"]]})
    history = card.get('stay_history')
    history_rows = []
    if history:
        for item in history['document']['intervals']:
            history_rows.append({'entry': item['entry_date'], 'exit': item['exit_date'] or 'Ещё в Кыргызстане на дату истории',
                'basis': HISTORY_BASES.get(item['basis'], 'Не установлено'),
                'country': countries.get(item['passport_country'], item['passport_country']) or 'Не установлено',
                'evidence': HISTORY_EVIDENCE[item['evidence']], 'confirmed': 'Проверена' if item['confirmed'] else 'Требует проверки'})
    return {"groups": groups, "report": report_view(result), "gaps": gaps, "sources": sources,
            'history_rows': history_rows, 'history_overlaps': history_overlaps(history['document']) if history else False,
            "blockers": [BLOCKERS.get(b, "Дополнительная проверка источника или расчёта.") for b in result["blockers"]],
            "specialist_count": len(result["specialist_missing_facts"]),
            "condition_groups": _condition_groups(saved["input"]["condition_facts"], countries)
                                if "condition_facts" in saved["input"] else []}
