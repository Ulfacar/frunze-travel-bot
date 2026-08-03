"""Адаптер WhatsApp через Wappi Pro — прямой канал (Схема B, для теста/MVP).

Прод-схема A (WhatsApp → Bitrix Открытые линии → бот) это НЕ отменяет: данный
адаптер — короткий путь к живому WhatsApp-демо на оплаченных номерах Wappi, в
обход Bitrix. Входящее: webhook Wappi (`wh_type=incoming_message`). Исходящее:
`POST /api/sync/message/send?profile_id=<id>` с заголовком Authorization.

⚠ `is_me=true` — это эхо наших же исходящих; такие события игнорируем, иначе бот
ответит сам себе (бесконечный цикл).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.channels.base import Message
from app.config import BotConfig, settings

logger = logging.getLogger("channel.wappi")

_TEXT_TYPE = "chat"  # Wappi: тип текстового сообщения (остальное — медиа/вложения)
# Формы ниже уточнены по РЕАЛЬНОМУ payload голосового с прода 03.08 (tests/fixtures/
# wappi/voice_ptt.json): Wappi присылает `type="ptt"`, ссылку в `file_link` и длительность
# в `length_seconds`. Ни того, ни другого имени в наших первоначальных догадках не было —
# без живого события голосовые молча не распознавались бы, а причину искали бы в OpenAI.
# Остальные варианты оставлены: провайдер может отдать другую форму для audio/документа.
_VOICE_TYPES = {"ptt", "voice", "audio", "audio_message", "voice_message"}
_URL_KEYS = ("file_link", "file", "fileUrl", "file_url", "url", "media", "mediaUrl",
             "media_url", "download_url")
_MIME_KEYS = ("mimetype", "mime_type", "mime", "contentType")
_DURATION_KEYS = ("length_seconds", "duration", "seconds", "duration_sec", "audio_duration")


@dataclass(frozen=True)
class VoiceRef:
    url: str
    mime: str
    duration_sec: float


def extract_voice(raw: dict) -> VoiceRef | None:
    """Извлечь голосовое из вероятных форм Wappi, пока точная схема не известна."""
    if not isinstance(raw, dict) or str(raw.get("type") or "").lower() not in _VOICE_TYPES:
        return None
    containers: list[dict] = [raw]
    if isinstance(raw.get("message"), dict):
        containers.append(raw["message"])
    attaches = raw.get("attaches")
    if isinstance(attaches, dict):
        containers.append(attaches)
    elif isinstance(attaches, list):
        containers.extend(item for item in attaches if isinstance(item, dict))
    for key in ("file", "media"):
        if isinstance(raw.get(key), dict):
            containers.append(raw[key])

    # Ссылку, mime и длительность берём из ОДНОГО контейнера — того, где нашлась ссылка.
    # Разные вложения одного события описывают разные файлы: mime от аватарки рядом с
    # ссылкой на голос дал бы отказ по content-type уже после платного скачивания.
    for container in containers:
        url = _first_url(container)
        if url:
            return VoiceRef(url=url, mime=_first_mime(container),
                            duration_sec=_first_duration(container))
    logger.info("[voice-capture] не распознан формат голосового: keys=%s", sorted(raw.keys()))
    return None


def _first_url(container: dict) -> str:
    for key in _URL_KEYS:
        value = container.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    body = container.get("body")
    if isinstance(body, str) and body.strip().lower().startswith(("http://", "https://")):
        return body.strip()
    return ""


def _first_mime(container: dict) -> str:
    for key in _MIME_KEYS:
        value = container.get(key)
        if value not in (None, ""):
            return str(value)
    return "audio/ogg"


def _first_duration(container: dict) -> float:
    for key in _DURATION_KEYS:
        value = container.get(key)
        if value in (None, ""):
            continue
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return 0.0


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


async def _stt_allowed(bot_id: str, phone: str) -> bool:
    """Проверить денежный рубильник до скачивания и обращения к провайдеру.

    Решение логируем ЦЕЛИКОМ, по каждому входу отдельно. На боевом включении 03.08 голосовое
    не распозналось, и по логам было невозможно понять, какое именно из четырёх условий не
    выполнилось: молчаливый `return False` не оставлял следа. Телефон не пишем — только
    факт попадания в список.
    """
    from app.core import flags
    global_on = await flags.get_flag("stt_enabled", settings.stt_enabled)
    enabled = await flags.get_flag(f"stt_enabled:{bot_id}", global_on) if bot_id else global_on
    public = await flags.get_flag("stt_public_enabled", settings.stt_public_enabled)
    has_key = bool(settings.stt_api_key)
    allowlist = {_digits(item) for item in settings.stt_allowlist_phones if _digits(item)}
    in_allowlist = public or not allowlist or _digits(phone) in allowlist
    ok = bool(enabled and has_key and in_allowlist)
    if not ok:
        logger.info("STT пропущен: bot_id=%r флаг=%s ключ=%s публичный=%s номер_в_списке=%s",
                    bot_id, enabled, has_key, public, in_allowlist)
    return ok


def is_delivery_status(raw: dict) -> bool:
    """True для событий статуса доставки/прочтения (не входящее сообщение клиента)."""
    return raw.get("wh_type") in {"messages_status", "message_status", "delivery_status", "ack"}


# Маппинг статусов Wappi → наши (pending|sent|delivered|failed).
_STATUS_MAP = {
    "sent": "sent", "server": "sent", "send": "sent",
    "delivered": "delivered", "device": "delivered", "read": "delivered", "played": "delivered",
    "failed": "failed", "error": "failed", "canceled": "failed",
}


def parse_delivery_status(raw: dict) -> tuple[str, str]:
    """(provider_msg_id, наш_статус) из события статуса Wappi. Пустой статус — если неизвестно."""
    provider_msg_id = str(raw.get("id") or raw.get("message_id") or raw.get("msg_id") or "")
    wappi_status = str(raw.get("status") or raw.get("ack") or "").lower()
    return provider_msg_id, _STATUS_MAP.get(wappi_status, "")


# Максимальные длины полей рекламного контекста (защита от мусора в БД/промпте).
_REF_LIMITS = {"source_type": 16, "source_id": 128, "source_url": 500,
               "ctwa_clid": 256, "headline": 300, "body": 1000, "media_type": 32}
# Синонимы ключей у разных провайдеров (Cloud API snake_case vs web/whatsmeow camelCase).
_REF_ALIASES = {
    "source_type": ("source_type", "sourceType"),
    "source_id": ("source_id", "sourceId"),
    "source_url": ("source_url", "sourceUrl"),
    "ctwa_clid": ("ctwa_clid", "ctwaClid"),
    "headline": ("headline", "title"),
    "body": ("body", "description"),
    "media_type": ("media_type", "mediaType"),
}


def extract_ad_referral(raw: dict) -> dict:
    """Нормализованный рекламный referral (Click-to-WhatsApp Ads) или {} если его нет.

    Точный формат Wappi для CTWA не зафиксирован в фикстурах — пробуем известные
    варианты вложения (WhatsApp Cloud API `referral`, web/whatsmeow `externalAdReply`).
    Максимально защитно: любой сюрприз/не-dict → {}. Никогда не бросает исключение.
    """
    if not isinstance(raw, dict):
        return {}
    containers = (
        raw.get("referral"),
        raw.get("adReply"),
        raw.get("ad_reply"),
        raw.get("externalAdReply"),
        (raw.get("contextInfo") or {}).get("externalAdReply") if isinstance(raw.get("contextInfo"), dict) else None,
        (raw.get("context") or {}).get("referral") if isinstance(raw.get("context"), dict) else None,
    )
    src = next((c for c in containers if isinstance(c, dict) and c), None)
    if src is None:
        return {}
    out: dict[str, str] = {}
    for canon, aliases in _REF_ALIASES.items():
        for alias in aliases:
            val = src.get(alias)
            if val not in (None, "", [], {}):
                out[canon] = str(val)[:_REF_LIMITS[canon]]
                break
    # Считаем referral валидным, только если есть хоть один опознавательный признак.
    if not any(out.get(k) for k in ("source_id", "ctwa_clid", "source_url", "headline")):
        return {}
    return out


# Подстроки, выдающие рекламный контекст в сыром payload. Если они есть, а
# extract_ad_referral вернул {} — значит реальный формат Wappi не совпал с парсером:
# логируем сырьё под [referral-miss], чтобы поймать настоящие ключи на живом трафике.
_REF_HINT_SUBSTRINGS = (
    "referral", "adreply", "externaladreply", "ctwa", "source_url", "sourceurl",
    "source_id", "sourceid", "ad_id", "\"adid\"", "quotedad", "conversionsource",
)


def _log_referral_miss(raw: dict) -> None:
    """Диагностика: сырьё с признаками рекламы, которое парсер НЕ распознал.

    Срабатывает только когда в payload есть тэлл-тейл рекламного контекста, а
    extract_ad_referral вернул {} — то есть формат Wappi разошёлся с парсером. Так лог
    не флудит на обычных сообщениях и прямо показывает реальные ключи CTWA. Никогда не бросает.
    """
    try:
        blob = json.dumps(raw, ensure_ascii=False)
    except Exception:  # noqa: BLE001 — лог не должен мешать обработке
        return
    low = blob.lower()
    if any(hint in low for hint in _REF_HINT_SUBSTRINGS):
        logger.info("Wappi ad-referral MISS [referral-miss]: %s", blob[:1800])


def is_incoming_user_message(raw: dict) -> bool:
    """True только для входящих сообщений клиента в ЛИЧНОМ чате.

    Отсекаем: наши эхо (`is_me`), статусы доставки/авторизации (`wh_type` != incoming_message),
    реакции (`type` == reaction) и групповые чаты (`chat_type` == group) — в группах бот молчит.
    `chat_type` может отсутствовать в синтетических событиях → по умолчанию считаем личным.
    """
    return (
        raw.get("wh_type") == "incoming_message"
        and not raw.get("is_me", False)
        and raw.get("type") != "reaction"
        and raw.get("chat_type", "dialog") != "group"
    )


# Эхо ответа менеджера с телефона. `outgoing_message_phone` — реальный тип из кабинета Wappi
# (включён на всех трёх профилях 31.07.2026); `incoming_message` + is_me оставляем как форму,
# на которую код был написан изначально, — она ничего не ломает и страхует, если провайдер
# пришлёт эхо в старом виде. Тип `outgoing_message_api` СОЗНАТЕЛЬНО не слушаем: это эхо
# отправок самого бота, мы их пишем при отправке, а защита «своё сообщение» живёт в памяти
# 15 минут — после рестарта бот принял бы собственные реплики за ответы менеджера.
_ECHO_WH_TYPES = ("outgoing_message_phone", "incoming_message")


def is_outgoing_echo(raw: dict) -> bool:
    wh_type = raw.get("wh_type")
    if wh_type not in _ECHO_WH_TYPES:
        return False
    if wh_type == "incoming_message" and raw.get("is_me") is not True:
        return False
    return (
        raw.get("type") != "reaction"
        and raw.get("chat_type", "dialog") != "group"
    )


def outgoing_echo_text(raw: dict) -> str:
    if raw.get("type") != _TEXT_TYPE:
        return ""
    return str(raw.get("body") or "").strip()


def outgoing_echo_phone(raw: dict) -> str:
    """Номер КЛИЕНТА из эха. Ключ у Wappi плавает по типам событий, поэтому перебираем."""
    chat_id = str(raw.get("to") or raw.get("chatId") or raw.get("chat_id")
                  or raw.get("recipient") or "")
    return _recipient(chat_id)


def _recipient(chat_id: str) -> str:
    """`996700...@c.us` → `996700...` (Wappi recipient = номер); группы (@g.us) как есть."""
    return chat_id.split("@")[0] if chat_id.endswith("@c.us") else chat_id


class WappiAdapter:
    channel = "whatsapp"

    def __init__(self, bot: BotConfig | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.bot = bot
        self._base = settings.wappi_base_url.rstrip("/")
        self._token = settings.wappi_token
        # profile_id — на каждого бота свой (его WhatsApp-номер); legacy-одиночный как fallback.
        self._profile_id = (bot.wappi_profile_id if bot and bot.wappi_profile_id else settings.wappi_profile_id)
        self._client = client

    async def parse(self, raw: dict) -> Message:
        """Разобрать событие Wappi incoming_message в нормализованный Message."""
        chat_id = str(raw.get("chatId") or raw.get("from") or "")
        sender = str(raw.get("from") or "")
        user_id = (sender or chat_id).split("@")[0]
        body = str(raw.get("body") or "")

        referral = extract_ad_referral(raw)
        if referral:
            # Capture: логируем сырой payload рекламного касания, чтобы подтвердить реальный
            # формат CTWA от Wappi на живом трафике (как [media-capture] для медиа).
            try:
                logger.info("Wappi ad-referral raw [referral-capture]: %s",
                            json.dumps(raw, ensure_ascii=False)[:1500])
            except Exception:  # noqa: BLE001 — лог не должен мешать обработке
                logger.info("Wappi ad-referral [referral-capture]: keys=%s", sorted(raw.keys()))
        else:
            # Парсер ничего не нашёл — но, возможно, формат Wappi просто не совпал.
            _log_referral_miss(raw)

        if raw.get("type") == _TEXT_TYPE and body:
            kind, text = "text", body
            voice = voice_failed = False
        else:
            kind, text, voice, voice_failed = "non_text", "", False, False
            from app.core.media_capture import note_raw, note_voice_miss
            await note_raw(raw)
            # M1-capture: логируем сырой payload медиа, чтобы узнать реальный формат Wappi
            # (ссылка на файл/голос, mime, длительность) — на этом строим плеер в панели.
            try:
                logger.info("Wappi non-text raw [media-capture]: %s",
                            json.dumps(raw, ensure_ascii=False)[:1200])
            except Exception:  # noqa: BLE001 — лог не должен мешать обработке
                logger.info("Wappi non-text raw [media-capture]: type=%s keys=%s",
                            raw.get("type"), sorted(raw.keys()))

            bot_id = self.bot.id if self.bot else ""
            ref = extract_voice(raw)
            if str(raw.get("type") or "").lower() in _VOICE_TYPES and ref is None:
                await note_voice_miss(raw)
            if await _stt_allowed(bot_id, user_id):
                if ref is not None:
                    from app.integrations.stt.service import transcribe
                    transcript = await transcribe(
                        audio_url=ref.url, mime=ref.mime, duration_sec=ref.duration_sec,
                        msg_id=str(raw.get("id") or raw.get("message_id") or raw.get("msg_id") or ""),
                        bot_id=bot_id,
                        wappi_account=str(raw.get("profile_id") or "unknown"),
                    )
                    if transcript:
                        kind, text, voice = "text", transcript, True
                    else:
                        # Пытались и не вышло. Пустую или сомнительную расшифровку боту НЕ
                        # отдаём — он ответит не по делу и уронит доверие сильнее молчания.
                        # Но менеджер обязан увидеть в панели, что запись стоит прослушать.
                        voice_failed = True

        return Message(
            channel=self.channel,
            user_id=user_id,
            chat_id=chat_id,
            text=text,
            kind=kind,
            raw=raw,
            referral=referral,
            voice_failed=voice_failed,
            voice=voice,
        )

    async def send(self, chat_id: str, text: str, **kwargs) -> str:
        """Отправить ответ клиенту через Wappi sync-API. Возвращает provider_msg_id (или "")."""
        if not self._token or not self._profile_id:
            logger.warning("Wappi send пропущен: не заданы token/profile_id")
            return ""

        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=20)
        try:
            resp = await client.post(
                f"{self._base}/api/sync/message/send",
                params={"profile_id": self._profile_id},
                headers={"Authorization": self._token, "Content-Type": "application/json"},
                json={"recipient": _recipient(chat_id), "body": text},
            )
            resp.raise_for_status()
            provider_msg_id = _extract_msg_id(resp)
        finally:
            if owns:
                await client.aclose()
        logger.info("Wappi send to=%s profile=%s msg_id=%s",
                    _recipient(chat_id), self._profile_id, provider_msg_id)
        return provider_msg_id


    async def fetch_chat_messages(self, phone: str) -> list[dict]:
        """Переписка с номером как её видит WhatsApp (вместе с нашими исходящими).

        Нужна потому, что профиль Wappi подписан только на `incoming_message` — эхо
        исходящих нам не приходит, и ответы менеджера с телефона до панели не долетают
        (за неделю 31.07.2026 в базе НОЛЬ сообщений с sender='manager' при 980 клиентских).
        Пока тип вебхука не включён в кабинете, забираем их сами.
        """
        if not self._token or not self._profile_id or not phone:
            return []
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=25)
        try:
            resp = await client.get(
                f"{self._base}/api/sync/messages/get",
                params={"profile_id": self._profile_id, "chat_id": f"{_recipient(phone)}@c.us"},
                headers={"Authorization": self._token},
            )
            resp.raise_for_status()
            data = resp.json()
        finally:
            if owns:
                await client.aclose()
        return data.get("messages") or [] if isinstance(data, dict) else []


def is_manager_reply(raw: dict) -> bool:
    """Исходящее текстовое сообщение живого человека (не реакция, не медиа-заглушка)."""
    outgoing = bool(raw.get("fromMe") or raw.get("from_me") or raw.get("is_me"))
    return outgoing and raw.get("type") == _TEXT_TYPE and bool(str(raw.get("body") or "").strip())


def message_time(raw: dict) -> int:
    try:
        return int(raw.get("time") or raw.get("timestamp") or 0)
    except (TypeError, ValueError):
        return 0


def _extract_msg_id(resp: httpx.Response) -> str:
    """Вытащить id отправленного сообщения из ответа Wappi (ключ варьируется)."""
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001 — тело не JSON
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("message_id", "msg_id", "id"):
        if data.get(key):
            return str(data[key])
    msg = data.get("message")
    if isinstance(msg, dict):
        for key in ("id", "message_id"):
            if msg.get(key):
                return str(msg[key])
    return ""
