"""Typed HTML interview adapter. No contact details, legal decisions or source ids."""
from copy import deepcopy
from datetime import date
import re

from app.knowledge.slots import slots_schema
from app.knowledge.intake import get as profile_value

UNKNOWN = [("", "Не спрашивали"), ("unknown", "Клиент не знает")]
OPTIONAL = [*UNKNOWN, ("not_applicable", "Не применимо")]
TRI = [*OPTIONAL, ("true", "Да"), ("false", "Нет")]
DOCUMENTS = dict(ordinary="Обычный паспорт", diplomatic="Дипломатический паспорт", service="Служебный паспорт",
    un_lp="Пропуск ООН", stateless="Документ лица без гражданства", refugee="Документ беженца",
    other="Другой документ", id_card="ID-карта", internal="Внутренний паспорт", unrecognized="Непризнанный документ")
PURPOSES = dict(tourism="Туризм", private_visit="Частный визит", relatives_kg_citizen="Родственники гражданина КР",
    family_of_foreigner="Семья иностранного гражданина", business_meeting="Деловая встреча", event="Мероприятие",
    sport="Спорт", medical="Лечение", study="Учёба", work_hire="Работа по найму",
    work_individual_employer="Работа у физического лица", entrepreneur="Предпринимательство", investor="Инвестиции",
    it_remote="Удалённая работа / IT", journalism="Журналистика", volunteer="Волонтёрство",
    equipment_installation="Монтаж оборудования", transit="Транзит", religious="Религиозная деятельность",
    driver="Водитель", accompanying_gcc="Сопровождение гражданина страны Залива", official="Официальная поездка")
BASES = dict(visa_free="Безвизовое пребывание", visa="Виза", ep="Единое разрешение", resident_card="Резидент-карта",
    residence_permit="Вид на жительство", registration_contract="Регистрация по договору", none="Основания нет")


def field(path, label, kind="select", options=None, *, group="profile", **attrs):
    return {"path": path, "label": label, "kind": kind, "options": options or [], "group": group,
            "id": "kg-" + path.replace(".", "-"), **attrs}


FIELDS = [
    field("citizenship", "Гражданства", "countries"),
    field("entry_passport_country", "Паспорт какой страны используется для въезда", "country"),
    field("document_type", "Тип проездного документа", options=[*UNKNOWN, *DOCUMENTS.items()]),
    field("passport_expiry", "Срок действия документа", "date"),
    field("passport_pages_ok", "Есть свободные страницы", options=TRI),
    field("purpose", "Фактическая цель поездки", options=[*UNKNOWN, *PURPOSES.items()]),
    field("current_location", "Где клиент сейчас", options=[*UNKNOWN, ("abroad", "За рубежом"), ("in_kg", "В Кыргызстане")]),
    field("entry_date", "Планируемый въезд", "date"), field("exit_date", "Планируемый выезд", "date"),
    field("in_kg_since", "Дата фактического въезда в Кыргызстан", "date", group="current"),
    field("current_basis_in_kg", "Основание текущего пребывания", options=[*OPTIONAL, *BASES.items()], group="current"),
    field("current_visa_type", "Тип действующей визы", options=[*OPTIONAL, *[(v, v) for v in slots_schema()["$defs"]["visa_type"]["enum"]]], group="current"),
    field("current_basis_until", "Основание пребывания действует до", "date", group="current"),
    field("registration_until", "Регистрация действует до", "date", group="current"),
    field("violations.overstay", "Были нарушения срока пребывания", options=TRI, group="risks"),
    field("violations.deportation_or_ban", "Были депортация или запрет въезда", options=TRI, group="risks"),
    field("violations.ban_until", "Известная дата окончания запрета", "date", group="risks"),
    field("violations.fines", "Были штрафы", options=TRI, group="risks"),
    field("previous_refusals_kg", "Были отказы по Кыргызстану", options=TRI, group="risks"),
]
ENTRY_POINTS = dict(manas="Аэропорт Манас", osh="Аэропорт Ош", ak_jol="Ак-Жол", other_land="Другой пограничный пункт")
INVITERS = dict(company="Компания", university="Вуз", clinic="Клиника", relative_kg_citizen="Родственник — гражданин КР",
                state_body="Госорган", individual="Физическое лицо", tour_organization="Туристическая организация", other="Другая сторона")
RELATIONS = dict(spouse="Супруг / супруга", child="Ребёнок", parent="Родитель", other="Другой член семьи")
PROCESS = dict(visa="Виза / въезд", unified_permit="Единое разрешение", resident_card="Резидент-карта",
               residence_permit="Вид на жительство", regularization="Урегулирование пребывания")
FIELDS += [
    field("client_type", "Частное или корпоративное обращение", options=[*UNKNOWN, ("b2c", "Частный клиент"), ("b2b", "Компания")], group="party"),
    field("applicants_count", "Всего заявителей, включая клиента", "integer", group="party", minimum=1, maximum=200, allow_na=False),
    field("requested_process", "С чем обратился клиент", options=[*UNKNOWN, *PROCESS.items()], group="party"),
    field("purpose_details", "Подробности фактической цели", "text", max_length=1000),
    field("multiple_entries_needed", "Нужны выезды и возвращения в этой поездке", options=TRI),
    field("entry_point", "Планируемый пункт въезда", options=[*OPTIONAL, *ENTRY_POINTS.items()]),
    field("entry_point_other", "Название другого пограничного пункта", "text", max_length=100),
    field("tickets_bought", "Билеты уже куплены", options=TRI),
    field("urgency_deadline", "Жёсткая дата готовности, если есть", "date"),
    field("event_dates.from", "Начало мероприятия, если применимо", "date"),
    field("event_dates.to", "Окончание мероприятия, если применимо", "date"),
    field("in_kg_entry_point", "Пункт фактического въезда", options=[*OPTIONAL, *ENTRY_POINTS.items()], group="current"),
    field("purpose_declared_at_border", "Цель, указанная при въезде", "text", max_length=500, group="current"),
    field("previous_refusals_details", "Когда и по какому типу визы был отказ", "text", max_length=500, group="risks"),
    field("inviting_party.exists", "Есть приглашающая сторона в Кыргызстане", options=TRI, group="inviter"),
    field("inviting_party.type", "Тип приглашающей стороны", options=[*OPTIONAL, *INVITERS.items()], group="inviter"),
    field("inviting_party.can_issue_letter", "Готова выдать официальное письмо", options=TRI, group="inviter"),
    field("inviting_party.has_portal_cabinet", "Есть кабинет на портале", options=TRI, group="inviter"),
    field("inviting_party.tax_debts_absent", "Подтверждено отсутствие налоговой задолженности", options=TRI, group="inviter"),
    field("escalation.complaint", "Клиент раздражён или жалуется", options=TRI, group="conversation"),
    field("escalation.refund_question", "Клиент спрашивает о возврате денег", options=TRI, group="conversation"),
    field("escalation.legal_question", "Есть вопрос о штрафах, депортации или суде", options=TRI, group="conversation"),
    field("escalation.conflicting_answers", "В ответах клиента есть противоречие", options=TRI, group="conversation"),
]
FAMILY_LIMIT = 20  # Same bound as the source slot schema; no applicant identities here.
FAMILY_FIELDS = []
for index in range(FAMILY_LIMIT):
    prefix = f"family.{index}."
    label = f"Член семьи №{index + 1}: "
    FAMILY_FIELDS += [
        field(prefix + "relation", label + "родство", options=[("", "Не указано"), *RELATIONS.items()], group="family"),
        field(prefix + "age", label + "возраст, полных лет", "integer", group="family", minimum=0, maximum=2147483647),
        *[field(prefix + key, label + title, options=TRI, group="family") for key, title in (
            ("travels_together", "въезжает вместе с клиентом"), ("arrives_later", "приедет позже"),
            ("both_parents_travel", "ребёнок едет с обоими родителями"), ("born_in_kg", "ребёнок родился в Кыргызстане"),
            ("documents_apostilled", "документы о родстве апостилированы"))],
        field(prefix + "kg_status_of_principal", label + "статус основного члена семьи в КР", options=[*OPTIONAL,
            ("citizen", "Гражданин КР"), *[(k, BASES[k]) for k in ("ep", "resident_card", "residence_permit", "visa", "none")]], group="family"),
    ]
FIELDS += FAMILY_FIELDS
LABELS = {"profile." + f["path"]: f["label"] for f in FIELDS}
LABELS["profile.family"] = "Состав семьи и возраст детей"
STOP_LABELS = dict(special_document_review="Особый тип проездного документа", work_purpose_review="Цель связана с работой",
    passport_expired="Срок действия документа истёк", passport_pages_review="Нет свободных страниц",
    reported_overstay="Указано нарушение срока пребывания", reported_deportation_or_ban="Указаны депортация или запрет",
    reported_refusal="Указан отказ по Кыргызстану", current_basis_missing="Нет основания текущего пребывания",
    current_basis_until_passed="Срок текущего основания истёк", registration_until_passed="Срок регистрации истёк",
    planned_entry_in_past="Планируемая дата въезда уже прошла")
STOP_LABELS.update(reported_fines="Указаны штрафы в Кыргызстане", large_group_review="Более пяти заявителей",
    special_process_requested="Запрошены разрешение, статус проживания или урегулирование",
    reported_complaint="Клиент раздражён или жалуется", reported_refund_question="Вопрос о возврате денег",
    reported_legal_question="Вопрос о штрафах, депортации или суде", reported_conflicting_answers="Противоречивые ответы клиента")
FORM_FIELDS = {"language", "clear_conditions", "family_state", *(f["path"] for f in FIELDS),
               *(f["path"] + "_state" for f in FIELDS if f["kind"] in ("date", "integer"))}
MAX_LENGTHS = {f["path"]: f.get("max_length", 128) for f in FIELDS}


class FormInvalid(ValueError):
    """Message contains only fixed UI text and known field labels."""


def values_from_request(request):
    values = {"language": request.get("language", "ru"), "clear_conditions": "", "citizenship": []}
    profile = request.get("profile", {})
    family = profile.get("family")
    values["family_state"] = ("value" if family else "none") if isinstance(family, list) else family or ""
    for f in FIELDS:
        path = f["path"]
        value = profile_value(profile, path)
        if f["kind"] in ("date", "integer"):
            state = "value" if value is not None and value not in ("unknown", "not_applicable", "") else value or ""
            values[path + "_state"] = state
            values[path] = str(value) if state == "value" else ""
        elif f["kind"] == "countries":
            values[path] = list(value) if isinstance(value, list) else [value] if value else []
        else:
            values[path] = "true" if value is True else "false" if value is False else value or ""
    return values


def request_from_values(values, *, as_of, base_request):
    profile = {}
    family_rows = [{} for _ in range(FAMILY_LIMIT)]
    family_state = values.get("family_state", "")
    if family_state not in ("", "unknown", "not_applicable", "none", "value"):
        raise FormInvalid("Выберите состояние сведений о семье.")
    for f in FIELDS:
        path = f["path"]
        if f["group"] == "family" and family_state != "value":
            continue
        value = values.get(path, [] if f["kind"] == "countries" else "")
        if f["kind"] in ("date", "integer"):
            state = values.get(path + "_state", "")
            if state == "value":
                try:
                    if f["kind"] == "date":
                        if date.fromisoformat(value).isoformat() != value:
                            raise ValueError
                    else:
                        if not re.fullmatch(r"0|[1-9][0-9]{0,9}", value):
                            raise ValueError
                        value = int(value)
                        if not f["minimum"] <= value <= f["maximum"]:
                            raise ValueError
                except (ValueError, TypeError):
                    raise FormInvalid("Укажите корректное значение: " + f["label"] + ".") from None
            elif state in ("", "unknown", "not_applicable"):
                value = state
            else:
                raise FormInvalid("Выберите состояние значения: " + f["label"] + ".")
        elif f["kind"] == "text":
            value = value.replace("\r\n", "\n").strip()
            if len(value) > f["max_length"]:
                raise FormInvalid("Сократите ответ: " + f["label"] + ".")
        elif f["kind"] == "countries":
            value = [v for v in value if v]
            if "unknown" in value:
                if value != ["unknown"]:
                    raise FormInvalid("Выберите гражданства или ответ «Клиент не знает».")
                value = "unknown"
        if value == "" or value == []:
            continue
        if f["options"]:
            if value not in dict(f["options"]):
                raise FormInvalid("Выберите допустимый ответ: " + f["label"] + ".")
            if value in ("true", "false"):
                value = value == "true"
        if path.startswith("family."):
            _, number, key = path.split(".")
            family_rows[int(number)][key] = value
        elif "." in path:
            parent, key = path.split(".")
            profile.setdefault(parent, {})[key] = value
        else:
            profile[path] = value
    if family_state == "value":
        members = [row for row in family_rows if row]
        if not members or any(not row.get("relation") for row in members):
            raise FormInvalid("Укажите родство для каждого заполненного члена семьи.")
        profile["family"] = members
    elif family_state:
        profile["family"] = [] if family_state == "none" else family_state
    if profile.get("current_location") == "abroad":
        for f in FIELDS:
            if f["group"] == "current":
                profile.pop(f["path"], None)
    if profile.get("current_basis_in_kg") in set(BASES) - {"visa"}:
        profile.pop("current_visa_type", None)
    if profile.get("entry_point") != "other_land":
        profile.pop("entry_point_other", None)
    if profile.get("previous_refusals_kg") is False:
        profile.pop("previous_refusals_details", None)
    if profile.get("inviting_party", {}).get("exists") is False:
        profile["inviting_party"] = {"exists": False}
    result = {"format": "kg-qualification-review-input/2", "as_of": as_of,
              "language": values.get("language", "ru"), "profile": profile}
    if "condition_facts" in base_request and values.get("clear_conditions") != "yes":
        result["condition_facts"] = deepcopy(base_request["condition_facts"])
    return result


def country_options(aliases):
    labels = {code: code for code in aliases.values()}
    for alias, code in aliases.items():
        if any("а" <= c.lower() <= "я" for c in alias) and len(alias) > len(labels[code]):
            labels[code] = alias
    return sorted(((code, f"{label} ({code})" if label != code else code) for code, label in labels.items()),
                  key=lambda row: row[1])


def report_view(report):
    history_labels = {"history_incomplete": "Полнота истории поездок не подтверждена.",
                      "history_unconfirmed": "Есть неподтверждённые поездки.",
                      "history_cutoff_differs": "История поездок составлена на другую дату; нужна сверка."}
    return {"status": {"needs_input": "Нужно уточнить сведения", "manager_review": "Нужна проверка менеджером",
                       "knowledge_review": "Анкета собрана для проверки правил"}.get(report["status"], "Нужна проверка"),
            "questions": report["next_questions"],
            "missing": [LABELS.get(k, "Дополнительные сведения") for k in report["missing_facts"]],
            "stops": [STOP_LABELS.get(k, "Дополнительная проверка") for k in report["stop_reasons"]],
            "conflict": "source_conflict" in report["blockers"],
            "history_attached": report["history"].get("status") == "integrity_checked",
            "history_notes": [message for code, message in history_labels.items() if code in report["blockers"]],
            "conditions_missing": bool(report["specialist_missing_facts"])}
