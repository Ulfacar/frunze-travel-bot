"""Клиент передумал ПОСЛЕ отправленной подборки — менеджер должен об этом узнать.

Замер 18.08.2026 на боевом портале (`scripts/sim_tour_card.py`, лид 186241): клиент
получил подборку по Турции, следующей репликой ушёл на ОАЭ, и карточка это честно
отразила. Но отправленные варианты по Турции стали мусором, а менеджеру не ушло ничего —
он подтверждает заявку по карточке, не зная, что разговор развернулся.

Почему только два поля. Бюджет, даты и состав бот пересчитывает сам: клиент сказал
«поднимем до 2500» — следующая подборка уже в 2500, вмешательство человека не нужно.
А смена страны или города вылета обесценивает именно то, что клиенту уже отправили.
Закон 5 (`docs/venom-v2.md`): шумный сторож выключают, и тогда он хуже отсутствующего.

Частота по истории 23.06–17.08: два и более направления называют 74 диалога из 985 —
верхняя граница 1.3 в сутки, и это ДО фильтра «только после отправленной подборки».

Однократность держится снимком на диалоге (`offer_facts`), а не памятью процесса:
рестарт не должен присылать менеджеру то же самое второй раз. Тот же приём, что и с
`bitrix_stage_by_bot` — факт о собственном действии помним мы, а не выводим из чужого
изменяемого состояния.

Гейт: `tests/test_bitrix_dossier_live.py`. ТЗ: `docs/task-bitrix-dossier-live.md`.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.core import flags

log = logging.getLogger("offer_change_notice")

FLAG = "offer_change_notice_enabled"

# Поля, смена которых обесценивает уже отправленную подборку. Порядок задаёт порядок
# строк в уведомлении.
SIGNIFICANT: tuple[str, ...] = ("destination", "region", "country", "departure_city")

_LABELS = {
    "destination": "Направление",
    "country": "Страна",
    "region": "Курорт",
    "departure_city": "Вылет",
}


def _clean(value) -> str:
    return str(value or "").strip()


def significant_diff(old: dict, new: dict) -> dict[str, tuple[str, str]]:
    """Что из значимого поменялось: {поле: (было, стало)}.

    Появление факта на пустом месте изменением НЕ считается: клиент, впервые назвавший
    курорт, ничего не переигрывает. Исчезновение — тоже: пустое значение приходит из
    повторного вызова инструмента, а не от клиента (тот же урок, что с датами в cb7f427).
    """
    changed: dict[str, tuple[str, str]] = {}
    for key in SIGNIFICANT:
        was, now = _clean((old or {}).get(key)), _clean((new or {}).get(key))
        if was and now and was.casefold() != now.casefold():
            changed[key] = (was, now)
    return changed


def _snapshot(facts: dict) -> dict[str, str]:
    return {key: _clean((facts or {}).get(key)) for key in SIGNIFICANT
            if _clean((facts or {}).get(key))}


def render_notice(*, name: str, phone: str, changed: dict[str, tuple[str, str]],
                  link: str, bitrix_link: str) -> str:
    """Одно сообщение: что изменилось и куда идти. Без пересказа всего досье."""
    head = " · ".join(part for part in (_clean(name), _clean(phone)) if part)
    lines = ["⚠️ Клиент передумал после отправленной подборки"]
    if head:
        lines += ["", head]
    lines.append("")
    for key in SIGNIFICANT:
        if key in changed:
            was, now = changed[key]
            lines.append(f"{_LABELS.get(key, key)}: {was} → {now}")
    lines += ["", "Отправленная подборка больше не подходит."]
    tail = " · ".join(part for part in (_clean(link), _clean(bitrix_link)) if part)
    if tail:
        lines.append(f"Открыть: {tail}")
    return "\n".join(lines)


async def remember_offer(conv_key: str, facts: dict) -> None:
    """Запомнить, по каким фактам клиенту ушла подборка. Точка отсчёта для «передумал».

    Без этого посева первая же смена сравнивалась бы с пустотой и считалась появлением
    факта, а не переигрыванием — то есть молчала бы именно там, где нужна.
    """
    try:
        from app.integrations.panel.store import get_conversation_store
        await get_conversation_store().update_meta(conv_key, offer_facts=_snapshot(facts))
    except Exception:  # noqa: BLE001
        log.warning("offer change: снимок подборки не сохранён (key=%s)", conv_key,
                    exc_info=True)


async def _default_send(login: str, text: str) -> bool:
    from app.core.instant_handoff import _send
    return await _send(login, text)


async def maybe_notify(conv_key: str, *, old: dict, new: dict, send=None) -> bool:
    """Сообщить владельцу диалога о существенной смене. True — отправлено.

    Никогда не поднимает исключение и никогда не мешает записи досье: карточка важнее
    уведомления, а сбой телеги не повод ронять живой ход.
    """
    try:
        if not await flags.get_flag(FLAG, False):
            return False

        changed = significant_diff(old, new)
        if not changed:
            return False

        from app.integrations.panel.store import get_conversation_store
        store = get_conversation_store()
        conv = await store.get(conv_key)
        if conv is None or getattr(conv, "intercepted", False):
            return False

        # Пока подборка не ушла, смена параметров — обычный ход квалификации, не событие.
        offer_stage = (settings.bitrix_stage_map or {}).get("offer_sent", "")
        if not offer_stage or (getattr(conv, "bitrix_stage_by_bot", "") or "") != offer_stage:
            return False

        wanted = _snapshot(new)
        if _snapshot(getattr(conv, "offer_facts", None) or {}) == wanted:
            return False          # об этой смене уже сообщали

        login = _clean(getattr(conv, "assigned_to", ""))
        if not login:
            # Слать некому. Снимок НЕ фиксируем: как только владелец появится,
            # уведомление уйдёт следующим ходом.
            log.info("offer change: no owner yet (key=%s)", conv_key)
            return False

        from app.core.calendar_brief import _bitrix_link, _client_link, _phone_display
        text = render_notice(
            name=_clean((getattr(conv, "qualification", None) or {}).get("name")),
            phone=_phone_display(getattr(conv, "phone", "") or conv_key),
            changed=changed,
            link=_client_link(conv_key, settings.admin_base_url),
            bitrix_link=_bitrix_link(getattr(conv, "bitrix_lead_id", "")),
        )
        sender = send or _default_send
        if not await sender(login, text):
            return False

        await store.update_meta(conv_key, offer_facts=wanted)
        log.info("offer change: sent (manager=%s key=%s fields=%s)",
                 login, conv_key, ",".join(changed))
        return True
    except Exception:  # noqa: BLE001 — уведомление никогда не роняет ход диалога
        log.warning("offer change notice failed (key=%s)", conv_key, exc_info=True)
        return False
