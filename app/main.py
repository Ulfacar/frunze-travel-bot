"""Точка входа FastAPI: вебхуки каналов + healthcheck."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.channels.bitrix_openlines import BitrixOpenLinesAdapter, bot_id_from_event, nest_form
from app.channels.telegram import TelegramAdapter
from app.channels.wappi import WappiAdapter, is_incoming_user_message
from app.config import settings
from app.core.bots import registry
from app.core.orchestrator import Orchestrator

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
    return {"status": "ok"}


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

    Игнорируем не-входящие и наши эхо (`is_me`), иначе бот ответит сам себе.
    """
    raw = await request.json()
    if not is_incoming_user_message(raw):
        return {"ok": True, "skipped": "not_incoming"}

    profile_id = str(raw.get("profile_id", ""))
    orchestrator = _wappi_orchestrators.get(profile_id)
    if orchestrator is None:
        log.warning("Wappi-событие без сопоставленного бота (profile_id=%s)", profile_id)
        return {"ok": False, "reason": "unknown_profile"}

    msg = await orchestrator.channel.parse(raw)
    await orchestrator.handle(msg)
    return {"ok": True, "bot": orchestrator.bot.id if orchestrator.bot else None}
