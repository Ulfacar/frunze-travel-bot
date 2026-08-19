"""Shared lead classification for board columns, cleanup and follow-up.

The admin board and background follow-up must agree on what is noise and what is
"silent". Keep these helpers pure so they are easy to test and reuse.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


STAGE_TO_COLUMN = {
    "greeting": "greeting", "new": "greeting",
    "qualification": "qualification",
    "progress": "progress", "scoring": "progress", "search": "progress", "visa_scoring": "progress",
    "office": "office", "office_consultation": "office",
    "manager": "manager", "manager_handoff": "manager",
    "follow_up": "follow_up", "followup": "follow_up", "callback": "follow_up",
}

HUMAN_STAGES = {"office", "office_consultation", "manager", "manager_handoff"}
NOISE_STAGES = {"greeting", "new"}
# Из дожима исключаем только «на живом менеджере». Прошедших консультацию/офис (office*) и уже
# пингованных (follow_up) — дожимаем по расписанию (правка со встречи 06.07), ритм ограничен
# числом пингов и интервалом (см. is_silent + followup_max_pings/followup_interval_hours).
SILENT_EXCLUDED_COLUMNS = {"manager"}
TERMINAL_OUTCOMES = {"won", "lost"}

NOISE_LINK_RE = re.compile(
    r"(https?://|instagram\.com|fb\.me|facebook\.com|wa\.me|api\.whatsapp|t\.me|telegram\.me)",
    re.IGNORECASE,
)
NOISE_MEDIA_TERMS = ("[media", "[медиа", "[голос", "голос", "voice", "audio")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# Порядок стадий для канбана. Бот двигает карточку только ВПЕРЁД: ручной перенос менеджера
# главнее бота (решение владельца 16.07), а `_sync_card` пишет стадию на каждом ходу — без
# этого порядка любой пересчёт сбрасывал бы карточку, которую менеджер перетащил руками.
STAGE_RANK = {"": 0, "greeting": 0, "new": 0, "qualification": 1,
              "progress": 2, "scoring": 2, "search": 2, "visa_scoring": 2,
              "follow_up": 2, "followup": 2, "callback": 2,
              "office": 3, "office_consultation": 3, "manager": 4, "manager_handoff": 4}

# Сколько собранных полей анкеты означает, что разговор перешёл от знакомства к подбору.
# На живых карточках заполненная анкета — это 7–8 полей (страна, даты, бюджет, состав…),
# так что «три и больше» уверенно отделяет работу от первых двух вежливых ответов.
PROGRESS_MIN_FIELDS = 3


def derive_stage(state) -> str:
    """Стадия, которую видно по самому разговору: знакомство → анкета → подбор.

    До 19.08.2026 стадия жила только как флаг эскалации (`manager`/`office`), и 92%
    диалогов навсегда оставались в «Приветствии» — включая те, где клиент написал 69
    сообщений. Считаем по собранной анкете: она наполняется по ходу разговора и не
    требует ни новых полей в БД, ни обращения к модели.
    """
    filled = sum(1 for v in (getattr(state, "qualification", None) or {}).values()
                 if v not in (None, "", [], {}))
    if filled == 0:
        return "greeting"
    return "progress" if filled >= PROGRESS_MIN_FIELDS else "qualification"


def advance_stage(current: str, derived: str) -> str:
    """Более поздняя из двух стадий. Бот не откатывает карточку назад — никогда."""
    return derived if STAGE_RANK.get(derived, 0) > STAGE_RANK.get(current, 0) else (current or derived)


def _has_message(conv) -> bool:
    return bool(getattr(conv, "messages", None) or getattr(conv, "last_text", "") or getattr(conv, "last_sender", ""))


def _has_bot_or_manager_message(conv) -> bool:
    return any(getattr(m, "sender", "") in {"bot", "manager"} for m in (getattr(conv, "messages", None) or []))


def _only_client_messages(conv) -> bool:
    messages = getattr(conv, "messages", None) or []
    if messages:
        return any(getattr(m, "sender", "") == "client" for m in messages) and not _has_bot_or_manager_message(conv)
    return getattr(conv, "last_sender", "") == "client"


def is_noise(conv, now: datetime | None = None, cfg=None) -> bool:
    """Advertising/media-only or dead empty greeting lead that can be archived."""
    stage = getattr(conv, "stage", "")
    if (
        stage not in NOISE_STAGES
        or getattr(conv, "intercepted", False)
        or getattr(conv, "assigned_to", "")
        or getattr(conv, "qualification", None)
    ):
        return False

    text = (getattr(conv, "last_text", "") or "").strip().lower()
    link_or_media = bool(NOISE_LINK_RE.search(text)) or any(term in text for term in NOISE_MEDIA_TERMS)
    if getattr(conv, "last_sender", "") == "client" and link_or_media:
        return True

    # Дальше идёт ветка «залежался и говорил только клиент» — ровно в неё проваливается
    # диалог, где менеджер отвечает мимо нас. Повтор рекламной ссылки уже отсеян выше по
    # тексту, так что здесь мы теряем только настоящий мусор, а не живой разговор.
    if looks_unseen_conversation(conv):
        return False

    now = _aware(now) or datetime.now(timezone.utc)
    last = _aware(getattr(conv, "last_message_at", None))
    stale_days = getattr(cfg, "noise_stale_days", 3)
    is_stale = bool(last and last <= now - timedelta(days=stale_days))
    return is_stale and _has_message(conv) and _only_client_messages(conv)


# Сколько раз клиент должен написать без единого нашего ответа, чтобы счесть, что разговор
# ведут без нас. Один-два неотвеченных сообщения — это настоящий брошенный лид (ради него
# дожим и существует), а вот третье подряд означает, что человеку кто-то отвечает мимо нас.
UNSEEN_MIN_CLIENT_MSGS = 3


def looks_unseen_conversation(conv) -> bool:
    """Диалог, который ведут без нас: клиент пишет раз за разом, наших реплик нет ни одной.

    Так выглядит канал, где менеджер отвечает с телефона, а эхо ответа до нас не долетает.
    Замер прода 19.08.2026: на визовом канале 385 из 681 диалога за 30 дней не имели ни
    одного нашего сообщения, при том что клиент в них отвечает на заданные вопросы — то
    есть человек с ним работал. Дожимать такого клиента нельзя: бот написал бы «вы ещё
    думаете?» тому, кому менеджер вчера отправил счёт.

    Осторожность в обе стороны: без загруженной истории (`all_conversations_light`)
    функция молчит, поэтому сводки и доски ведут себя ровно как раньше.
    """
    messages = getattr(conv, "messages", None) or []
    if not messages:
        return False
    if _has_bot_or_manager_message(conv):
        return False
    client_msgs = sum(1 for m in messages if getattr(m, "sender", "") == "client")
    return client_msgs >= UNSEEN_MIN_CLIENT_MSGS


def followup_pings(conv) -> int:
    """Сколько пингов дожима уже отправлено (совместимо со старым булевым followup_sent)."""
    count = int(getattr(conv, "followup_count", 0) or 0)
    if count == 0 and getattr(conv, "followup_sent", False):
        return 1  # legacy-лид, помеченный старым флагом до перехода на счётчик
    return count


def is_silent(conv, now: datetime, cfg) -> bool:
    """Broad stuck-lead definition used by both board and auto-follow-up.

    Ритм дожима: до `followup_max_pings` пингов на клиента; первый — после
    `followup_after_hours` тишины, повторные — не чаще `followup_interval_hours` (~2×/неделю).
    """
    now = _aware(now) or datetime.now(timezone.utc)
    if getattr(conv, "intercepted", False):
        return False
    if looks_unseen_conversation(conv):
        return False  # с клиентом уже говорят, просто мимо нас — молчим, пока не увидим ответы
    pings = followup_pings(conv)
    if pings >= getattr(cfg, "followup_max_pings", 2):
        return False  # лимит пингов исчерпан — больше не дожимаем
    if getattr(conv, "outcome", "") in TERMINAL_OUTCOMES:
        return False
    if STAGE_TO_COLUMN.get(getattr(conv, "stage", ""), "greeting") in SILENT_EXCLUDED_COLUMNS:
        return False
    if is_noise(conv, now, cfg):
        return False
    if not _has_message(conv):
        return False
    last = _aware(getattr(conv, "last_message_at", None))
    if last is None:
        return False
    # Первый пинг — после followup_after_hours тишины; повторные — не чаще followup_interval_hours.
    hours = (getattr(cfg, "followup_after_hours", 24) if pings == 0
             else getattr(cfg, "followup_interval_hours", 84))
    return last <= now - timedelta(hours=hours)
