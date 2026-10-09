"""Typed HTML interview adapter. No contact details, legal decisions or source ids."""
from copy import deepcopy
from datetime import date

from app.knowledge.slots import slots_schema

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


def field(path, label, kind="select", options=None, *, group="profile"):
    return {"path": path, "label": label, "kind": kind, "options": options or [], "group": group,
            "id": "kg-" + path.replace(".", "-")}


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
LABELS = {"profile." + f["path"]: f["label"] for f in FIELDS}
STOP_LABELS = dict(special_document_review="Особый тип проездного документа", work_purpose_review="Цель связана с работой",
    passport_expired="Срок действия документа истёк", passport_pages_review="Нет свободных страниц",
    reported_overstay="Указано нарушение срока пребывания", reported_deportation_or_ban="Указаны депортация или запрет",
    reported_refusal="Указан отказ по Кыргызстану", current_basis_missing="Нет основания текущего пребывания",
    current_basis_until_passed="Срок текущего основания истёк", registration_until_passed="Срок регистрации истёк",
    planned_entry_in_past="Планируемая дата въезда уже прошла")
FORM_FIELDS = {"language", "clear_conditions", *(f["path"] for f in FIELDS),
               *(f["path"] + "_state" for f in FIELDS if f["kind"] == "date")}


class FormInvalid(ValueError):
    """Message contains only fixed UI text and known field labels."""


def values_from_request(request):
    values = {"language": request.get("language", "ru"), "clear_conditions": "", "citizenship": []}
    profile = request.get("profile", {})
    for f in FIELDS:
        path = f["path"]
        value = profile.get(path) if "." not in path else profile.get("violations", {}).get(path.split(".")[1])
        if f["kind"] == "date":
            state = "value" if value and value not in ("unknown", "not_applicable") else value or ""
            values[path + "_state"] = state
            values[path] = value if state == "value" else ""
        elif f["kind"] == "countries":
            values[path] = list(value) if isinstance(value, list) else [value] if value else []
        else:
            values[path] = "true" if value is True else "false" if value is False else value or ""
    return values


def request_from_values(values, *, as_of, base_request):
    profile = {}
    for f in FIELDS:
        path = f["path"]
        value = values.get(path, [] if f["kind"] == "countries" else "")
        if f["kind"] == "date":
            state = values.get(path + "_state", "")
            if state == "value":
                try:
                    if date.fromisoformat(value).isoformat() != value:
                        raise ValueError
                except (ValueError, TypeError):
                    raise FormInvalid("Укажите корректную дату: " + f["label"] + ".") from None
            elif state in ("", "unknown", "not_applicable"):
                value = state
            else:
                raise FormInvalid("Выберите состояние даты: " + f["label"] + ".")
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
        if "." in path:
            profile.setdefault("violations", {})[path.split(".")[1]] = value
        else:
            profile[path] = value
    if profile.get("current_location") == "abroad":
        for f in FIELDS:
            if f["group"] == "current":
                profile.pop(f["path"], None)
    if profile.get("current_basis_in_kg") in set(BASES) - {"visa"}:
        profile.pop("current_visa_type", None)
    result = {"format": "kg-qualification-review-input/1", "as_of": as_of,
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
