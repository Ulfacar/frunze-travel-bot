"""Точка входа FastAPI: вебхуки каналов + healthcheck."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import time
from collections import OrderedDict

from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

from app.channels.bitrix_openlines import BitrixOpenLinesAdapter, bot_id_from_event, nest_form
from app.channels.telegram import TelegramAdapter
from app.channels.wappi import (
    WappiAdapter,
    is_delivery_status,
    is_incoming_user_message,
    parse_delivery_status,
)
from app.config import settings
from app.core.bots import registry
from app.core.orchestrator import Orchestrator
from app.integrations.panel.store import get_conversation_store

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём схему БД (идемпотентно), если используется Postgres под CRM или панель.
    if settings.crm_backend == "postgres" or settings.panel_backend == "postgres":
        from app.integrations.crm.db import init_db
        await init_db()
        log.info("Postgres: схема (сделки/диалоги) готова")
    yield


app = FastAPI(title="Frunze Travel Bot", lifespan=lifespan)
# Сессии менеджеров (подписанная cookie) — для логина в админ-панель.
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, max_age=14 * 24 * 3600)

# Наблюдаемость: время последнего входящего сообщения клиента (детектор «тишины»).
_LAST_INBOUND: dict[str, float] = {"ts": 0.0}
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

# Дев-демо: одиночный бот в Telegram (keyword-детект воронки). Поднимается только
# при заданном токене — прод работает через Bitrix и Telegram-токена не требует.
_telegram = TelegramAdapter() if settings.telegram_bot_token else None
_telegram_orchestrator = Orchestrator(channel=_telegram) if _telegram else None

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


@app.get("/health")
async def health() -> dict:
    last = _LAST_INBOUND["ts"]
    return {
        "status": "ok",
        "last_inbound_seconds_ago": round(time.time() - last, 1) if last else None,
    }


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request) -> dict:
    if _telegram_orchestrator is None:
        return {"ok": False, "reason": "telegram_disabled"}
    raw = await request.json()
    msg = await _telegram.parse(raw)
    await _telegram_orchestrator.handle(msg)  # не-текст/перехват — внутри оркестратора
    return {"ok": True}


@app.post("/webhook/bitrix")
async def bitrix_webhook(request: Request) -> dict:
    """Единый эндпоинт Открытых линий: маршрут к нужному боту по BOT_ID события imbot.

    Bitrix шлёт событие form-urlencoded (`data[PARAMS][...]`); JSON принимаем тоже
    (тесты/ручная отладка). `nest_form` приводит оба к вложенному dict.
    """
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
    payload = await request.json()
    # Wappi: события в payload["messages"]; на всякий случай поддерживаем и плоский формат.
    events = payload.get("messages") if isinstance(payload, dict) else None
    if not events:
        events = [payload]

    handled = 0
    for raw in events:
        if not isinstance(raw, dict):
            continue

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

        if not is_incoming_user_message(raw):
            continue

        if _seen_before(str(raw.get("id", ""))):
            continue  # дубль доставки вебхука — уже обработали

        profile_id = str(raw.get("profile_id", ""))
        orchestrator = _wappi_orchestrators.get(profile_id)
        if orchestrator is None:
            log.warning("Wappi-событие без сопоставленного бота (profile_id=%s)", profile_id)
            continue

        _LAST_INBOUND["ts"] = time.time()
        msg = await orchestrator.channel.parse(raw)
        await orchestrator.handle(msg)
        handled += 1

    return {"ok": True, "handled": handled}
