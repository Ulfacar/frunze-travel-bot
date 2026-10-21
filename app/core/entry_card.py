"""Карточка передачи менеджеру по въездному лиду — формат приложения Б.4 ТЗ.

Двенадцать строк, заданных ТЗ дословно. Карточка существует потому, что бот по въездным
визам сознательно не доводит сделку: он квалифицирует и отдаёт человеку. Значит всё, что
он понял, должно уехать менеджеру в одном читаемом виде, иначе разговор придётся вести
заново и клиент это почувствует.

Два отличия от буквы ТЗ, оба осознанные:

- **Ориентир стоимости не заполняется.** ТЗ (Б.1) разрешает боту называть ориентир из
  блока 12, но приложение Г п.2 того же ТЗ ставит фактическим суммам e-Visa статус
  «Открыт»: на портале нет ни прайса, ни калькулятора, суммы снимаются только со шага
  оплаты живой заявки. Владелец 21.10 решил: бот цен не называет. В карточке стоит
  явная отметка, а не пустое место — чтобы менеджер видел, что это решение, а не сбой.
- **Остаток дней — только как пометка «проверить по штампам».** ТЗ 2.9 запрещает
  обещать остаток расчётом, считает его государственная система ЕСУВМ, доступа нет.

Чистый модуль: ни БД, ни сети. Рендер строки — отдельно от сбора данных, чтобы его можно
было проверить построчно против PDF.
"""
from __future__ import annotations

from typing import Any

NOT_QUOTED = "не называется (решение владельца; фактических сумм портала нет)"
UNKNOWN = "не выяснено"

# Человеческие названия типов документа из схемы Б.3.
DOCUMENT_LABELS = {
    "ordinary": "обычный", "diplomatic": "дипломатический", "service": "служебный",
    "un_lp": "документ ООН", "stateless": "апатрид", "refugee": "беженец",
    "id_card": "ID-карта", "internal": "внутренний паспорт", "other": "иной",
}

REGIME_LABELS = {
    "visa_free": "безвиз", "visa_required": "виза", "special": "особый режим",
    "unknown": "не определён",
}

PURPOSE_LABELS = {
    "tourism": "туризм", "private_visit": "частный визит",
    "relatives_kg_citizen": "родственники — граждане КР",
    "family_of_foreigner": "семья иностранца", "business_meeting": "деловая встреча",
    "event": "мероприятие", "sport": "спорт", "medical": "лечение", "study": "учёба",
    "work_hire": "работа по найму", "work_individual_employer": "работа у физлица",
    "entrepreneur": "предпринимательство", "investor": "инвестиции",
    "it_remote": "удалённая работа в IT", "journalism": "журналистика",
    "volunteer": "волонтёрство", "equipment_installation": "монтаж оборудования",
    "transit": "транзит", "religious": "религиозная деятельность", "driver": "водитель",
    "accompanying_gcc": "сопровождение", "official": "официальный визит",
}


def _regime_line(verdict: Any) -> str:
    """Строка «Режим» — с лимитом, окном и честной пометкой про остаток дней."""
    if verdict is None:
        return UNKNOWN
    label = REGIME_LABELS.get(getattr(verdict, "regime", ""), "не определён")
    bits = [label]
    if getattr(verdict, "stay_limit_days", None) and getattr(verdict, "window_days", None):
        bits.append(f"{verdict.stay_limit_days}/{verdict.window_days}")
    if getattr(verdict, "gknb_approval", None):
        bits.append("общий порядок, согласование ГКНБ")
    if getattr(verdict, "unified_permit_required", None) is True:
        bits.append("для работы нужно Единое разрешение")
    elif getattr(verdict, "unified_permit_required", None) is False:
        bits.append("работа без Единого разрешения")
    if "stay_window_check_required_by_manager" in (getattr(verdict, "notes", ()) or ()):
        bits.append("остаток дней проверить по штампам (ЕСУВМ)")
    return " · ".join(bits)


def _registration_line(verdict: Any) -> str:
    reg = getattr(verdict, "registration", None) if verdict is not None else None
    if reg is None:
        return UNKNOWN
    if reg.exempt_days is not None:
        line = f"освобождение {reg.exempt_days} дн."
    elif reg.working_days_from_border is not None:
        line = f"учёт в течение {reg.working_days_from_border} раб. дн. с пересечения границы"
    else:
        line = UNKNOWN
    if reg.registered_for_days is not None:
        line += f"; оформляется на {reg.registered_for_days} дн."
    return line


def _basis_line(verdict: Any) -> str:
    """Основания — разделы и страницы ТЗ, по которым сделан вывод (Б.2 п.4)."""
    units = getattr(verdict, "units", ()) if verdict is not None else ()
    if not units:
        return UNKNOWN
    seen: list[str] = []
    for u in units:
        mark = f"{u.unit_id} ({u.section}, с. {u.page})"
        status = "" if u.confirmation_status == "confirmed" else " — не подтверждено"
        label = f" — метка {u.label}" if u.label and u.label != "none" else ""
        if mark not in seen:
            seen.append(mark + status + label)
    return "; ".join(seen)


def render(data: dict[str, Any], verdict: Any = None) -> str:
    """Двенадцать строк Б.4. `data` — анкета диалога, `verdict` — вывод движка режима."""
    q = data or {}
    kg = q.get("kg_entry") or {}

    citizenship = kg.get("citizenship") or q.get("citizenship") or UNKNOWN
    doc = DOCUMENT_LABELS.get(str(kg.get("document_type") or ""), kg.get("document_type") or UNKNOWN)
    purpose = PURPOSE_LABELS.get(str(kg.get("purpose") or ""), kg.get("purpose") or UNKNOWN)
    where = kg.get("location")
    where_line = {"in_kg": "в Кыргызстане", "abroad": "за рубежом"}.get(str(where or ""), UNKNOWN)
    if where == "in_kg" and kg.get("in_kg_since"):
        where_line += f" с {kg['in_kg_since']}"

    dates = UNKNOWN
    if kg.get("entry_on") or kg.get("exit_on"):
        dates = f"{kg.get('entry_on') or '?'} – {kg.get('exit_on') or '?'}"

    flags = list(kg.get("flags") or ())
    withheld = list(getattr(verdict, "withheld", ()) or ()) if verdict is not None else []

    lines = [
        f"ЛИД · {q.get('channel') or 'whatsapp'} · "
        f"{kg.get('language') or 'ru'} · {kg.get('client_type') or 'B2C'}",
        f"Клиент: {q.get('name') or UNKNOWN}, {q.get('phone') or UNKNOWN}",
        f"Гражданство: {citizenship} · Паспорт: {doc} · Сейчас: {where_line}",
        f"Цель: {purpose} · Даты: {dates} · Человек: {kg.get('applicants_count') or 1}",
        f"Режим: {_regime_line(verdict)}",
        f"Регистрация: {_registration_line(verdict)}",
        f"Основание: {_basis_line(verdict)}",
        f"Приглашающая сторона: {kg.get('inviter') or 'нет данных'}",
        f"Семья/группа: {kg.get('family') or 'нет данных'}",
        f"Риски/флаги: {', '.join(flags) if flags else 'не отмечены'}",
        f"Ориентир стоимости: {NOT_QUOTED}",
        f"Причина передачи: {kg.get('handoff_reason') or 'квалификация не завершена'}",
        f"Не сказано клиенту: {', '.join(withheld) if withheld else 'нет'}",
    ]
    return "\n".join(lines)


def dossier_lines(data: dict[str, Any], verdict: Any = None) -> list[str]:
    """Те же данные строками для досье Bitrix — без шапки лида."""
    return render(data, verdict).split("\n")[2:]


def request_line(data: dict[str, Any], verdict: Any = None) -> str:
    """Одна строка для пуша менеджеру: кто, откуда, зачем, какой режим."""
    kg = (data or {}).get("kg_entry") or {}
    citizenship = kg.get("citizenship") or UNKNOWN
    purpose = PURPOSE_LABELS.get(str(kg.get("purpose") or ""), kg.get("purpose") or UNKNOWN)
    return f"въезд в КР · {citizenship} · {purpose} · {_regime_line(verdict)}"
