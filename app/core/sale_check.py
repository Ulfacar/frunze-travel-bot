"""Вечерний вопрос менеджеру: «клиент оплатил?» — одним касанием, без захода в панель.

Зачем это есть. 10.09.2026 разбор показал, что вся цепочка от обращения до отчёта
исправна, кроме одного звена — человеческого:

    клиент написал       → бот завёл лид                       работает
    бот выяснил запрос   → двигает стадию, пишет сводку        работает
    менеджер продал тур  → должен нажать «Оплатил»             НЕ НАЖИМАЕТ
    лид → «Подписан»     → бот создаёт сделку в FrunzeTravel   не доходит
    владелец смотрит     → «Продано: 0, конверсия 0.0%»        не доходит

Кнопка «✅ Оплатил» в панели живёт с июля, ей воспользовались 1-3 раза за 90 дней. Дело
не в лени: в момент продажи менеджер сидит в WhatsApp, а не в админке. Владелец пятую
неделю подряд получает сводку со строкой «Продано: 0» при 251 обращении за неделю — и
делает единственный возможный вывод, что бот не работает.

Почему ссылки, а не кнопки Telegram. Менеджерам пишет `@FrunzeHelper_bot`; кнопки требуют
вебхука, а вебхук несовместим с опросом, на котором держится мост владельца. Ссылка даёт
то же одно касание и ничего не ломает.

## Ловушки, найденные ревью и замером на проде 10.09 — все зашиты здесь

1. **`outcome` — не признак «диалог закрыт».** Оркестратор пишет туда рабочий авто-статус
   (`in_progress`/`office`/`manager`) на каждом ходу: непустой он у 564 туровых диалогов
   из 794. Финал ставит только человек — это `won`/`lost`. Проверка «непусто» означала бы
   не спросить вообще никого (замер: 0 кандидатов вместо 92) и отказать по нажатой ссылке.
2. **Открытие ссылки не должно ничего менять.** Telegram строит превью, сходив GET-ом по
   первой ссылке в сообщении, — и отметил бы «Оплатил» за менеджера в первый же вечер. То
   же делают антивирус на телефоне и предзагрузка браузера. Поэтому `GET /sale/...`
   показывает страницу с кнопкой, а пишет только `POST`. Превью гасим отдельно.
3. **Стадии `manager`/`office` ставит и визовая воронка.** Без фильтра по `funnel` визовому
   менеджеру ушёл бы вопрос с подписью про отчёт по турам, а лид GetVisa уехал бы
   в «Подписан» под видом тур-продажи.
4. **Номер клиента в адрес ссылки не кладём:** `/sale/<token>` осядет в access-логе nginx
   и в истории браузера на телефоне менеджера. В токене — непрозрачный отпечаток диалога.
5. **Нет секрета — нет ссылок.** Пустой `webhook_secret` на проде уже случался; подпись на
   константе из репозитория означала бы, что продажи может отметить кто угодно.
6. **Два тапа подряд — одна запись.** Защёлка исхода атомарная, на стороне БД, и только
   после неё идём в портал.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("sale_check")

BISHKEK_UTC_OFFSET = 6
# Что менеджер может ответить. «won»/«lost» — финал, «thinking» финалом не является:
# клиент ещё думает, и мы просто отложим вопрос, а не запишем несуществующий исход.
OUTCOMES = ("won", "lost", "thinking")
# Исход, который ставит ЧЕЛОВЕК. Всё остальное в поле `outcome` — рабочий авто-статус
# оркестратора, и закрытым диалог от него не становится (ловушка 1).
FINAL_OUTCOMES = ("won", "lost")
# Стадии, на которых работа с клиентом реально шла. «greeting» сюда не входит намеренно:
# спрашивать менеджера про «здравствуйте» без продолжения — это шум, от которого
# перестают читать сообщения целиком.
WORKED_STAGES = {"office", "office_consultation", "manager", "manager_handoff",
                 "progress", "search", "follow_up"}
# Часы по Бишкеку, когда человеку вообще можно писать.
DAY_HOURS = range(9, 22)
# Наши собственные номера: это партнёрские чаты (ваучеры, страховки, трансферы), а не
# клиенты. Замер 11.09: они попали в вечернюю очередь, и менеджеру ушёл бы вопрос
# «клиент оплатил?» про переписку с коллегами, а нажатие завело бы сделку в портале.
OWN_NUMBERS = ("996707660009", "996706660009")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _worked(conv: Any) -> bool:
    """Была ли по диалогу настоящая работа: подборка туров или доведение до человека."""
    if dict(getattr(conv, "offer_facts", None) or {}):
        return True
    return str(getattr(conv, "stage", "") or "") in WORKED_STAGES


def _is_tour(conv: Any) -> bool:
    """Только туры: стадии `manager`/`office` ставит и визовая воронка (ловушка 3)."""
    return str(getattr(conv, "funnel", "") or "") == "tours"


# Валюты, которые менеджер может выбрать на странице подтверждения. Сом первым: воронка
# туров считает в сомах, базовая валюта портала — KGS.
SALE_CURRENCIES = ("KGS", "USD")
# Выше этого продажа тура не бывает — защита от лишнего нуля, набранного с телефона.
_MAX_SALE = {"KGS": 5_000_000, "USD": 60_000}


def parse_amount(raw: str, currency: str = "KGS") -> float | None:
    """Сумма оплаты из того, что менеджер набрал с телефона.

    «120 000», «120000», «96,5» — обычная запись. Мусор («не помню»), ноль и отрицательное
    не принимаем: пустая сумма это вопрос менеджеру, а неверная — испорченный отчёт.
    """
    text = str(raw or "").strip().replace(" ", " ")
    text = text.replace(" ", "").replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value <= 0:
        return None
    if value > _MAX_SALE.get(str(currency or "KGS").upper(), _MAX_SALE["KGS"]):
        return None
    return value


async def _save_amount(conv_key: str, raw: str, currency: str) -> float | None:
    """Записать названную менеджером оплату. Не разобрали — подтверждение всё равно живёт."""
    code = str(currency or "KGS").upper()
    if code not in SALE_CURRENCIES:
        code = SALE_CURRENCIES[0]
    value = parse_amount(raw, code)
    if value is None:
        return None
    from app.integrations.panel.store import get_conversation_store
    await get_conversation_store().update_meta(conv_key, sale_amount=value,
                                               sale_currency=code)
    log.info("sale check: менеджер назвал сумму conv=%s currency=%s", conv_key, code)
    return value


def _shared_leads(convs: list) -> set[str]:
    """Карточки Открытой линии, на которых сидит больше одного нашего клиента.

    Замер 11.09: таких карточек 74, на них 203 туровых диалога, на одной — 19 клиентов
    и 73 телефона внутри самой карточки. Нажатие «Оплатил» по такому диалогу увело бы
    в «Подписан» карточку всех сразу, а обратное чтение завело бы сделку с именем
    произвольного из них — остальные выпали бы из конвейера навсегда.
    """
    seen: dict[str, set[str]] = {}
    for conv in convs:
        lead = str(getattr(conv, "bitrix_lead_id", "") or "").strip()
        if not lead:
            continue
        # Ключ диалога — «<бот>:<телефон>». Считаем ЛЮДЕЙ, а не строки: один клиент,
        # написавший и в туры, и в визы, даёт два диалога на одной карточке, и это
        # не контейнер, а тот же человек. Замер 11.09: таких карточек 78 против 17
        # настоящих общих — считая диалоги, фильтр ошибался чаще, чем срабатывал.
        phone = str(getattr(conv, "user_id", "") or "").rsplit(":", 1)[-1]
        seen.setdefault(lead, set()).add(phone)
    return {lead for lead, phones in seen.items() if len(phones) > 1}


def _askable(conv: Any, now: datetime) -> bool:
    """Можно ли спрашивать. Один диалог — один вопрос; «клиент думает» покупает ещё один.

    Без ответа менеджера мы не возвращаемся: молчание — тоже ответ, а долбить человека
    одним и тем же вопросом каждый вечер значит отучить его читать сообщения совсем.
    """
    if _aware(getattr(conv, "sale_check_asked_at", None)) is None:
        return True
    snooze = _aware(getattr(conv, "sale_check_snooze_until", None))
    return snooze is not None and now >= snooze


def select_targets(convs: list, now: datetime, cfg: Any, *, enabled: bool | None = None) -> list:
    """Про кого спросить менеджера сегодня. Чистая функция — тестируется без сети.

    `enabled` передаёт джоба: тумблер живёт в БД, а не в env, и читать его здесь второй
    раз означало бы «кнопку включили, а код молчит» — дефект, который мы уже чинили (9117f3d).

    Порядок отбора важен: сначала самые свежие. Менеджер помнит вчерашний разговор лучше,
    чем недельный, и ответит точнее.
    """
    if not (getattr(cfg, "sale_check_enabled", False) if enabled is None else enabled):
        return []
    now = _aware(now) or datetime.now(timezone.utc)
    min_age = timedelta(hours=float(getattr(cfg, "sale_check_min_age_hours", 12)))
    max_age = timedelta(days=float(getattr(cfg, "sale_check_max_age_days", 14)))
    shared = _shared_leads(convs)
    out = []
    for conv in convs:
        if getattr(conv, "archived", False):
            continue
        if not _is_tour(conv):
            continue
        phone = str(getattr(conv, "phone", "") or getattr(conv, "user_id", ""))
        if any(phone.endswith(own) for own in OWN_NUMBERS):
            continue                       # наш же номер — партнёрский чат, не клиент
        if str(getattr(conv, "bitrix_lead_id", "") or "").strip() in shared:
            continue                       # общая карточка — спрашивать про неё нельзя
        if str(getattr(conv, "outcome", "") or "") in FINAL_OUTCOMES:
            continue                       # человек уже отметил исход — вопрос закрыт
        if not _askable(conv, now):
            continue
        if not _worked(conv):
            continue
        last = _aware(getattr(conv, "last_message_at", None))
        if last is None or now - last < min_age:
            continue                       # разговор ещё идёт, об исходе рано
        if now - last > max_age:
            continue                       # месячной давности разговор менеджер не помнит
        out.append(conv)
    out.sort(key=lambda c: _aware(getattr(c, "last_message_at", None)) or now, reverse=True)
    return out[:max(1, int(getattr(cfg, "sale_check_max_items", 5)))]


# --- ссылка ---------------------------------------------------------------------------
def _secret(cfg: Any) -> str:
    return str(getattr(cfg, "webhook_secret", "") or "").strip()


def _sign(payload: str, cfg: Any) -> str:
    digest = hmac.new(_secret(cfg).encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest)[:16].decode()


def _cid(conv_key: str, cfg: Any) -> str:
    """Непрозрачный отпечаток диалога для адреса: номер из него не восстанавливается."""
    raw = hmac.new(_secret(cfg).encode(), f"cid|{conv_key}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw)[:16].decode()


def _b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _unb64(raw: str) -> str:
    pad = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + pad).decode()


def make_link(conv_key: str, outcome: str, cfg: Any, login: str = "") -> str:
    """Ссылка «отметить исход». Пустая строка — если нельзя выдать (ловушка 5).

    В подписанный payload входит и логин менеджера: без него в журнале не остаётся следа,
    кто отметил продажу, а для записи в боевой CRM это обязательный минимум.
    """
    if not _secret(cfg) or outcome not in OUTCOMES:
        return ""
    payload = f"{_cid(conv_key, cfg)}|{outcome}|{login}"
    token = f"{_b64(payload)}.{_sign(payload, cfg)}"
    base = str(getattr(cfg, "public_base_url", "") or "").rstrip("/")
    return f"{base}/sale/{token}"


def verify_token(token: str, cfg: Any) -> tuple[str, str, str] | None:
    """`(cid, outcome, login)` для валидного токена, иначе None. Никогда не бросает."""
    if not _secret(cfg):
        return None                        # fail closed: нет секрета — нет доверия ссылке
    try:
        body, _, sig = str(token or "").partition(".")
        if not body or not sig:
            return None
        payload = _unb64(body)
        if not hmac.compare_digest(sig, _sign(payload, cfg)):
            return None
        cid, _, tail = payload.partition("|")
        outcome, _, login = tail.partition("|")
        if outcome not in OUTCOMES or not cid:
            return None
        return cid, outcome, login
    except Exception:  # noqa: BLE001 — кривая ссылка не повод падать
        return None


# --- текст сообщения ------------------------------------------------------------------
def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


# Кто сказал последнюю реплику. Без подписи менеджер читает свои же слова как клиентские:
# на проде 400 диалогов из 794 заканчиваются репликой менеджера, 199 — репликой бота.
# «менеджер», а не «вы»: список один на обеих (решение 11.09), и 11.09 Айсина получила
# «вы: *Ademi Orozakunova:* Добрый день…» — чужие слова, выданные за её собственные.
_SAID = {"client": "клиент", "manager": "менеджер", "bot": "бот"}


def last_line(conv: Any, limit: int = 70) -> str:
    """Последняя реплика с подписью, кто её сказал. Пусто — если реплики нет."""
    text = _clip(getattr(conv, "last_text", ""), limit)
    if not text:
        return ""
    who = _SAID.get(str(getattr(conv, "last_sender", "") or ""), "")
    return f"{who}: «{text}»" if who else f"«{text}»"


def _ago(conv: Any, now: datetime) -> str:
    last = _aware(getattr(conv, "last_message_at", None))
    if last is None:
        return ""
    days = (now - last).days
    return "сегодня" if days <= 0 else ("вчера" if days == 1 else f"{days} дн. назад")


def describe(conv: Any, now: datetime | None = None) -> str:
    """Как назвать клиента менеджеру. Телефон целиком не пишем — это переписка в чате.

    Замер на проде 10.09: `qualification.destination` заполнено меньше чем у половины
    кандидатов, а последняя реплика («уже неактуально, спасибо») есть у всех и опознаётся
    менеджером мгновенно. Поэтому реплика — основной опознавательный признак.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    phone = str(getattr(conv, "phone", "") or getattr(conv, "user_id", ""))
    tail = phone[-4:] if len(phone) >= 4 else phone
    q = dict(getattr(conv, "qualification", None) or {})
    where = str(q.get("destination") or q.get("country") or "").strip()
    # Список общий на обеих менеджерок (заказы по турам общие — решение Алана 11.09),
    # поэтому надо видеть, свой это клиент или коллеги.
    owner = str(getattr(conv, "assigned_to", "") or "").strip() or "ничей"
    return " · ".join(x for x in (f"…{tail}", where, _ago(conv, now), owner) if x)


def recorded_facts(conv: Any) -> list[tuple[str, str]]:
    """Что бот записал по клиенту — парами «подпись, значение», в порядке анкеты.

    Показываем это менеджеру на странице подтверждения, а не отправляем его сверять
    карточку в Битриксе: человек проверяет то, что видит, и не проверяет то, ради чего
    надо открыть второе приложение и найти клиента руками.
    """
    from app.core.manager_brief import FIELD_LABELS

    data = dict(getattr(conv, "qualification", None) or {})
    out = []
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        out.append((FIELD_LABELS.get(key, key), _clip(str(value), 60)))
    return out


def card_link(conv: Any, cfg: Any) -> str:
    """Прямая ссылка на карточку клиента в портале. Пусто, если вести некуда."""
    base = str(getattr(cfg, "bitrix_portal_url", "") or "").rstrip("/")
    lead_id = str(getattr(conv, "bitrix_lead_id", "") or "").strip()
    return f"{base}/crm/lead/details/{lead_id}/" if base and lead_id else ""


def render_message(convs: list, cfg: Any, now: datetime | None = None,
                   login: str = "") -> str:
    """Одно сообщение менеджеру со списком и тремя ссылками на каждый диалог."""
    now = _aware(now) or datetime.now(timezone.utc)
    lines = ["Добрый вечер! Отметьте, чем закончилось — одно касание:", ""]
    for i, conv in enumerate(convs, 1):
        lines.append(f"{i}. {describe(conv, now)}")
        last = last_line(conv)
        if last:
            lines.append(f"   {last}")
        lines.append(f"   ✅ Оплатил: {make_link(conv.user_id, 'won', cfg, login)}")
        lines.append(f"   ❌ Не сложилось: {make_link(conv.user_id, 'lost', cfg, login)}")
        lines.append(f"   ⏳ Ещё думает: {make_link(conv.user_id, 'thinking', cfg, login)}")
        lines.append("")
    lines.append("Ссылка открывает страницу с кнопкой — само нажатие ничего не записывает.")
    lines.append("Это нужно, чтобы в отчёте по турам были настоящие цифры продаж.")
    return "\n".join(lines)


# --- применение отметки ---------------------------------------------------------------
async def apply_outcome(conv: Any, outcome: str, *, convert=None) -> bool:
    """Решение «что делать с этим исходом». True — записали впервые, False — нечего делать.

    «Оплатил» ведёт лид в «Подписан», и дальше существующий read-back сам заводит сделку
    в воронке FrunzeTravel. «Не сложилось» карточку не трогает: статус «Некачественный»
    ставит человек, бот такие решения за него не принимает.
    """
    if outcome not in FINAL_OUTCOMES:
        return False
    if str(getattr(conv, "outcome", "") or "") in FINAL_OUTCOMES:
        return False                       # уже отмечено — второй раз ничего не делаем
    conv.outcome = outcome
    if outcome == "won" and convert is not None:
        lead_id = str(getattr(conv, "bitrix_lead_id", "") or "")
        if lead_id:
            await convert(conv.user_id, lead_id)
    return True


async def _convert_lead(conv_key: str, lead_id: str, *, conv: Any = None) -> None:
    """Перевести лид в «Подписан». Дальше read-back сам заведёт сделку в FrunzeTravel.

    Два предохранителя, без которых запись в боевой портал шла бы в обход всего остального:
    тумблеры Битрикса (глобальный и по боту) и терминальный статус карточки — если человек
    руками поставил «Некачественный» или лид уже «Подписан», мы не переписываем его решение.
    """
    from app.integrations.crm import bitrix_pipeline
    from app.integrations.crm.bitrix24 import Bitrix24Crm
    from app.integrations.panel.store import get_conversation_store

    if conv is not None and not await bitrix_pipeline._enabled(conv):
        log.info("sale check: связка с Битриксом выключена, лид не трогаем conv=%s", conv_key)
        return
    # Ссылки на общие карточки уже разосланы менеджерам — отозвать их нельзя, поэтому
    # защита стоит и на самом нажатии, а не только в отборе. Ответ менеджера при этом
    # сохраняется: врать в отчёте нельзя, но и чужую карточку двигать нельзя.
    if lead_id in _shared_leads(await get_conversation_store().all_conversations_light()):
        log.warning("sale check: лид %s общий для нескольких клиентов — в портал не пишем"
                    " (conv=%s)", lead_id, conv_key)
        return
    crm = Bitrix24Crm()
    status = str((await crm.get_lead(lead_id)).get("STATUS_ID") or "")
    if status in bitrix_pipeline.TERMINAL_STATUSES:
        log.info("sale check: лид уже в терминальном статусе %s, не трогаем conv=%s",
                 status, conv_key)
        return
    await crm.update_stage_status(lead_id, "CONVERTED")
    log.info("sale check: лид переведён в Подписан conv=%s", conv_key)


async def _find_by_cid(cid: str, cfg: Any):
    """Найти диалог по непрозрачному отпечатку из ссылки. None — не нашли."""
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    for conv in await store.all_conversations_light():
        if hmac.compare_digest(_cid(conv.user_id, cfg), cid):
            return conv
    return None


async def mark(cid: str, outcome: str, cfg: Any, login: str = "", *,
               amount: str = "", currency: str = "KGS") -> tuple[str, Any]:
    """Записать ответ менеджера. Возвращает `(результат, диалог)`.

    Результат: `saved` / `saved_no_crm` / `repeat` / `snoozed` / `unknown`. Менеджеру это
    три разных ответа — «записал», «уже было отмечено» и «ссылка устарела»; схлопывать их
    в один текст значит врать человеку, который пришёл проверить.
    """
    from app.integrations.panel.store import get_conversation_store

    conv = await _find_by_cid(cid, cfg)
    if conv is None:
        return "unknown", None
    store = get_conversation_store()
    conv_key = conv.user_id

    if outcome == "thinking":
        days = float(getattr(cfg, "sale_check_snooze_days", 3))
        until = datetime.now(timezone.utc) + timedelta(days=days)
        await store.update_meta(conv_key, sale_check_snooze_until=until)
        await store.add_audit(login or "sale-link", "sale_check_snooze", conv_key,
                              f"клиент думает, спросим через {int(days)} дн.")
        log.info("sale check: клиент думает, спросим позже conv=%s", conv_key)
        return "snoozed", conv

    if str(getattr(conv, "outcome", "") or "") in FINAL_OUTCOMES:
        return "repeat", conv
    if not await store.claim_outcome(conv_key, outcome):
        return "repeat", conv              # кто-то успел раньше — второй записи не будет
    await store.add_audit(login or "sale-link", f"sale_check_{outcome}", conv_key,
                          "отметка по ссылке из вечернего вопроса")
    # Сумму пишем ПОСЛЕ защёлки исхода и только у продажи: она уезжает в поле выручки
    # сделки, и повторное нажатие не должно её переписывать. Не разобрали — подтверждение
    # всё равно сохранено, сумму менеджер проставит в карточке.
    if outcome == "won" and amount:
        if await _save_amount(conv_key, amount, currency) is not None:
            conv = await store.get(conv_key) or conv
    try:
        await apply_outcome(conv, outcome,
                            convert=functools.partial(_convert_lead, conv=conv))
    except Exception:  # noqa: BLE001 — портал лежит, но ответ менеджера уже сохранён
        log.warning("sale check: исход записан, портал недоступен conv=%s", conv_key,
                    exc_info=True)
        return "saved_no_crm", conv
    log.info("sale check: исход отмечен conv=%s outcome=%s", conv_key, outcome)
    return "saved", conv


# --- джоба ------------------------------------------------------------------------------
async def run(now: datetime | None = None) -> None:
    """Джоба планировщика: вечером спросить каждого менеджера про его диалоги.

    `now` инъектируется тестом: без этого проверить, что джоба проходит целиком и не
    повторяется на следующем тике, можно было бы только в конкретный час суток.
    """
    from app.config import settings
    from app.core import flags
    from app.core.calendar_brief import _push_telegram, _token
    from app.integrations.panel.store import get_conversation_store

    if not await flags.get_flag("sale_check_enabled", settings.sale_check_enabled):
        return
    if not _secret(settings):
        log.warning("sale check: пустой webhook_secret — ссылки не выдаём")
        return
    hour = int(getattr(settings, "sale_check_hour", 18))
    if hour not in DAY_HOURS:
        log.warning("sale check: час %s вне рабочего времени — не пишем", hour)
        return
    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    if local.hour != hour:
        return                             # спрашиваем раз в день, в один и тот же час

    token = _token()
    if not token:
        return
    store = get_conversation_store()
    convs = await store.all_conversations_light()

    # Очередь ОДНА на всех: заказы по турам у менеджеров общие, и делить их по владельцу
    # значит терять 29 ничейных диалогов в неделю (17% потока) — их не спросили бы никогда.
    # Кто первым нажал, тот и закрыл: повторное нажатие ловит атомарная защёлка исхода.
    targets = select_targets(convs, now, settings, enabled=True)
    if not targets:
        return

    only = {str(x).strip().lower() for x in (settings.sale_check_managers or []) if str(x).strip()}
    asked = failed = 0
    for mgr in settings.manager_list():
        login = (mgr.login or "").strip().lower()
        chat_id = (getattr(mgr, "telegram_chat_id", "") or "").strip()
        if only and login not in only:
            continue                       # получатели заданы явно — остальных не трогаем
        if not chat_id:
            continue                       # некому слать — молча пропускаем
        # Защёлка на КАЖДОГО менеджера отдельно, как у календарного брифа. Одна общая
        # блокировала весь день всем: 11.09 рассылка ушла одной Адеми, и вторая туровая
        # менеджер (Айсина, у неё половина трафика) не получила бы вопрос вовсе.
        sent_key = f"sale_check_sent_{login}_{local:%Y%m%d}"
        if await flags.get_flag(sent_key, False):
            continue                       # этому менеджеру за сегодня уже писали
        text = render_message(targets, settings, now, login)
        # Превью гасим: сервер Telegram сам ходит GET-ом по первой ссылке в сообщении.
        if not await _push_telegram(token, chat_id, text, disable_web_page_preview=True):
            failed += 1                    # не дошло — на следующем тике попробуем снова
            continue
        # Защёлку ставим по факту доставки: рестарт контейнера в этот же час иначе даёт
        # менеджеру второе такое же сообщение.
        await flags.set_flag(sent_key, True)
        asked += 1
        log.info("sale check: спросили менеджера %s про %d диалог(ов)", login, len(targets))

    # Помечаем диалоги спрошенными, только когда СПИСОК ДОШЁЛ ДО ВСЕХ. Иначе сбой доставки
    # одному тихо выбрасывал остальных из сегодняшнего дня: отбор на следующем тике вернул
    # бы пусто, а назавтра эти диалоги уже вне окна свежести. Кому дошло — тот защищён
    # своей защёлкой и второго сообщения не получит.
    if asked and not failed:
        for conv in targets:
            # Спросили — снимаем отсрочку: «ещё думает» покупает ровно один новый вопрос.
            await store.update_meta(conv.user_id, sale_check_asked_at=now,
                                    clear_sale_snooze=True)
