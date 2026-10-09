"""Факты расширенной анкеты PDF 3.3/3.4 и наблюдаемые причины проверки Б.6."""
UNKNOWN = (None, "unknown", "not_applicable", "")


def get(profile, path):
    value = profile
    for part in path.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and part.isdecimal() and int(part) < len(value):
            value = value[int(part)]
        else:
            return None
    return value


def known(value):
    return value not in UNKNOWN


def review_intake(profile):
    """Called only after v2 schema validation. No policy/eligibility or deadline math."""
    p = profile
    family = p.get("family")
    inviter = p.get("inviting_party", {})
    count = p.get("applicants_count")
    if isinstance(family, list):
        if type(count) is int and count < len(family) + 1:
            raise ValueError("family_exceeds_applicants")
        if any(r.get("travels_together") is True and r.get("arrives_later") is True for r in family):
            raise ValueError("family_travel_conflict")
    if inviter.get("exists") is False and any(known(v) for k, v in inviter.items() if k != "exists"):
        raise ValueError("inviter_absence_conflict")
    if p.get("current_location") == "abroad" and any(known(p.get(k)) for k in ("in_kg_entry_point", "purpose_declared_at_border")):
        raise ValueError("location_basis_conflict")
    event = p.get("event_dates", {})
    if known(event.get("from")) and known(event.get("to")) and event["to"] < event["from"]:
        raise ValueError("event_date_order")

    questions = []
    def need(path, step, ru, en):
        value = get(p, path)
        if not known(value) or isinstance(value, str) and not value.strip():
            questions.append({"path": "profile." + path, "step": step, "ru": ru, "en": en})

    need("client_type", 4, "Обращаетесь как частный клиент или от компании?", "Are you applying privately or on behalf of a company?")
    need("applicants_count", 4, "Сколько всего заявителей, включая вас?", "How many applicants are there in total, including you?")
    purpose = p.get("purpose")
    if known(purpose) and purpose not in ("tourism", "transit"):
        need("purpose_details", 4, "Уточните, что вы планируете делать в Кыргызстане.", "Please describe what you plan to do in Kyrgyzstan.")
        need("inviting_party.exists", 4, "Есть ли у вас приглашающая сторона в Кыргызстане?", "Do you have an inviting party in Kyrgyzstan?")
    if inviter.get("exists") is True:
        need("inviting_party.type", 4, "Кто вас приглашает: компания, вуз, клиника, родственник или другая сторона?", "Who is inviting you: a company, university, clinic, relative or another party?")
        need("inviting_party.can_issue_letter", 4, "Готова ли приглашающая сторона выдать официальное письмо?", "Can the inviting party issue an official invitation letter?")
        need("inviting_party.has_portal_cabinet", 4, "Есть ли у приглашающей стороны кабинет на портале?", "Does the inviting party have a portal account?")
        if purpose in ("study", "work_hire", "work_individual_employer", "entrepreneur", "equipment_installation"):
            need("inviting_party.tax_debts_absent", 4, "Подтверждено ли отсутствие налоговой задолженности у приглашающей стороны?", "Has the inviting party confirmed that it has no tax arrears?")
    need("multiple_entries_needed", 5, "Планируете выезжать из Кыргызстана и возвращаться в этой поездке?", "Will you leave Kyrgyzstan and return during this trip?")
    need("tickets_bought", 5, "Билеты уже куплены?", "Have you already bought your tickets?")
    need("entry_point", 5, "Через какой аэропорт или пограничный пункт планируете въезд?", "Which airport or border crossing will you use to enter?")
    if p.get("entry_point") == "other_land":
        need("entry_point_other", 5, "Как называется этот пограничный пункт?", "What is the name of that border crossing?")
    if p.get("current_location") == "in_kg":
        need("in_kg_entry_point", 5, "Через какой пункт вы фактически въехали в Кыргызстан?", "Which crossing did you actually use to enter Kyrgyzstan?")
        need("purpose_declared_at_border", 5, "Какую цель поездки вы указали при въезде?", "What purpose did you state at the border?")
    need("violations.fines", 6, "Были ли у вас штрафы в Кыргызстане?", "Have you had any fines in Kyrgyzstan?")
    if p.get("previous_refusals_kg") is True:
        need("previous_refusals_details", 6, "Когда и по какому типу визы Кыргызстана был отказ?", "When were you refused a Kyrgyzstan visa, and what visa type was it?")
    need("family", 7, "Едут ли с вами члены семьи? Укажите родство и возраст детей.", "Are any family members travelling with you? Please specify their relationship and the children's ages.")
    if isinstance(family, list):
        for i, member in enumerate(family):
            prefix = f"family.{i}."
            number = i + 1
            if member["relation"] == "child":
                need(prefix + "age", 7, f"Сколько лет ребёнку №{number}?", f"How old is child #{number}?")
                need(prefix + "both_parents_travel", 7, f"Ребёнок №{number} едет с обоими родителями?", f"Is child #{number} travelling with both parents?")
            need(prefix + "travels_together", 7, f"Член семьи №{number} въезжает вместе с вами?", f"Is family member #{number} entering with you?")
            if member.get("travels_together") is False:
                need(prefix + "arrives_later", 7, f"Член семьи №{number} приедет позже?", f"Will family member #{number} arrive later?")

    stops = []
    if p.get("violations", {}).get("fines") is True:
        stops.append("reported_fines")
    if type(count) is int and count > 5:
        stops.append("large_group_review")
    if p.get("requested_process") in ("unified_permit", "resident_card", "residence_permit", "regularization"):
        stops.append("special_process_requested")
    for key in ("complaint", "refund_question", "legal_question", "conflicting_answers"):
        if p.get("escalation", {}).get(key) is True:
            stops.append("reported_" + key)
    return {"questions": questions, "stops": stops}
