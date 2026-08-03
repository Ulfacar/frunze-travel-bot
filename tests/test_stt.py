"""STT голосовых Wappi: флаги, допуски, кэш и fail-safe без реальной сети."""
from __future__ import annotations

import asyncio
import json
import socket

import pytest
import httpx

from app.channels.wappi import WappiAdapter, extract_voice
from app.config import BotConfig, settings
from app.core import flags
from app.integrations.stt.base import SttPermanentError, SttTemporaryError, Transcript


BOT = BotConfig(id="frunze_tours", scenario="tours", wappi_profile_id="profile")


def _voice(**extra):
    raw = {
        "wh_type": "incoming_message", "id": "voice-1", "type": "ptt",
        "from": "996700123456@c.us", "chatId": "996700123456@c.us",
        "url": "https://files.invalid/voice.ogg", "duration": 12, "profile_id": "profile",
    }
    raw.update(extra)
    return raw


@pytest.fixture(autouse=True)
def _stt_defaults(monkeypatch):
    flags.reset()
    monkeypatch.setattr(settings, "stt_enabled", False)
    monkeypatch.setattr(settings, "stt_api_key", "test-key")
    monkeypatch.setattr(settings, "stt_allowlist_phones", [])
    monkeypatch.setattr(settings, "state_backend", "memory")
    monkeypatch.setattr(settings, "stt_timeout_seconds", 0.05)


def test_flag_off_keeps_non_text(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return "текст"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    assert (msg.kind, msg.text, msg.voice) == ("non_text", "", False)
    assert calls == []


def test_enabled_voice_becomes_text(monkeypatch):
    monkeypatch.setattr(settings, "stt_enabled", True)

    async def fake(**kwargs):
        return "Хочу тур"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    assert (msg.kind, msg.text, msg.voice) == ("text", "Хочу тур", True)


def test_per_bot_flag_overrides_global(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs["bot_id"])
        return "распознано"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    asyncio.run(flags.set_flag("stt_enabled:frunze_tours", True))
    enabled = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    other = asyncio.run(WappiAdapter(BotConfig(id="getvisa", scenario="visa")).parse(_voice()))
    assert enabled.kind == "text"
    assert other.kind == "non_text"
    assert calls == ["frunze_tours"]


def test_allowlist_blocks_unknown_phone(monkeypatch):
    monkeypatch.setattr(settings, "stt_enabled", True)
    monkeypatch.setattr(settings, "stt_allowlist_phones", ["+996 555 000 111"])
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return "текст"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    assert msg.kind == "non_text"
    assert calls == []


def test_missing_api_key_keeps_non_text(monkeypatch):
    monkeypatch.setattr(settings, "stt_enabled", True)
    monkeypatch.setattr(settings, "stt_api_key", "")
    calls = []

    async def fake(**kwargs): calls.append(kwargs)

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    assert msg.kind == "non_text" and calls == []


@pytest.mark.parametrize("result", [SttTemporaryError("временный сбой"), Transcript(" ", "x", "m")])
def test_provider_error_or_empty_returns_empty(monkeypatch, result):
    from app.integrations.stt import service

    async def download(url, **kwargs):
        return b"audio", "audio/ogg"

    class Provider:
        async def transcribe(self, *args, **kwargs):
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr(service, "fetch_media", download)
    monkeypatch.setattr(service, "get_provider", lambda: Provider())
    text = asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=1,
        msg_id="", bot_id="frunze_tours", wappi_account="profile"))
    assert text == ""


def test_too_long_skips_download_and_provider(monkeypatch):
    from app.integrations.stt import service
    monkeypatch.setattr(settings, "stt_max_duration_seconds", 10)
    calls = []

    async def download(url, **kwargs):
        calls.append("download")
        return b"", "audio/ogg"

    monkeypatch.setattr(service, "fetch_media", download)
    monkeypatch.setattr(service, "get_provider", lambda: calls.append("provider"))
    text = asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=11,
        msg_id="", bot_id="frunze_tours", wappi_account="profile"))
    assert text == ""
    assert calls == []


def test_cache_prevents_download_and_provider(monkeypatch):
    from app.integrations.stt import service
    monkeypatch.setattr(settings, "state_backend", "redis")
    calls = []

    async def cache_get(key):
        return True, "из кэша"

    monkeypatch.setattr(service, "_cache_get", cache_get)
    monkeypatch.setattr(service, "fetch_media", lambda url, **kwargs: calls.append("download"))
    monkeypatch.setattr(service, "get_provider", lambda: calls.append("provider"))
    text = asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=1,
        msg_id="same-id", bot_id="frunze_tours", wappi_account="profile"))
    assert text == "из кэша"
    assert calls == []


def test_extract_voice_tolerates_probable_payloads():
    top = extract_voice({"type": "voice", "url": "https://x/a", "duration": "2"})
    listed = extract_voice({"type": "audio", "attaches": [{"fileUrl": "https://x/b", "mime": "audio/mp4"}]})
    mapped = extract_voice({"type": "audio_message", "attaches": {"download_url": "https://x/c"}})
    assert top and top.url == "https://x/a" and top.duration_sec == 2
    assert listed and listed.url == "https://x/b" and listed.mime == "audio/mp4"
    assert mapped and mapped.url == "https://x/c"
    assert extract_voice({"type": "chat", "body": "привет"}) is None


def test_registry_rejects_unknown_and_ignores_fallback(monkeypatch):
    from app.integrations.stt import registry
    with pytest.raises(SttPermanentError, match="неизвестный"):
        registry.get_provider("missing")
    monkeypatch.setattr(settings, "stt_fallback_provider", "yandex")
    monkeypatch.setattr(settings, "stt_provider", "openai")
    registry._fallback_warned = False
    provider = registry.get_provider()
    assert provider.name == "openai"
    assert set(registry._PROVIDERS) == {"openai"}


def test_text_regression_when_stt_enabled(monkeypatch):
    monkeypatch.setattr(settings, "stt_enabled", True)
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return "не должен вызываться"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    raw = _voice(type="chat", body="обычный текст")
    msg = asyncio.run(WappiAdapter(BOT).parse(raw))
    assert (msg.kind, msg.text, msg.voice) == ("text", "обычный текст", False)
    assert calls == []


def test_cache_key_separates_bots_and_profiles(monkeypatch):
    from app.integrations.stt import service
    keys = []

    async def cache_get(key):
        keys.append(key)
        return True, "кэш"

    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(service, "_cache_get", cache_get)
    for bot_id, profile in (("frunze_tours", "a"), ("getvisa", "a"), ("frunze_tours", "b")):
        assert asyncio.run(service.transcribe(
            audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=1,
            msg_id="same", bot_id=bot_id, wappi_account=profile)) == "кэш"
    assert keys == ["stt:a:frunze_tours:same", "stt:a:getvisa:same", "stt:b:frunze_tours:same"]


def test_parallel_call_waits_for_first_result(monkeypatch):
    from app.integrations.stt import service
    cache = {}
    lock = False
    provider_calls = 0

    async def cache_get(key):
        value = cache.get(key)
        return (value is not None, value or "")

    async def cache_set(key, payload):
        cache[key] = payload["transcript"]

    async def acquire(key, token):
        nonlocal lock
        if lock:
            return False
        lock = True
        return True

    async def release(key, token):
        nonlocal lock
        lock = False

    async def fetch(*args, **kwargs):
        await asyncio.sleep(0.01)
        return b"audio", "audio/ogg"

    class Provider:
        name = "mock"
        async def transcribe(self, *args, **kwargs):
            nonlocal provider_calls
            provider_calls += 1
            await asyncio.sleep(0.01)
            return Transcript("чистый текст", "mock", "offline")

    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(settings, "stt_timeout_seconds", 1)
    monkeypatch.setattr(service, "_cache_get", cache_get)
    monkeypatch.setattr(service, "_cache_set", cache_set)
    monkeypatch.setattr(service, "_lock_acquire", acquire)
    monkeypatch.setattr(service, "_lock_release", release)
    monkeypatch.setattr(service, "fetch_media", fetch)
    monkeypatch.setattr(service, "get_provider", lambda: Provider())

    async def run():
        kwargs = dict(audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=1,
                      msg_id="parallel", bot_id="frunze_tours", wappi_account="profile")
        return await asyncio.gather(service.transcribe(**kwargs), service.transcribe(**kwargs))

    assert asyncio.run(run()) == ["чистый текст", "чистый текст"]
    assert provider_calls == 1


def test_busy_lock_times_out_without_deadlock(monkeypatch):
    from app.integrations.stt import service
    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(settings, "stt_timeout_seconds", 0.01)

    async def miss(key):
        return False, ""

    async def busy(key, token):
        return False

    monkeypatch.setattr(service, "_cache_get", miss)
    monkeypatch.setattr(service, "_lock_acquire", busy)
    assert asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a", mime="audio/ogg", duration_sec=1,
        msg_id="busy", bot_id="frunze_tours", wappi_account="profile")) == ""


@pytest.mark.parametrize("response_type,payload_mime", [
    ("image/jpeg", "audio/ogg"), ("application/pdf", "application/pdf"),
])
def test_non_audio_content_never_reaches_provider(monkeypatch, response_type, payload_mime):
    from app.integrations.stt import service
    called = []

    async def fetch(*args, **kwargs):
        return b"not-audio", response_type

    monkeypatch.setattr(service, "fetch_media", fetch)
    monkeypatch.setattr(service, "get_provider", lambda: called.append(True))
    assert asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a", mime=payload_mime, duration_sec=1,
        msg_id="", bot_id="frunze_tours")) == ""
    assert called == []


def test_media_capture_sanitizes_and_voice_miss(monkeypatch):
    from app.core import media_capture

    class Redis:
        def __init__(self): self.rows = {}
        async def lpush(self, key, value): self.rows.setdefault(key, []).insert(0, value)
        async def ltrim(self, key, start, end): self.rows[key] = self.rows[key][start:end + 1]
        async def expire(self, key, ttl): self.ttl = ttl
        async def lrange(self, key, start, end): return self.rows.get(key, [])[start:end + 1]

    redis = Redis()
    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(media_capture, "_redis", redis)
    raw = {"token": "secret", "from": "996700123456@c.us", "nested": {
        "api_key": "gone", "body": "x" * 301}, "type": "voice"}
    asyncio.run(media_capture.note_voice_miss(raw))
    row = asyncio.run(media_capture.recent("voice", 1))[0]
    assert "token" not in row["payload"] and "api_key" not in row["payload"]["nested"]
    assert row["payload"]["from"] == "9967***us"
    assert row["payload"]["nested"]["body"].endswith("…[обрезано]")
    assert row["top_level_keys"] == sorted(raw)
    assert redis.ttl == settings.media_capture_ttl_seconds


def test_voice_without_url_is_captured_and_not_transcribed(monkeypatch):
    monkeypatch.setattr(settings, "stt_enabled", True)
    calls = []

    async def capture(raw): calls.append("capture")
    async def stt(**kwargs): calls.append("stt")

    monkeypatch.setattr("app.core.media_capture.note_raw", capture)
    monkeypatch.setattr("app.core.media_capture.note_voice_miss", capture)
    monkeypatch.setattr("app.integrations.stt.service.transcribe", stt)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice(url="")))
    assert msg.kind == "non_text"
    assert calls == ["capture", "capture"]


@pytest.mark.parametrize("url", [
    "http://public.example/a", "https://localhost/a", "https://127.0.0.1/a",
    "https://10.0.0.1/a", "https://169.254.169.254/a",
])
def test_unsafe_media_url_is_blocked(monkeypatch, url):
    from app.integrations.stt import fetch

    def dns(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (host, port))]

    monkeypatch.setattr(fetch.socket, "getaddrinfo", dns)
    with pytest.raises(SttPermanentError):
        asyncio.run(fetch._validate_url(url))


def test_redirect_is_not_followed(monkeypatch):
    from app.integrations.stt import fetch
    requests = []
    original_client = httpx.AsyncClient

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://other.example/secret"})

    def client_factory(*args, **kwargs):
        assert kwargs["follow_redirects"] is False
        return original_client(transport=httpx.MockTransport(handler), timeout=kwargs["timeout"],
                               follow_redirects=kwargs["follow_redirects"])

    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(fetch.httpx, "AsyncClient", client_factory)
    with pytest.raises(SttPermanentError, match="редирект"):
        asyncio.run(fetch.fetch_media("https://public.example/a", max_bytes=10, timeout=1))
    assert requests == ["https://public.example/a"]


def test_oversized_media_never_reaches_provider(monkeypatch):
    from app.integrations.stt import fetch, service
    original_client = httpx.AsyncClient
    called = []

    def client_factory(*args, **kwargs):
        return original_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(
                200, headers={"content-type": "audio/ogg"}, content=b"123456")),
            timeout=kwargs["timeout"], follow_redirects=False)

    monkeypatch.setattr(settings, "stt_max_bytes", 5)
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(fetch.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(service, "get_provider", lambda: called.append(True))
    assert asyncio.run(service.transcribe(
        audio_url="https://public.example/a", mime="audio/ogg", duration_sec=1,
        msg_id="", bot_id="frunze_tours")) == ""
    assert called == []


def test_voice_marker_only_goes_to_panel(monkeypatch):
    from app.channels.base import Message
    from app.core import orchestrator as module
    from app.core.orchestrator import Orchestrator

    seen = {"panel": [], "turn": []}
    orch = Orchestrator(channel=object())

    async def expire(key): return None
    async def log_in(msg, text): seen["panel"].append(text)
    async def run_turn(msg): seen["turn"].append(msg.text)

    monkeypatch.setattr(module, "expire_auto_intercept", expire)
    monkeypatch.setattr(orch, "_log_in", log_in)
    monkeypatch.setattr(orch, "_run_turn", run_turn)
    msg = Message(channel="whatsapp", user_id="u", chat_id="u", text="Хочу тур", voice=True)
    asyncio.run(orch.handle(msg))
    assert seen == {"panel": ["🎤 Хочу тур"], "turn": ["Хочу тур"]}


def test_three_bot_flags_do_not_mix_dialogs(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append((kwargs["bot_id"], kwargs["wappi_account"]))
        return "текст"

    monkeypatch.setattr("app.integrations.stt.service.transcribe", fake)
    asyncio.run(flags.set_flag("stt_enabled:frunze_tours", True))
    bots = [
        BOT,
        BotConfig(id="getvisa", scenario="visa", wappi_profile_id="visa-profile"),
        BotConfig(id="frunze_tours_sezim", scenario="tours", wappi_profile_id="sezim-profile"),
    ]
    messages = [asyncio.run(WappiAdapter(bot).parse(_voice(profile_id=bot.wappi_profile_id)))
                for bot in bots]
    assert [msg.kind for msg in messages] == ["text", "non_text", "non_text"]
    assert calls == [("frunze_tours", "profile")]


def test_stt_path_does_not_touch_tourvisor_bitrix_or_telegram(monkeypatch):
    from app.channels.telegram import TelegramAdapter
    from app.integrations.crm.bitrix24 import Bitrix24Crm
    from app.integrations.tourvisor.client import TourVisorClient

    forbidden = []

    async def bomb(*args, **kwargs):
        forbidden.append(True)
        raise AssertionError("STT не должен входить в соседнюю интеграцию")

    async def stt(**kwargs): return "распознанный текст"

    monkeypatch.setattr(settings, "stt_enabled", True)
    monkeypatch.setattr(TourVisorClient, "search", bomb)
    monkeypatch.setattr(Bitrix24Crm, "send_message", bomb)
    monkeypatch.setattr(TelegramAdapter, "send", bomb)
    monkeypatch.setattr("app.integrations.stt.service.transcribe", stt)
    msg = asyncio.run(WappiAdapter(BOT).parse(_voice()))
    assert (msg.kind, msg.text) == ("text", "распознанный текст")
    assert forbidden == []


def test_failure_is_remembered_briefly_so_redelivery_can_retry(monkeypatch):
    """Сбой нельзя помнить неделю: Wappi повторяет доставку вебхука по таймауту, и длинная
    отметка «не получилось» навсегда закрыла бы вторую попытку по тому же сообщению."""
    from app.integrations.stt import service
    saved: list[tuple[str, dict, int | None]] = []

    async def miss(key):
        return False, ""

    async def cache_set(key, payload, *, ttl=None):
        saved.append((key, payload, ttl))

    async def boom(*args, **kwargs):
        raise SttTemporaryError("медиа-сервер недоступен")

    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(settings, "stt_failure_cache_seconds", 60)
    monkeypatch.setattr(service, "_cache_get", miss)
    monkeypatch.setattr(service, "_cache_set", cache_set)
    monkeypatch.setattr(service, "_lock_acquire", lambda key, token: _true())
    monkeypatch.setattr(service, "_lock_release", lambda key, token: _noop())
    monkeypatch.setattr(service, "fetch_media", boom)

    assert asyncio.run(service.transcribe(
        audio_url="https://files.invalid/a?token=SECRET", mime="audio/ogg", duration_sec=3,
        msg_id="fail-once", bot_id="frunze_tours", wappi_account="profile")) == ""
    assert len(saved) == 1
    _, payload, ttl = saved[0]
    assert ttl == 60                                  # короткое окно, а не stt_cache_ttl_seconds
    assert payload["ok"] is False
    # Подписанный токен доступа не имеет права осесть в Redis.
    assert "SECRET" not in payload["media_ref"] and "token" not in payload["media_ref"]


async def _true():
    return True


async def _noop():
    return None


def test_voice_fields_come_from_one_container():
    """mime и длительность берём оттуда же, где нашлась ссылка: mime соседнего вложения
    (например аватарки) отправил бы нас в отказ по content-type уже после скачивания."""
    ref = extract_voice({
        "type": "ptt",
        "mimetype": "image/jpeg",          # мусор верхнего уровня — рядом с аватаркой
        "duration": 999,
        "attaches": [{"fileUrl": "https://x/voice.ogg", "mime": "audio/ogg", "seconds": 7}],
    })
    assert ref is not None
    assert ref.url == "https://x/voice.ogg"
    assert ref.mime == "audio/ogg" and ref.duration_sec == 7


def test_extract_voice_on_real_wappi_payload():
    """Боевой payload голосового с прода 03.08 (обезличен).

    Именно он показал, что первоначальные догадки были мимо: ссылка приходит в `file_link`,
    длительность — в `length_seconds`. Ни одного из этих имён в списках кандидатов не было,
    поэтому распознавание молча не запускалось бы, а причину искали бы в OpenAI.
    """
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).parent / "fixtures" / "wappi" / "voice_ptt.json").read_text("utf-8"))
    ref = extract_voice(raw)
    assert ref is not None
    assert ref.url.startswith("https://wapi-uploads7d.storage.yandexcloud.net/")
    assert ref.mime.startswith("audio/ogg")
    assert ref.duration_sec == 4


def test_capture_masks_phone_inside_any_string():
    """Телефон клиента приехал внутри ссылки на аватарку — поля с таким именем нет ни в
    одном списке, поэтому маскируем по форме: длинная цепочка цифр в любой строке."""
    from app.core.media_capture import _sanitize

    cleaned = _sanitize({
        "thumbnail": "https://fs.wappi.pro/fs/downloadFile/x/avatars/tumb_996500494009.jpg",
        "nested": {"link": "https://x/996700111222/file.ogg"},
        "small_number": "12345",
    })
    assert "996500494009" not in cleaned["thumbnail"]
    assert "996700111222" not in cleaned["nested"]["link"]
    assert cleaned["small_number"] == "12345"      # короткие числа не трогаем
