"""Best-effort pipeline for Bitrix lead stages, dossier and sale read-back."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.core import flags
from app.integrations.crm.bitrix24 import (
    LEAD_COMMENTS_MARKER,
    sanitize_lead_comments,
    sanitize_lead_comments,
    strip_lead_comments_bbcode,
)
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("crm.bitrix_pipeline")

STAGE_SEQUENCE: tuple[str, ...] = (
    "NEW", "UC_S0NTF8", "UC_Y4VY7B", "UC_1I1YV0", "UC_T9AEO4",
    "UC_A492DB", "UC_PNSIIB",
)
TERMINAL_STATUSES = frozenset({"CONVERTED", "JUNK", "UC_R8BD0W"})
DOSSIER_MARKER = LEAD_COMMENTS_MARKER
READ_BACK_LIMIT = 100
_tasks: set[asyncio.Task] = set()
_inflight_stages: set[tuple[str, str]] = set()

_LEGACY_KEYS = frozenset({
    "destination", "region", "departure_city", "tourists", "children_ages", "budget",
    "dates", "nights", "hotel_stars", "meal", "name", "country", "trip_purpose",
    "purpose", "age", "marital_status", "occupation", "prior_countries", "companions",
    "english_level", "prior_refusal", "prior_visas", "visa_country",
})


def _adapter(adapter: Any = None) -> Any:
    if adapter is not None:
        return adapter
    from app.integrations.crm.bitrix24 import Bitrix24Crm
    return Bitrix24Crm()


async def _enabled(conv: Any) -> bool:
    global_on = await flags.get_flag("bitrix_pipeline_enabled", settings.bitrix_pipeline_enabled)
    bot_id = (getattr(conv, "bot_id", "") or str(conv.user_id).partition(":")[0]).strip()
    return await flags.get_flag(f"bitrix_pipeline_enabled:{bot_id}", global_on)


async def _catchup_enabled() -> bool:
    """Один тумблер на всю фичу «карточка едет, даже если диалог ведёт менеджер»."""
    return await flags.get_flag("bitrix_stage_catchup_enabled",
                                settings.bitrix_stage_catchup_enabled)


async def _dialog_started_enabled(conv: Any) -> bool:
    """Уводить ли карточку из «Нового лида» по началу работы с клиентом. Per-bot.

    Заказчик просил трогать только туры: у виз менеджеры двигают карточки сами, и лезть
    туда незачем. Поэтому тумблер читается по боту, как `bitrix_pipeline_enabled`.
    """
    global_on = await flags.get_flag("bitrix_stage_dialog_started_enabled",
                                     settings.bitrix_stage_dialog_started_enabled)
    bot_id = (getattr(conv, "bot_id", "") or str(conv.user_id).partition(":")[0]).strip()
    return await flags.get_flag(f"bitrix_stage_dialog_started_enabled:{bot_id}", global_on)


async def _dossier_when_intercepted_enabled() -> bool:
    """Вести ли досье, пока диалог ведёт менеджер.

    Отдельный тумблер от `bitrix_stage_catchup_enabled`: движение стадии и сводка в
    карточке — разные обещания заказчику, и включать их порознь мы должны уметь.
    """
    return await flags.get_flag("dossier_when_intercepted_enabled",
                                settings.dossier_when_intercepted_enabled)


async def advance(conv_key: str, internal_stage: str, *, adapter: Any = None,
                  _conv: Any = None, _lead: dict | None = None) -> str:
    """Move a lead forward if the bot still owns its stage; return the new STATUS_ID."""
    store = get_conversation_store()
    conv = _conv if _conv is not None else await store.get(conv_key)
    stage_map = settings.bitrix_stage_map or {}
    if conv is None or not stage_map or not await _enabled(conv):
        return ""
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    target = stage_map.get(internal_stage, "")
    if not lead_id or not target:
        return ""
    # Перехват — «менеджер пишет в чат», а НЕ «менеджер двигал карточку»: это разные вещи,
    # а раньше первое запрещало второе. Цена замера (август, туры): перехвачено 69–88%
    # диалогов, из них 64 с полностью собранными фактами так и стояли в NEW. От реальной
    # перезаписи ручного переноса защищает `frozen_manual` ниже (стадия сменилась не ботом
    # → замираем), терминальные статусы и движение только вперёд по STAGE_SEQUENCE.
    if getattr(conv, "intercepted", False) and not await _catchup_enabled():
        return ""
    client = _adapter(adapter)
    try:
        lead = _lead if _lead is not None else await client.get_lead(lead_id)
        current = str(lead.get("STATUS_ID") or "")
        remembered = getattr(conv, "bitrix_stage_by_bot", "") or ""
        if current in TERMINAL_STATUSES:
            # Запоминаем в самой карточке, а не в памяти процесса: закрытая карточка
            # закрыта навсегда, и после рестарта это должно остаться правдой. Без отметки
            # 10 карточек в JUNK давали 815 обращений к порталу за сутки и держали слоты
            # лимита, пока 278 живых ждали очереди (замер 08.09.2026).
            if remembered != current:
                await store.update_meta(conv_key, bitrix_stage_by_bot=current)
            log.info("pipeline skip terminal conv_key=%s from=%s to=%s", conv_key, current, target)
            return ""
        if remembered and current != remembered:
            drift = classify_drift(current, remembered)
            log.info("pipeline skip frozen_manual conv_key=%s from=%s to=%s drift=%s",
                     conv_key, current, target, drift or "unknown")
            from app.core import pipeline_metrics
            if drift == "behind":
                # Воронка сама назад не ходит: карточку вернули руками или её подменили.
                # Чинить молча нельзя — это боевой CRM, — но человек должен узнать.
                await pipeline_metrics.note_conflict(
                    "stage_backwards", conv_key, detail=f"{current} ← {remembered}")
            # Карточку ведёт человек: писать в неё мы и так не будем, но и перебирать её
            # каждый прогон незачем. 09.09 такие 25 карточек держали все слоты лимита.
            await pipeline_metrics.mark_human_led(conv_key, conv)
            return ""
        if target not in STAGE_SEQUENCE or current not in STAGE_SEQUENCE:
            return ""
        if STAGE_SEQUENCE.index(target) <= STAGE_SEQUENCE.index(current):
            # Карточка уже на цели или дальше — двигать нечего. Запоминаем УВИДЕННОЕ, иначе
            # очередь будет ходить в портал за ней вечно: замер 08.09 показал 22 такие
            # карточки из 25 в голове очереди, и все они запрашивались каждый прогон.
            if remembered != current:
                await store.update_meta(conv_key, bitrix_stage_by_bot=current)
            return ""
        await client.update_stage_status(lead_id, target)
        lead["STATUS_ID"] = target
        await store.update_meta(conv_key, bitrix_stage_by_bot=target)
        log.info("pipeline moved conv_key=%s from=%s to=%s", conv_key, current, target)
        return target
    except Exception:  # noqa: BLE001 - CRM side channel is fail-open
        log.warning("pipeline advance failed conv_key=%s", conv_key, exc_info=True)
        return ""


def _reset_skip_cache_for_tests() -> None:
    """Оставлено для гейта: отметка о закрытой карточке живёт в самой карточке, а не в
    памяти процесса, поэтому сбрасывать в модуле уже нечего."""
    return None


def _plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу. Без него карточка говорит «1 туристов»."""
    if 11 <= count % 100 <= 14:
        return many
    tail = count % 10
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _ages_phrase(raw: str) -> str:
    """«7, 10» → «дети 7 и 10 лет»; «5» → «ребёнок 5 лет».

    Менеджер сверяет заказ с клиентом голосом — возрасты должны читаться, а не
    расшифровываться. Нечисловое оставляем как есть: чужую формулировку не переписываем.
    """
    ages = [part.strip() for part in re.split(r"[,;]", raw) if part.strip()]
    if not ages or not all(age.isdigit() for age in ages):
        return raw.strip()
    if len(ages) == 1:
        return f"ребёнок {ages[0]} лет"
    listed = ", ".join(ages[:-1]) + f" и {ages[-1]}"
    return f"дети {listed} лет"


def _compose_line(q: dict) -> str:
    """Строка «Состав» человеческим языком.

    Было `Состав: 4 · 7, 10` — четверо туристов и дети семи и десяти лет, но догадаться
    об этом менеджер обязан сам. Сводка, которую надо расшифровывать, свою работу
    не делает (живой прогон на лиде 186261, 21.08.2026).
    """
    parts: list[str] = []
    head = next((str(q[k]).strip() for k in ("tourists", "adults", "взрослых")
                 if str(q.get(k) or "").strip()), "")
    if head:
        digits = re.fullmatch(r"(\d+)", head)
        if digits:
            count = int(digits.group(1))
            parts.append(f"{count} {_plural(count, 'турист', 'туриста', 'туристов')}")
        else:
            parts.append(head)               # «мы вдвоём» — не склоняем чужие слова
    ages = next((str(q[k]).strip() for k in ("children_ages", "детей")
                 if str(q.get(k) or "").strip()), "")
    if ages:
        parts.append(_ages_phrase(ages))
    elif str(q.get("children") or "").strip():
        parts.append(str(q["children"]).strip())
    companions = str(q.get("companions") or "").strip()
    if companions:
        parts.append(companions)
    return ", ".join(parts)


def render_dossier(conv: Any, qualification: dict) -> str:
    q = dict(qualification or {})
    lines = [DOSSIER_MARKER]
    labels = (
        (("destination", "region", "country", "visa_country", "направление"), "Направление"),
        # Город вылета менеджеру нужен так же, как страна: замер 18.08 — клиент ушёл на
        # вылет из Алматы, бот пересчитал цены из Алматы, а в карточке об этом ни слова.
        (("departure_city", "departure", "город вылета"), "Вылет"),
        (("budget", "бюджет"), "Бюджет"), (("dates", "nights", "даты"), "Даты"),
    )
    for keys, label in labels:
        values = [str(q[k]).strip() for k in keys if str(q.get(k) or "").strip()]
        if values:
            # Страна и курорт — одна сущность, а не два разных факта: читаем через запятую.
            lines.append(f"{label}: {', '.join(values)}")
    composition = _compose_line(q)
    if composition:
        lines.append(f"Состав: {composition}")
    offer_url = str(q.get("offer_url") or q.get("tour_url") or "").strip()
    if not offer_url:
        for message in reversed(getattr(conv, "messages", []) or []):
            match = re.search(r"https?://\S+/t/[\w-]+", getattr(message, "text", "") or "")
            if match:
                offer_url = match.group(0).rstrip(".,)")
                break
    if offer_url:
        lines.append(f"Предложено: {offer_url}")
    # Ссылку строит `_client_link`, а не своя копия рядом: 21.08 копия разошлась с
    # оригиналом и досье уносило в карточку HTMX-партиал, который открывается как
    # сломанная страница. Две копии одного адреса однажды разъезжаются всегда.
    from app.core.calendar_brief import _client_link
    lines.append(f"Диалог: {_client_link(conv.user_id, settings.public_base_url)}")
    if getattr(conv, "last_message_at", None):
        lines.append(f"Последнее сообщение: {conv.last_message_at:%d.%m.%Y %H:%M}")
    return sanitize_lead_comments("\n".join(lines))


def _legacy_ours(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    for line in lines:
        key, sep, value = line.partition(":")
        if not sep or not value.strip() or key.strip() not in _LEGACY_KEYS:
            return False
    return True


# Строки, которые пишет только `render_dossier`. Всё, что не отсюда, — рука человека.
_DOSSIER_PREFIXES = ("Направление:", "Вылет:", "Бюджет:", "Даты:", "Состав:",
                     "Предложено:", "Диалог:", "Последнее сообщение:")


def _dossier_ours(text: str) -> bool:
    """Recognise our own dossier in portal-normalised COMMENTS.

    Bitrix may add BBCode around links on read-back, поэтому сначала снимаем разметку.

    Маркера в первой строке НЕ достаточно: менеджер дописывает свою строку под нашей
    сводкой, и по одному маркеру поле выглядело бы нашим — а следующее обновление
    стирало бы дописанное. Поэтому нашим считаем текст, где каждая видимая строка —
    наша: маркер либо известная метка.
    """
    visible = strip_lead_comments_bbcode(text)
    lines = [line.strip() for line in visible.splitlines() if line.strip()]
    if not lines or not lines[0].startswith(DOSSIER_MARKER):
        return False
    return all(line.startswith(_DOSSIER_PREFIXES) for line in lines[1:])


def _no_human_lines(text: str) -> bool:
    """Похоже ли поле на наше досье, даже если портал испортил сам маркер.

    Здесь сходятся два требования, и оба выстраданы на проде.

    17.08: портал вырезал «[бот]» как BBCode и съел эмодзи — маркер перестал совпадать,
    бот не узнал собственный текст и замолчал по карточке навсегда. Отсюда правило
    «кто писал — помним МЫ», источник истины не может быть чужим изменяемым текстом.

    21.08: то же правило, применённое буквально, затирало правку менеджера — он дописал
    «клиент передумал, летят из Оша», а бот перезаписал поле своей сводкой.

    Развязка: память отвечает на вопрос «наше ли поле», а текст — на вопрос «трогал ли
    его человек». Метки короткие и без спецсимволов, BBCode-парсеру портала в них
    вцепиться не во что, поэтому по ним состав строк узнаётся и после искажения.

    От первой строки требуем начинаться с корня маркера («Досье»): портал обрезает у неё
    хвост, но не переписывает начало.

    И требуем минимум двух строк. Однострочная запись иначе проскакивала бы всегда —
    строк «после первой» у неё просто нет, а проверять нечего. Проверено на реалистичных
    пометках менеджера: «Направление: уточнить у клиента» и «Досье клиента: хочет Египет»
    обе считались нашими и были бы стёрты. Наше досье короче двух строк не бывает:
    `render_dossier` всегда дописывает ссылку на диалог и время последнего сообщения.
    """
    visible = strip_lead_comments_bbcode(text)
    lines = [line.strip() for line in visible.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    if not lines[0].startswith(DOSSIER_MARKER.split()[0]):
        return False
    return all(line.startswith(_DOSSIER_PREFIXES) for line in lines[1:])


async def sync_dossier(conv_key: str, *, qualification: dict | None = None,
                       adapter: Any = None, _conv: Any = None,
                       _lead: dict | None = None) -> bool:
    store = get_conversation_store()
    conv = _conv if _conv is not None else await store.get(conv_key)
    if conv is None or not await _enabled(conv):
        return False
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    if not lead_id:
        return False
    # Перехват — «менеджер ПИШЕТ клиенту», и это не повод переставать вести карточку:
    # сводка нужна ему ровно тогда, когда клиент стоит перед ним. Замер 21.08: из 11
    # туровых диалогов за шесть часов после QR восемь перехвачены — при старом правиле
    # досье не появилось бы почти нигде.
    if getattr(conv, "intercepted", False) and not await _dossier_when_intercepted_enabled():
        return False
    client = _adapter(adapter)
    try:
        lead = _lead if _lead is not None else await client.get_lead(lead_id)
        if str(lead.get("STATUS_ID") or "") in TERMINAL_STATUSES:
            return False
        comments = str(lead.get("COMMENTS") or "")
        # Два вопроса, и отвечают на них разные источники. «Наше ли это поле» — наша
        # память (портал калечит текст, и угадывать по нему нельзя: шрам 17.08). «Трогал
        # ли его человек» — сам текст: строка не из нашего шаблона означает, что менеджер
        # писал руками, и его слова важнее свежести нашей сводки (шрам 21.08).
        remembered = bool(getattr(conv, "bitrix_dossier_by_bot", False))
        writable = (_dossier_ours(comments) or _legacy_ours(comments)
                    or (remembered and _no_human_lines(comments)))
        if comments and not writable:
            return False
        text = render_dossier(conv, conv.qualification if qualification is None else qualification)
        await client.update_comments(lead_id, text)
        await store.update_meta(conv_key, bitrix_dossier_by_bot=True)
        return True
    except Exception:  # noqa: BLE001
        log.warning("pipeline dossier failed conv_key=%s", conv_key, exc_info=True)
        return False


# Портал принимает КОДЫ валют, а движок оценки чека хранит СИМВОЛЫ («$», «€», «сом» —
# `readiness.py:180`). Живая проверка 18.08: `crm.deal.add` с `CURRENCY_ID: "$"` отвечает
# 400 «Неверное значение поля Валюта» — и сделка не создаётся вовсе. В базе таких диалогов
# 39 с «$» и один с «€».
_CURRENCY_CODES = {
    "$": "USD", "usd": "USD", "долл": "USD",
    "€": "EUR", "eur": "EUR", "евро": "EUR",
    "сом": "KGS", "kgs": "KGS", "с": "KGS",
    "руб": "RUB", "rub": "RUB", "₽": "RUB",
}


def _currency_code(raw: str) -> str:
    """Символ или код → код Битрикса. Незнакомое — пусто: лучше сделка без суммы, чем
    отвергнутый порталом вызов, после которого не создаётся ничего."""
    value = str(raw or "").strip().lower()
    if not value:
        return ""
    if value.upper() in {"USD", "EUR", "KGS", "RUB"}:
        return value.upper()
    return _CURRENCY_CODES.get(value, "")


def _sale_amount(conv: Any) -> tuple[str, str] | None:
    """Оплата, названная менеджером при подтверждении продажи. Она главнее всего.

    Бюджет из разговора — это «сколько клиент хотел потратить», и в отчёте о выручке он
    врёт. Пока менеджеру негде было назвать сумму, приходилось брать бюджет; теперь поле
    на странице подтверждения есть, и если оно заполнено — в сделку идёт оно.

    Отдаём строкой, как и `_opportunity`: портал принимает сумму строкой, а float с
    хвостом вроде 119999.99999 в карточке выглядит как ошибка.
    """
    try:
        amount = float(getattr(conv, "sale_amount", None) or 0)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    currency = str(getattr(conv, "sale_currency", "") or "KGS").upper()
    return (f"{amount:.2f}", currency)


def _opportunity(conv: Any) -> tuple[str, str]:
    """Сумма сделки и её ВАЛЮТА. ("", "") — если разобрать не удалось.

    Валюта обязательна: воронка туров считает в сомах (базовая валюта портала KGS, живые
    сделки 45000 и 58000 KGS). Без явной `CURRENCY_ID` бюджет «2500 USD» лёг бы в портал
    как 2500 сом — впятеро-двадцатеро ниже правды, а заказчик меряет работу этими суммами.
    Пересчёт для отчётов делает сам Битрикс: курсы у него настроены, свой мы не прибиваем —
    он протухнет.

    Разбор берём тот же, что и поиск туров (`_parse_budget`): голое число там означает
    доллары, и расходиться с ним нельзя — клиенту показали цены в долларах.
    """
    value = getattr(conv, "estimated_value", None)
    if value is not None:
        code = _currency_code(getattr(conv, "estimated_value_currency", ""))
        return (str(value), code) if code else ("", "")
    budget = str((getattr(conv, "qualification", {}) or {}).get("budget") or "")
    from app.integrations.tourvisor.client import _parse_budget
    amount, currency = _parse_budget(budget)
    if not amount:
        return "", ""            # лучше пустое поле, чем неверная сумма в отчёте
    code = _currency_code(currency) or "USD"
    return str(amount), code


def _is_tour(conv: Any) -> bool:
    """Диалог туровый? Сделки заводятся в одну воронку — CATEGORY_ID 27 «FrunzeTravel».

    Без этой проверки обратное чтение сопоставляло проданный лид с ЛЮБЫМ нашим диалогом
    по номеру карточки. Визовые менеджеры двигают лиды в «Подписан» сотнями в месяц, и
    каждая такая продажа помечала визовый диалог как выигранный и заводила сделку в
    туровой воронке. Замер 13.09: флаг автосделки на проде включён, один визовый диалог
    уже помечен продажей. Загрязнялась ровно та статистика, ради которой конвейер и есть.

    Пустая воронка туровой не считается: «не знаю» — это не «тур».
    """
    return str(getattr(conv, "funnel", "") or "") == "tours"


async def read_back_once(*, adapter: Any = None) -> dict:
    """Забрать из портала продажи и завести по ним сделки.

    Спрашиваем портал СПИСКОМ («какие лиды стали Подписаны после такого-то»), а не
    опрашиваем каждую свою карточку. Прежний перебор с потолком в 100 штук при 1001
    карточке в окне не находил продажу на свежем лиде никогда — проверено живьём на
    лиде 186245 (замер 18.08). Тот же закон, что со сторожем каналов: спрашиваем
    источник, а не гадаем перебором.
    """
    stats = {key: 0 for key in ("checked", "moved", "frozen_manual", "dossier_written",
            "dossier_skipped_human", "won", "deals_created", "deals_dry_run", "errors")}
    client = _adapter(adapter)
    store = get_conversation_store()
    since = datetime.now(timezone.utc) - timedelta(days=settings.bitrix_read_back_days)

    try:
        converted = await client.list_converted_leads(since)
    except Exception:  # noqa: BLE001 — портал недоступен, следующий тик попробует снова
        log.warning("pipeline read-back: портал не отдал список продаж", exc_info=True)
        stats["errors"] += 1
        return stats

    by_lead: dict[str, Any] = {}
    for conv in await store.all_conversations_light():
        if not _is_tour(conv):
            continue            # воронка FrunzeTravel — только туры, см. `_is_tour`
        lead_id = str(getattr(conv, "bitrix_lead_id", "") or "")
        if lead_id:
            by_lead[lead_id] = conv

    for lead in converted:
        lead_id = str(lead.get("ID") or "")
        conv = by_lead.get(lead_id)
        if conv is None:
            continue                    # продажа по чужой карточке — не наш диалог
        try:
            stats["checked"] += 1
            if (getattr(conv, "outcome", "") or "") != "won":
                await store.update_meta(conv.user_id, outcome="won")
                stats["won"] += 1
            if getattr(conv, "bitrix_deal_id", ""):
                continue
            if not await flags.get_flag("bitrix_autodeal_enabled", settings.bitrix_autodeal_enabled):
                stats["deals_dry_run"] += 1
                continue
            fields = deal_fields(conv, lead)
            contact_id = await _deal_contact_id(conv, lead, client)
            if contact_id:
                fields["CONTACT_ID"] = contact_id
            deal_id = await client.create_deal(fields)
            if deal_id:
                await store.update_meta(conv.user_id, bitrix_deal_id=deal_id)
                stats["deals_created"] += 1
        except Exception:  # noqa: BLE001
            stats["errors"] += 1
            log.warning("pipeline read-back failed lead=%s", lead_id, exc_info=True)
    log.info("pipeline read-back stats=%s", stats)
    return stats



def deal_title(conv: Any, lead: dict) -> str:
    """Название сделки — про тур, а не про канал.

    Замер 11.09: сделка называлась «Al - WhatsApp Wappi: GetVisa», и в списке пять таких
    отличались только именем. Менеджер должен опознавать сделку не открывая её, поэтому
    собираем из того, что клиент сказал: куда, сколько человек, когда.
    """
    q = dict(getattr(conv, "qualification", None) or {})
    where = ", ".join(x for x in (str(q.get("destination") or "").strip(),
                                  str(q.get("region") or "").strip()) if x)
    # «чел» дописываем ТОЛЬКО к голому числу. Состав часто приходит фразой («2 взрослых,
    # 1 ребенок»), и тогда получалось «2 взрослых, 1 ребенок чел» — мусор в названии,
    # который менеджер видит в списке сделок (прогон по 734 диалогам 11.09).
    who = str(q.get("tourists") or "").strip()
    if who:
        who = f"{who} чел" if who.isdigit() else who
    when = str(q.get("dates") or "").strip()
    parts = [x for x in (where, who, when) if x]
    if parts:
        return "Тур: " + " · ".join(parts)
    # Анкета пустая — разговор был ни о чём. Берём название лида, а если и его нет,
    # хотя бы телефон: сделка без названия в портале выглядит как строка-призрак.
    return str(lead.get("TITLE") or "").strip() or \
        f"Тур: {getattr(conv, 'phone', '') or conv.user_id}"


def deal_fields(conv: Any, lead: dict) -> dict:
    """Поля новой сделки. Чистая функция — проверяется без обращений к порталу.

    Что сюда НЕ попадает и почему:
    * `LEAD_ID` — в сделке доступен только для чтения (`crm.deal.fields`), портал
      отвергнет запись. Связь с карточкой клиента кладём ссылкой в комментарий.
    * `OPPORTUNITY` — сколько клиент реально заплатил, бот не знает: оплата идёт в офисе
      и по телефону. Сумму вписывает менеджер (решение владельца 11.09). Раньше сюда
      уезжал бюджет из анкеты, то есть «сколько клиент хотел потратить» — в отчёте о
      выручке это враньё.
    * `CONTACT_ID` — добавляется отдельно и только при включённом тумблере: контакт это
      новая запись в CRM заказчика.
    """
    q = dict(getattr(conv, "qualification", None) or {})
    # Досье собираем ТОЙ ЖЕ функцией, что пишет в лид. Вторая копия текста однажды
    # разъедется с оригиналом — это уже было 21.08 со ссылкой на диалог.
    comments = [render_dossier(conv, q)]
    lead_id = str(lead.get("ID") or "").strip()
    if lead_id:
        # Номер карточки пишем ВСЕГДА, ссылку — когда известен адрес портала. Связь
        # сделки с карточкой иначе теряется совсем: поле `LEAD_ID` только для чтения.
        base = (settings.bitrix_portal_url or "").rstrip("/")
        where = f"{base}/crm/lead/details/{lead_id}/" if base else f"№{lead_id}"
        comments.append(f"Карточка клиента: {where}")

    fields = {
        "CATEGORY_ID": settings.bitrix_deal_category_id,
        "STAGE_ID": settings.bitrix_deal_stage_id,
        "TITLE": deal_title(conv, lead),
        "COMMENTS": sanitize_lead_comments("\n".join(x for x in comments if x)),
    }
    for key in ("ASSIGNED_BY_ID", "SOURCE_ID", "SOURCE_DESCRIPTION"):
        if lead.get(key):
            fields[key] = lead[key]
    # Сумму кладём ТОЛЬКО когда её удалось разобрать, и обязательно с валютой: воронка
    # туров считает в сомах, и «2500 USD» без валюты легло бы как 2500 сом — в двадцать
    # раз ниже правды (гейт tests/test_deal_currency.py, замер портала 18.08). Это оценка
    # из разговора, а не факт оплаты: менеджер правит её в карточке.
    opportunity, currency = _sale_amount(conv) or _opportunity(conv)
    if opportunity:
        fields["OPPORTUNITY"] = opportunity
        fields["CURRENCY_ID"] = currency
    return fields


async def _deal_contact_id(conv: Any, lead: dict, client: Any) -> str:
    """Контакт для сделки: найти по телефону, иначе создать. "" — если нельзя или нечем.

    Без контакта из сделки нельзя позвонить — в Битриксе телефон живёт у контакта, а не
    у сделки. Но создание контакта это новая запись в CRM заказчика, поэтому за тумблером
    и по умолчанию выключено.
    """
    if not await flags.get_flag("bitrix_deal_contact_enabled",
                                settings.bitrix_deal_contact_enabled):
        return ""
    phone = str(getattr(conv, "phone", "") or "").strip()
    if not phone:
        return ""
    try:
        found = await client.find_contact_id_by_phone(phone)
        if found:
            return found
        name = str(lead.get("NAME") or "").strip() or phone
        return await client.create_contact(name, phone)
    except Exception:  # noqa: BLE001 — без контакта сделка всё равно нужнее, чем без сделки
        log.warning("pipeline: контакт для сделки не получен (conv=%s)", conv.user_id,
                    exc_info=True)
        return ""


def classify_drift(current: str, remembered: str) -> str:
    """Куда уехала карточка относительно того, что записал бот: `ahead` | `behind` | ``.

    До этого оба случая были одним: «стадия не та, что мы помним» → замираем молча.
    Но это две разные вещи. Менеджер двинул карточку ВПЕРЁД — он работает, всё правильно,
    бот уступает. Карточка уехала НАЗАД (или её вернули в «Новый лид») — так сама собой
    воронка не ходит, и человек должен об этом узнать.

    Стадии вне известной последовательности не судим: портал могли перенастроить, и
    выдумывать смысл незнакомому статусу опаснее, чем промолчать.
    """
    if not current or not remembered or current == remembered:
        return ""
    if current not in STAGE_SEQUENCE or remembered not in STAGE_SEQUENCE:
        return ""
    return "ahead" if STAGE_SEQUENCE.index(current) > STAGE_SEQUENCE.index(remembered) else "behind"


def _stage_reached(by_bot: str, target: str) -> bool:
    """Дошла ли карточка до целевой стадии — или уже уехала дальше неё.

    Сравнение на равенство здесь стоило нам всего догоняющего прохода: карточка на
    «Предложение отправлено» при цели «Выявление потребностей» считалась недоделанной,
    каждый тик попадала в очередь и занимала слот лимита. Замер 07.09: 27 таких карточек
    держали все 25 слотов, `moved` был нулём во всех прогонах за сутки, а пять карточек,
    которые правда ждали движения, не обрабатывались вообще.
    """
    if not target:
        return False
    if by_bot == target:
        return True
    if by_bot in STAGE_SEQUENCE and target in STAGE_SEQUENCE:
        return STAGE_SEQUENCE.index(by_bot) > STAGE_SEQUENCE.index(target)
    return False


def _work_started(conv: Any) -> bool:
    """Начали ли с этим лидом работать. Только факты, которые видны в диалоге.

    Счётчика сообщений в `all_conversations_light` нет — и не надо: любого из признаков
    ниже достаточно, чтобы карточка перестала быть «Новым лидом», которого никто не касался.
    Ни одного признака — клиент написал, и ему не ответили; это честный `NEW`.
    """
    if getattr(conv, "intercepted", False):
        return True                                     # менеджер вступил в переписку
    if (getattr(conv, "assigned_to", "") or "").strip():
        return True                                     # диалог закреплён за менеджером
    if getattr(conv, "last_sender", "") in ("bot", "manager"):
        return True                                     # клиенту ответили
    return any(str(v or "").strip() for v in (getattr(conv, "qualification", None) or {}).values())


def _catchup_stage(conv: Any, *, dialog_started: bool = False) -> str:
    """Какую стадию карточка заслужила по уже собранным фактам — или пусто.

    `qualified` — факт, проверяемый по самой карточке (направление + даты + туристы).
    `offer_sent` здесь НЕ ставим — «подборку отдали» знает лишь живой ход, который её
    отправил (`runner._attach_tour_cards`), и догадываться об этом задним числом нельзя:
    соврать в CRM хуже, чем отстать на одну стадию.

    `dialog_started` (за тумблером) — вторая, более ранняя ступень: с клиентом начали
    работать, но до полной квалификации не дошло. Без неё карточка стоит в «Новом лиде»
    навсегда, потому что порог квалификации проходят 11% туровых диалогов — 85% забирает
    менеджер раньше, чем бот успевает выяснить направление, даты и состав.

    Правило квалификации берём из `runner._is_qualified`, а не переписываем рядом: две
    копии одного порога однажды разъедутся, и карточки поедут не туда.
    """
    from app.agent.runner import _is_qualified
    try:
        if _is_qualified(conv):
            return "qualified"
    except Exception:  # noqa: BLE001 — кривая квалификация не должна ронять весь проход
        return ""
    return "dialog_started" if dialog_started and _work_started(conv) else ""


async def catchup_once(*, adapter: Any = None) -> dict:
    """Подтянуть стадии карточек, которые живой ход пропустил.

    Зачем отдельный проход: при перехвате `run_turn` выходит на первой строке, поэтому
    `_sync_qualified_if_ready` для таких диалогов не вызывается вообще — факты в карточке
    есть, а стадия не поедет никогда, сколько бы тумблеров ни включили. Замер 21.08.2026:
    64 туровых диалога за август с полной квалификацией стояли в NEW.

    Проход идёт порциями (`bitrix_stage_catchup_limit` за тик): каждая карточка — это
    два запроса к порталу, а он не любит залпов.
    """
    stats = {key: 0 for key in
             ("scanned", "eligible", "moved", "dossiers", "errors", "waiting")}
    if not await _catchup_enabled():
        return stats
    from app.core import pipeline_metrics
    client = _adapter(adapter)
    store = get_conversation_store()
    since = datetime.now(timezone.utc) - timedelta(days=settings.bitrix_stage_catchup_days)
    limit = max(1, settings.bitrix_stage_catchup_limit)
    dossier_on = await _dossier_when_intercepted_enabled()
    touched = 0                          # карточек, по которым ходили в портал за этот тик

    for conv in await store.all_conversations_light():
        last = getattr(conv, "last_message_at", None)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is not None and last < since:
            continue
        if not (getattr(conv, "bitrix_lead_id", "") or ""):
            continue
        if (getattr(conv, "bitrix_stage_by_bot", "") or "") in TERMINAL_STATUSES:
            continue                        # закрытая карточка: ни двигать, ни писать нечего
        if await pipeline_metrics.is_human_led(conv.user_id, conv):
            continue                        # карточку ведёт человек — слот нужен другим
        stats["scanned"] += 1
        stage = _catchup_stage(conv, dialog_started=await _dialog_started_enabled(conv))
        if not stage:
            continue
        # Стадия уже наша — двигать нечего, но сводка в карточке могла и не появиться:
        # 21.08 проход сдвинул 25 карточек, а досье не записал ни в одну, и менеджер
        # получил половину обещанного — карточка переехала, а чего хочет клиент, не видно.
        stage_done = _stage_reached(getattr(conv, "bitrix_stage_by_bot", "") or "",
                                    (settings.bitrix_stage_map or {}).get(stage, ""))
        dossier_done = bool(getattr(conv, "bitrix_dossier_by_bot", False))
        if stage_done and (dossier_done or not dossier_on):
            continue
        # Лимит исчерпан — дальше только СЧИТАЕМ очередь, в портал не ходим. Без этого
        # числа длина очереди была невидима, и застревание прохода (07.09: moved=0 сутки
        # подряд) нельзя было отличить от «работы больше нет».
        if touched >= limit:
            stats["waiting"] += 1
            continue
        stats["eligible"] += 1
        touched += 1
        try:
            if not stage_done and await advance(conv.user_id, stage, adapter=client, _conv=conv):
                stats["moved"] += 1
            # Сводку пишем там, где её ЕЩЁ НЕТ. Свежие факты в уже записанную доносит живой
            # ход; догоняющему проходу переписывать её незачем. Замер 08.09: 1949 записей на
            # 154 карточки — по двенадцать переписываний за сутки, и все 25 слотов лимита
            # уходили на это вместо движения очереди.
            if dossier_on and not dossier_done and await sync_dossier(
                    conv.user_id, adapter=client, _conv=conv):
                stats["dossiers"] += 1
        except Exception:  # noqa: BLE001 — одна карточка не должна ронять проход
            stats["errors"] += 1
            log.warning("pipeline catchup failed conv_key=%s", conv.user_id, exc_info=True)

    log.info("pipeline catchup stats=%s", stats)
    return stats


def _facts_changed(conv: Any, qualification: dict | None) -> bool:
    """Изменилась ли квалификация с прошлого хода.

    Сравниваем свежие факты хода с теми, что лежат на диалоге: оркестратор пишет их в
    конце хода, поэтому здесь `conv.qualification` — это ещё прошлое состояние. Так мы
    отличаем «клиент назвал новое» от «клиент болтает», не заводя отдельного поля и не
    дёргая портал на каждую реплику.
    """
    if qualification is None:
        return False
    fresh = {k: v for k, v in qualification.items() if v}
    known = {k: v for k, v in (getattr(conv, "qualification", None) or {}).items() if v}
    return fresh != known


async def _advance_and_sync(conv_key: str, stage: str, qualification: dict | None) -> None:
    store = get_conversation_store()
    conv = await store.get(conv_key)
    if conv is None:
        return
    # Ранний выход относится к СТАДИИ, а не к досье. Приёмочный прогон 18.08 (лид 186259):
    # бот не дошёл до подборки, весь диалог зовётся только `qualified`, и после первой же
    # записи карточка замерзала — клиент ушёл на Дубай, стал четвёркой и сменил вылет, а в
    # карточке осталась Анталья на двоих. Стадию второй раз не двигаем, факты дописываем.
    target = (settings.bitrix_stage_map or {}).get(stage, "")
    stage_done = bool(target) and (getattr(conv, "bitrix_stage_by_bot", "") or "") == target
    if stage_done and not _facts_changed(conv, qualification):
        return                      # ни стадии, ни новостей — портал не трогаем вовсе
    lead_id = getattr(conv, "bitrix_lead_id", "") or ""
    if not lead_id:
        return
    client = _adapter()
    try:
        lead = await client.get_lead(lead_id)
    except Exception:  # noqa: BLE001
        log.warning("pipeline lead read failed conv_key=%s", conv_key, exc_info=True)
        return
    moved_to = await advance(conv_key, stage, adapter=client, _conv=conv, _lead=lead)
    await sync_dossier(
        conv_key, qualification=qualification, adapter=client, _conv=conv, _lead=lead,
    )

    # Карточка обновлена — теперь решаем, надо ли будить человека. Порядок важен:
    # досье пишется всегда, уведомление — только если клиент переиграл уже отправленное.
    from app.core import offer_change_notice as notice
    facts = qualification if qualification is not None else (
        getattr(conv, "qualification", None) or {})
    if moved_to and moved_to == (settings.bitrix_stage_map or {}).get("offer_sent", ""):
        await notice.remember_offer(conv_key, facts)
    else:
        await notice.maybe_notify(
            conv_key, old=getattr(conv, "offer_facts", None) or {}, new=facts)


def fire(conv_key: str, stage: str, qualification: dict | None) -> None:
    """Schedule portal work without delaying the customer response."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key = (conv_key, stage)
    if key in _inflight_stages:
        return
    task = loop.create_task(_advance_and_sync(conv_key, stage, qualification))
    _inflight_stages.add(key)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    task.add_done_callback(lambda _done: _inflight_stages.discard(key))
