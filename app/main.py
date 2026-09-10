"""Точка входа FastAPI: вебхуки каналов + healthcheck."""
from __future__ import annotations

import html
import logging
import secrets
from contextlib import asynccontextmanager

from collections import OrderedDict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.channels.bitrix_openlines import BitrixOpenLinesAdapter, bot_id_from_event, nest_form
from app.channels.telegram import TelegramAdapter
from app.channels.wappi import (
    WappiAdapter,
    is_delivery_status,
    is_incoming_user_message,
    is_outgoing_echo,
    outgoing_echo_phone,
    outgoing_echo_text,
    parse_delivery_status,
)
from app.config import BotConfig, settings
from app.core import observ
from app.core.bots import registry
from app.core.intercept import set_intercept
from app.core.orchestrator import Orchestrator
from app.core.own_outbound import is_own
from app.integrations.panel.store import get_conversation_store

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
observ.install_request_id_logging()  # WP0: text logs with a request_id field
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Явно сообщаем на старте: заполненный fallback пока не даёт ложной гарантии резерва.
    from app.integrations.stt.registry import warn_fallback_configuration
    warn_fallback_configuration()
    # Создаём схему БД (идемпотентно), если используется Postgres под CRM или панель.
    if settings.crm_backend == "postgres" or settings.panel_backend == "postgres":
        from app.integrations.crm.db import init_db
        await init_db()
        log.info("Postgres: схема (сделки/диалоги) готова")
    try:
        from app.core.faq import seed_defaults
        await seed_defaults()
    except Exception:  # noqa: BLE001
        log.warning("FAQ defaults seed failed", exc_info=True)
    # Фоновые джобы: watchdog-алерты + автодожим. Автодожим регистрируем всегда —
    # джоба сама сверяется с рантайм-флагом (переключается кнопкой в админке без рестарта).
    from app.core import (awaiting, balance_guard, bitrix_pipeline_job, calendar_brief,
                          channel_heartbeat, followup, instant_handoff, manager_sync,
                          morning_brief, outcome_infer, rescore, scheduler, tours_health,
                          tours_summary, wappi_health, watchdog)
    scheduler.register("watchdog", watchdog.run)
    # Основной сторож каналов: спрашивает у Wappi, авторизован ли профиль. Точный факт
    # вместо догадки по тишине — 03.08 Wappi знал о разлогине, а мы 12 часов не знали.
    scheduler.register("wappi_health", wappi_health.run)
    # Предохранитель к нему: ловит «профиль жив, но вебхук до нас не доходит», чего
    # статус Wappi не покажет. Порог 12 часов — более чувствительные дают ложные тревоги.
    scheduler.register("channel_heartbeat", channel_heartbeat.run)
    # Деньги и живость чужих систем: 21.08 бот замолчал на исходе баланса OpenRouter, и
    # узнали об этом от клиента. Порог считается в днях остатка, а не в долларах (gated OFF).
    scheduler.register("balance_guard", balance_guard.run)
    scheduler.register("awaiting", awaiting.run)
    scheduler.register("followup", followup.run)
    scheduler.register("rescore", rescore.run)          # ghost-ре-скоринг тира готовности
    scheduler.register("outcome_infer", outcome_infer.run)  # LLM-исход (gated OFF)
    scheduler.register("morning_brief", morning_brief.run)  # утренний горячий лист (gated OFF)
    scheduler.register("calendar_brief", calendar_brief.run)  # персональный план дня (gated OFF)
    scheduler.register("tours_summary", tours_summary.run)  # еженедельная тур-сводка владельцу (gated OFF)
    # Дайджест готовых заявок для каналов, переведённых с мгновенных пушей (gated OFF).
    # Мгновенный пуш идёт не отсюда, а из orchestrator по факту собранной заявки.
    scheduler.register("handoff_digest", instant_handoff.run_digest)
    # Догоняющая отправка: пуш из orchestrator уходит только в момент ответа бота, и
    # заявка без владельца в ту секунду не получала второй попытки НИКОГДА (12 из 17
    # потерянных за июль). Джоба досылает готовые заявки, до которых пуш не дошёл.
    scheduler.register("handoff_catchup", instant_handoff.run_catchup)
    # Квота TourVisor: предупредить владельца ДО того, как поиск туров умрёт молча.
    from app.integrations.tourvisor import quota as tv_quota
    scheduler.register("tourvisor_quota", tv_quota.run)
    # Здоровье подбора: кричать, когда бот массово отвечает «ничего не нашлось».
    # Прежде мерили расход API, а не результат — поэтому поломка жила месяц незамеченной.
    scheduler.register("tours_health", tours_health.run)
    # Ответы менеджеров с телефона: Wappi не шлёт эхо исходящих, поэтому перехваченные
    # диалоги вечно висят «ждёт ответа». Подтягиваем их сами, пока тип вебхука не включён.
    scheduler.register("manager_sync", manager_sync.run)
    scheduler.register("bitrix_pipeline_read_back", bitrix_pipeline_job.run)
    # Сторож самого контроллера карточек: очередь стоит, джоба встала, портал сыплет
    # ошибками. 07.09 проход сутки отдавал moved=0, и это не заметил никто (gated OFF).
    from app.core import pipeline_metrics
    scheduler.register("pipeline_controller", pipeline_metrics.run)
    # Вечерний вопрос менеджеру «клиент оплатил?»: без него продажи не доезжают до
    # отчёта, и владелец пятую неделю видит «Продано: 0» (gated OFF).
    from app.core import sale_check
    scheduler.register("sale_check", sale_check.run)
    scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Frunze Travel Bot", lifespan=lifespan)
# Сессии менеджеров (подписанная cookie) — для логина в админ-панель.
# https_only=True ставит Secure-флаг (TLS терминирует nginx, ходим по https);
# same_site=lax — базовая защита от CSRF.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                   max_age=14 * 24 * 3600, https_only=True, same_site="lax")
# WP0: correlation id per request (X-Request-ID). Added last → outermost middleware,
# so it binds the id before everything and echoes the header on the way out.
app.add_middleware(observ.RequestIdMiddleware)


def _verify_webhook(request: Request, *, telegram: bool = False) -> bool:
    """Проверка секрета входящего вебхука. Пустой settings.webhook_secret → пропускаем
    (обратная совместимость, чтобы не уронить прод до обновления URL у провайдера)."""
    expected = settings.webhook_secret
    if not expected:
        return True
    if telegram:
        got = request.headers.get("x-telegram-bot-api-secret-token", "")
    else:
        got = request.query_params.get("s", "") or request.headers.get("x-webhook-secret", "")
    return bool(got) and secrets.compare_digest(got, expected)

# Наблюдаемость «тишины» вебхуков живёт в app.core.observ (общий доступ с watchdog).
# Дедуп входящих Wappi по id события (повторная доставка вебхука не плодит ответы).
_seen_wappi_ids: "OrderedDict[str, None]" = OrderedDict()
_SEEN_MAX = 2000


def _seen_before(event_id: str) -> bool:
    """True, если событие с таким id уже обрабатывали (защита от дублей доставки)."""
    if not event_id:
        return False
    if event_id in _seen_wappi_ids:
        return True
    _seen_wappi_ids[event_id] = None
    if len(_seen_wappi_ids) > _SEEN_MAX:
        _seen_wappi_ids.popitem(last=False)
    return False

# Админ-панель (канбан диалогов + чат + перехват).
if settings.admin_enabled:
    from app.admin.router import router as admin_router
    app.include_router(admin_router)

# Витрина подборки туров `/t/<slug>` — её открывает КЛИЕНТ из WhatsApp, поэтому она
# публична и живёт отдельно от админки: логина у клиента нет и быть не может.
from app.web.offers import router as offers_router  # noqa: E402

app.include_router(offers_router)

# Дев-демо: одиночный бот в Telegram (keyword-детект воронки). Поднимается только
# при заданном токене — прод работает через Bitrix и Telegram-токена не требует.
_telegram = TelegramAdapter() if settings.telegram_bot_token else None
_telegram_orchestrator = Orchestrator(channel=_telegram) if _telegram else None

# Тестовые Telegram-боты (песочница): по оркестратору на каждого, со своим токеном и
# ЖЁСТКИМ сценарием (как WhatsApp-боты). Маршрут — /webhook/telegram/<id>. Ключ диалога
# bot_id:user_id, поэтому туры и визы в Telegram не пересекаются.
_telegram_test: dict[str, tuple[TelegramAdapter, Orchestrator]] = {}
for _tb in settings.telegram_bots:
    _tg_bot = BotConfig(id=_tb.id, scenario=_tb.scenario, title=_tb.title)
    _tg_adapter = TelegramAdapter(token=_tb.token)
    _telegram_test[_tb.id] = (_tg_adapter, Orchestrator(channel=_tg_adapter, bot=_tg_bot))

# Прод: по оркестратору на каждого настроенного бота (свой канал + сценарий).
_bot_orchestrators: dict[str, Orchestrator] = {
    bot.id: Orchestrator(channel=BitrixOpenLinesAdapter(bot=bot), bot=bot)
    for bot in registry.all()
}

# Прямой WhatsApp через Wappi (Схема B, тест/MVP) — оркестратор на профиль с заданным id.
_wappi_orchestrators: dict[str, Orchestrator] = {
    bot.wappi_profile_id: Orchestrator(channel=WappiAdapter(bot=bot), bot=bot)
    for bot in registry.all()
    if bot.wappi_profile_id
}


_ECHO_LOOKBACK = 6


async def _is_bot_echo(panel, key: str, text: str) -> bool:
    """Не наша ли это собственная реплика, вернувшаяся эхом от провайдера.

    Второй рубеж после `is_own`. Первый живёт 15 минут в памяти процесса, и после рестарта
    или задержки эха бот принял бы свой же текст за ответ менеджера — а это автоперехват,
    то есть бот замолчал бы на этом клиенте до вмешательства человека.

    Сравниваем с последними репликами бота в диалоге по нормализованному тексту. Ошибиться
    можно только если менеджер слово в слово повторил недавнюю фразу бота — тогда мы
    потеряем одно сообщение в панели; цена несопоставима с молчанием бота.
    """
    needle = " ".join((text or "").split())
    if not needle:
        return False
    try:
        conv = await panel.get(key)
    except Exception:  # noqa: BLE001 — сомнение трактуем в пользу записи
        return False
    for message in reversed(list(getattr(conv, "messages", None) or [])[-_ECHO_LOOKBACK:]):
        if getattr(message, "sender", "") != "bot":
            continue
        if " ".join((getattr(message, "text", "") or "").split()) == needle:
            return True
    return False


async def _handle_manager_echo(raw: dict) -> None:
    event_id = str(raw.get("id", ""))
    if _seen_before(event_id):
        return
    if is_own(event_id):
        return

    profile_id = str(raw.get("profile_id", ""))
    orchestrator = _wappi_orchestrators.get(profile_id)
    if orchestrator is None or orchestrator.bot is None:
        log.warning("Wappi manager echo without mapped bot (profile_id=%s)", profile_id)
        return

    phone = outgoing_echo_phone(raw)
    text = outgoing_echo_text(raw)
    if not phone or not text:
        return

    bot = orchestrator.bot
    key = f"{bot.id}:{phone}"
    panel = get_conversation_store()
    if await _is_bot_echo(panel, key, text):
        return
    await panel.add_message(
        key,
        "manager",
        text,
        channel="whatsapp",
        bot_id=bot.id,
        chat_id=str(raw.get("chatId") or raw.get("to") or ""),
        status="sent",
        provider_msg_id=event_id,
        phone=phone,
    )
    # Echo не сообщает логин менеджера: существующего владельца сохраняем, а ничей
    # диалог оставляем честно нераспределённым.
    await panel.update_meta(key, funnel=bot.scenario)
    await set_intercept(key, True, automatic=True)
    # Зеркало реплики менеджера в Bitrix (best-effort, фоном).
    from app.integrations.crm import bitrix_mirror
    bitrix_mirror.fire(key, sender="manager", text=text, phone=phone,
                       funnel=bot.scenario, bot_id=bot.id)


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "last_inbound_seconds_ago": observ.last_inbound_ago(),
    }


_SALE_TITLES = {
    "won": ("Клиент оплатил", "Продажа попадёт в отчёт по турам, а карточка уедет в «Подписан»."),
    "lost": ("Сделка не состоялась", "Отметим, что клиент не купил. Карточку в Битриксе не трогаем."),
    "thinking": ("Клиент ещё думает", "Отложим вопрос и вернёмся к нему через несколько дней."),
}


@app.get("/sale/{token}", response_class=HTMLResponse)
async def sale_confirm(token: str) -> HTMLResponse:
    """Страница подтверждения. НИЧЕГО не записывает — записывает только POST с кнопки.

    Открытие ссылки обязано быть безопасным: Telegram сам ходит GET-ом по первой ссылке
    в сообщении, чтобы построить превью, и записал бы продажу за менеджера в первый же
    вечер. То же делают антивирус на телефоне и предзагрузка браузера.
    """
    from app.core import sale_check

    parsed = sale_check.verify_token(token, settings)
    if parsed is None:
        return HTMLResponse(_sale_page("Ссылка недействительна",
                                       "Похоже, адрес повреждён. Отметьте исход в панели."),
                            status_code=400)
    cid, outcome, _login = parsed
    conv = await sale_check._find_by_cid(cid, settings)
    if conv is None:
        return HTMLResponse(_sale_page("Ссылка устарела",
                                       "Такого диалога больше нет. Отметьте исход в панели."),
                            status_code=404)
    title, body = _SALE_TITLES.get(outcome, ("Отметить исход", ""))
    who = html.escape(sale_check.describe(conv))
    current = str(getattr(conv, "outcome", "") or "")
    if outcome != "thinking" and current in sale_check.FINAL_OUTCOMES:
        already = "оплатил" if current == "won" else "не купил"
        return HTMLResponse(_sale_page(
            "Уже отмечено",
            f"По диалогу {who} уже стоит «{already}». Если это ошибка — поправьте в панели."))
    form = (f'<form method="post" action="/sale/{html.escape(token)}">'
            f'<button type="submit">Подтвердить</button></form>')
    return HTMLResponse(_sale_page(title, f"{who}<br><br>{body}", extra=form))


@app.post("/sale/{token}", response_class=HTMLResponse)
async def sale_apply(token: str) -> HTMLResponse:
    """Менеджер нажал кнопку на странице — только здесь что-то меняется."""
    from app.core import sale_check

    parsed = sale_check.verify_token(token, settings)
    if parsed is None:
        return HTMLResponse(_sale_page("Ссылка недействительна",
                                       "Похоже, адрес повреждён. Отметьте исход в панели."),
                            status_code=400)
    cid, outcome, login = parsed
    result, conv = await sale_check.mark(cid, outcome, settings, login)
    who = html.escape(sale_check.describe(conv)) if conv is not None else ""
    pages = {
        "saved": ("Записано ✅",
                  "Спасибо! Продажа учтена — она попадёт в отчёт по турам."
                  if outcome == "won" else "Спасибо! Отметили, что сделка не состоялась."),
        "saved_no_crm": ("Записано ✅",
                         "Ответ сохранён. Карточку в Битриксе обновить не удалось — "
                         "проверьте её вручную."),
        "snoozed": ("Отложили ⏳", "Хорошо, спросим про этот диалог ещё раз через пару дней."),
        "repeat": ("Уже отмечено", "Этот диалог отметили раньше. Ничего менять не нужно."),
        "unknown": ("Ссылка устарела", "Такого диалога больше нет. Отметьте исход в панели."),
    }
    title, body = pages.get(result, pages["unknown"])
    status = 404 if result == "unknown" else 200
    return HTMLResponse(_sale_page(title, f"{who}<br><br>{body}" if who else body),
                        status_code=status)


def _sale_page(title: str, body: str, extra: str = "") -> str:
    """Простая страница: менеджер открывает её с телефона на секунду."""
    return (
        "<!doctype html><html lang=ru><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width, initial-scale=1'>"
        "<meta name=robots content='noindex'>"
        f"<title>{title}</title><style>"
        "body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;"
        "background:#F1F5F9;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#0F172A}"
        ".card{background:#fff;border-radius:16px;padding:32px 28px;max-width:420px;margin:20px;"
        "box-shadow:0 6px 24px rgba(15,23,42,.08);text-align:center}"
        "h1{font-size:22px;margin:0 0 10px}p{color:#475569;font-size:15px;line-height:1.5;margin:0}"
        "button{margin-top:22px;width:100%;padding:15px 20px;font-size:17px;font-weight:600;"
        "color:#fff;background:#0E5C57;border:0;border-radius:12px;cursor:pointer}"
        "</style></head><body><div class=card>"
        f"<h1>{title}</h1><p>{body}</p>{extra}</div></body></html>"
    )


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if not _verify_webhook(request, telegram=True):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    if _telegram_orchestrator is None:
        return {"ok": False, "reason": "telegram_disabled"}
    raw = await request.json()
    msg = await _telegram.parse(raw)
    await _telegram_orchestrator.handle(msg)  # не-текст/перехват — внутри оркестратора
    return {"ok": True}


@app.post("/webhook/telegram/{bot_id}")
async def telegram_test_webhook(bot_id: str, request: Request):
    """Тестовый Telegram-бот (песочница): свой токен + жёсткий сценарий (туры/визы)."""
    if not _verify_webhook(request, telegram=True):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    entry = _telegram_test.get(bot_id)
    if entry is None:
        return JSONResponse({"ok": False, "reason": "unknown_bot"}, status_code=404)
    adapter, orchestrator = entry
    raw = await request.json()
    msg = await adapter.parse(raw)
    await orchestrator.handle(msg)
    return {"ok": True}


@app.post("/webhook/bitrix")
async def bitrix_webhook(request: Request) -> dict:
    """Единый эндпоинт Открытых линий: маршрут к нужному боту по BOT_ID события imbot.

    Bitrix шлёт событие form-urlencoded (`data[PARAMS][...]`); JSON принимаем тоже
    (тесты/ручная отладка). `nest_form` приводит оба к вложенному dict.
    """
    if not _verify_webhook(request):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        flat: object = await request.json()
    else:
        flat = list((await request.form()).multi_items())
    event = nest_form(flat)

    bitrix_bot_id = bot_id_from_event(event)
    bot = registry.by_bitrix_bot_id(bitrix_bot_id) if bitrix_bot_id else None
    if bot is None:
        log.warning("Bitrix-событие без сопоставленного бота (BOT_ID=%s)", bitrix_bot_id)
        return {"ok": False, "reason": "unknown_bot"}

    orchestrator = _bot_orchestrators[bot.id]
    msg = await orchestrator.channel.parse(event)
    await orchestrator.handle(msg)
    return {"ok": True, "bot": bot.id}


@app.post("/webhook/wappi")
async def wappi_webhook(request: Request) -> dict:
    """Прямой WhatsApp-канал (Wappi). Маршрут к боту по profile_id события.

    Wappi оборачивает события в `{"messages": [ {...}, ... ]}`; обрабатываем каждое.
    Игнорируем не-входящие, наши эхо (`is_me`), реакции и групповые чаты — отвечаем
    только в личных диалогах, иначе бот ответит сам себе или зафлудит группу.
    """
    if not _verify_webhook(request):
        return JSONResponse({"ok": False, "reason": "forbidden"}, status_code=403)
    payload = await request.json()
    # Wappi: события в payload["messages"]; на всякий случай поддерживаем и плоский формат.
    events = payload.get("messages") if isinstance(payload, dict) else None
    if not events:
        events = [payload]

    handled = 0
    for raw in events:
        if not isinstance(raw, dict):
            continue

        # Диагностика захвата ответов менеджера (31.07.2026). В базе за неделю НОЛЬ сообщений
        # с sender='manager': перехваченные диалоги навсегда висят в «ждёт ответа», потому что
        # ответ менеджера с телефона до нас не долетает. Нам нужно увидеть, какие события Wappi
        # шлёт на самом деле — ждём wh_type=incoming_message + is_me=true. Только форма события,
        # без телефона и текста: в логах не должно быть персональных данных.
        log.info("wappi event: wh_type=%s is_me=%s type=%s",
                 raw.get("wh_type"), raw.get("is_me"), raw.get("type"))

        # Статус доставки/прочтения нашего исходящего → обновляем галочку в панели.
        if is_delivery_status(raw):
            provider_msg_id, status = parse_delivery_status(raw)
            if provider_msg_id and status:
                try:
                    await get_conversation_store().mark_message_status(
                        provider_msg_id=provider_msg_id, status=status)
                except Exception:  # noqa: BLE001
                    log.warning("delivery-status update failed", exc_info=True)
            continue

        if settings.capture_manager_echo and is_outgoing_echo(raw):
            try:
                await _handle_manager_echo(raw)
            except Exception:  # noqa: BLE001
                log.warning("manager echo capture failed", exc_info=True)
            continue

        if not is_incoming_user_message(raw):
            continue

        if _seen_before(str(raw.get("id", ""))):
            continue  # дубль доставки вебхука — уже обработали

        profile_id = str(raw.get("profile_id", ""))
        orchestrator = _wappi_orchestrators.get(profile_id)
        if orchestrator is None:
            log.warning("Wappi-событие без сопоставленного бота (profile_id=%s)", profile_id)
            continue

        observ.note_inbound()
        # Отметка живости КОНКРЕТНОГО канала: агрегат выше не показывает смерть части.
        from app.core import channel_heartbeat
        await channel_heartbeat.note_inbound(getattr(orchestrator.bot, "id", "") or "")
        msg = await orchestrator.channel.parse(raw)
        await orchestrator.handle(msg)
        handled += 1

    return {"ok": True, "handled": handled}
