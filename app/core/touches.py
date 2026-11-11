"""Касания до договора: напоминания МЕНЕДЖЕРУ, а не сообщения от бота.

Требование Медины (письменные ответы 11.11.2026, вопросы 2 и 3): «хотелось бы, чтобы
система автоматически напоминала менеджеру о необходимости связаться с клиентом» —
через 1 день, 3 дня и 5–7 дней молчания. Тексты всех трёх касаний она написала сама и
отправляет их своими руками.

Почему это НЕ автодожим (`app/core/followup.py`). Дожим пишет клиенту от имени бота и
на проде выключен (`followup_enabled = f`). Здесь бот не пишет никому: он создаёт
задачу владельцу лида в его календаре, а текст кладёт в комментарий, чтобы менеджер
скопировал и отправил сам. Если когда-нибудь включат и дожим, и касания — клиент
получит два сообщения, поэтому в `run()` стоит проверка и предупреждение в лог.

**Формула «клиент молчит» здесь СВОЯ, и это главное место, где можно ошибиться.**
`leadstate.is_silent`, на котором стоит дожим, исключает перехваченные менеджером
диалоги (`intercepted`) — бот не лезет туда, где говорит человек. Но касания Медины
нужны ровно по ЕЁ клиентам, которых она перехватила и ведёт сама. Поэтому берём
`intercepted` в работу и смотрим на другое: последним писали МЫ, клиент не ответил.

Ограничители — память инцидента 07.09.2026, когда сухой прогон дожима показал, что
первое включение отправило бы 818 сообщений залпом по базе, накопленной за месяцы:

* `touch_max_age_days` — молчит дольше, значит это не касание, а рассылка;
* `touch_batch_limit` — сколько задач создаём за один прогон;
* `touch_daily_limit` — сколько НОВЫХ касаний получит один менеджер за день. Этот
  ограничитель появился после замера на боевых данных 11.11.2026: под первое касание
  подходило **201 визовый лид**, а на выезде Медина работает одна. Порция за прогон
  такой завал не лечит — она лишь растягивает его на десять прогонов, и человек всё
  равно приходит утром к двум сотням задач;
* не больше одной задачи на клиента в день и не больше `len(touch_after_days)` касаний
  всего.

Флаг `visa_touch_tasks_enabled`, дефолт OFF. Направления — только те, что в
`touch_funnels` (по умолчанию визы: это её направление).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings

log = logging.getLogger(__name__)

FLAG = "visa_touch_tasks_enabled"
TERMINAL_OUTCOMES = {"won", "lost"}

# Тексты Медины, 11.11.2026, вопрос 3 — дословно. Менеджер копирует и отправляет сам,
# поэтому правка текста здесь НЕ меняет того, что получит клиент: она меняет подсказку.
TOUCH_TEXTS = (
    "Здравствуйте! Хотели уточнить, актуален ли для вас ещё вопрос оформления визы? "
    "Будем рады помочь 😊",
    "Добрый день! Ранее вы интересовались оформлением визы. Подскажите, планируете ли "
    "вы поездку? Мы можем помочь с подготовкой документов и записью на подачу.",
    "Здравствуйте! Хотели ещё раз уточнить, актуально ли для вас оформление визы. "
    "Если решите начать оформление, будем рады вам помочь!",
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def touch_number(conv, done: int) -> int:
    """Какое касание пора делать: 1, 2 или 3. `done` — сколько уже сделано."""
    return done + 1


def due_after_days(number: int, cfg) -> int | None:
    """Через сколько дней молчания пора делать касание `number`. None — касаний больше нет."""
    schedule = list(getattr(cfg, "touch_after_days", None) or (1, 3, 6))
    if number < 1 or number > len(schedule):
        return None
    return int(schedule[number - 1])


def select_touch_targets(convs: list, now: datetime, cfg, *,
                         done_by_user: dict[str, int] | None = None,
                         today_by_owner: dict[str, int] | None = None,
                         allowed_funnels: set[str] | None = None) -> list[dict]:
    """Кому пора напомнить. Чистая функция: ни базы, ни сети.

    `done_by_user` — сколько касаний уже сделано по каждому диалогу (ключ `user_id`).
    Считает вызывающий код по задачам в базе: счётчик дожима (`followup_count`) здесь
    не годится, он про сообщения бота, а не про напоминания менеджеру.

    `today_by_owner` — сколько касаний менеджер уже получил СЕГОДНЯ. Без этого первое
    включение выдало бы Медине 201 задачу (замер 11.11.2026), и список дел перестал бы
    быть списком дел.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    done_by_user = done_by_user or {}
    budget = dict(today_by_owner or {})
    daily_limit = max(0, int(getattr(cfg, "touch_daily_limit", 10) or 0))
    funnels = (allowed_funnels if allowed_funnels is not None
               else set(getattr(cfg, "touch_funnels", None) or ("visa",)))
    max_age_days = int(getattr(cfg, "touch_max_age_days", 30) or 0)
    oldest = now - timedelta(days=max_age_days) if max_age_days else None

    out: list[dict] = []
    for c in convs:
        if str(getattr(c, "funnel", "") or "") not in funnels:
            continue
        if getattr(c, "archived", False):
            continue
        if str(getattr(c, "outcome", "") or "") in TERMINAL_OUTCOMES:
            continue
        # Касание нужно, когда ждём КЛИЕНТА: последним писали мы. Если последним писал
        # клиент — он ждёт нас, и это работа сторожа «клиент ждёт», а не касания.
        if str(getattr(c, "last_sender", "") or "") not in ("manager", "bot"):
            continue
        owner = str(getattr(c, "assigned_to", "") or "").strip().lower()
        if not owner:
            continue            # некому ставить задачу: нераспределённые разбирает админ
        last = _aware(getattr(c, "last_message_at", None))
        if last is None:
            continue
        if oldest is not None and last < oldest:
            continue            # молчит слишком давно — это уже не касание
        number = touch_number(c, done_by_user.get(getattr(c, "user_id", ""), 0))
        days = due_after_days(number, cfg)
        if days is None:
            continue            # все касания сделаны
        if last > now - timedelta(days=days):
            continue            # срок ещё не подошёл
        out.append({"conv": c, "number": number, "owner": owner,
                    "silent_days": (now - last).days,
                    "text": TOUCH_TEXTS[min(number, len(TOUCH_TEXTS)) - 1]})

    # Сначала те, кому пора первое касание (их легче вернуть), внутри группы — САМЫЕ
    # СВЕЖИЕ. Тот же принцип, что в `followup.select_followup_targets`, и сухой прогон
    # 11.11.2026 показал, почему: при обратном порядке первые 20 задач достались
    # клиентам, молчащим по 29 дней — то есть почти мёртвым. Её график (1, 3, 6 дней)
    # написан для тех, кого ещё можно вернуть; хвост разбирается следующими прогонами.
    out.sort(key=lambda t: (t["number"], t["silent_days"]))

    # Суточный бюджет менеджера — последним фильтром, уже на отсортированном списке:
    # так до лимита доходят самые полезные касания, а не случайные.
    if daily_limit:
        kept: list[dict] = []
        for target in out:
            owner = target["owner"]
            if budget.get(owner, 0) >= daily_limit:
                continue
            budget[owner] = budget.get(owner, 0) + 1
            kept.append(target)
        out = kept

    limit = max(0, int(getattr(cfg, "touch_batch_limit", 20)))
    return out[:limit] if limit else out


async def _counts(sessionmaker, day) -> tuple[dict[str, int], dict[str, int]]:
    """Сколько касаний сделано по каждому диалогу и сколько создано сегодня по менеджеру.

    Читает только задачи. Признак касания — автор `bot` плюс комментарий «Касание …»:
    отдельного вида задачи не вводим, потому что `kind` разошёлся бы с интерфейсом
    календаря, где виды задач перечислены руками.
    """
    from sqlalchemy import func, select
    from app.domain.models import CalendarTask
    is_touch = (CalendarTask.created_by == "bot",
                CalendarTask.comment.like("Касание %"))
    async with sessionmaker() as session:
        by_user = (await session.execute(
            select(CalendarTask.user_id, func.count()).where(*is_touch)
            .group_by(CalendarTask.user_id))).all()
        today = (await session.execute(
            select(CalendarTask.manager_id, func.count())
            .where(*is_touch, CalendarTask.scheduled_date == day)
            .group_by(CalendarTask.manager_id))).all()
    return ({str(u): int(c) for u, c in by_user if u},
            {str(m): int(c) for m, c in today if m})


async def run(now: datetime | None = None, *, sessionmaker=None) -> int:
    """Джоба: создать задачи-напоминания. Возвращает число созданных задач."""
    from app.core import flags
    from app.domain.calendar_tasks import CalendarTaskService, bishkek_today
    from app.domain.models import DIRECTIONS
    from app.domain.services import ContactService
    from app.integrations.panel.store import get_conversation_store

    cfg = settings
    if not await flags.get_flag(FLAG, cfg.visa_touch_tasks_enabled):
        return 0
    if await flags.get_flag("followup_enabled", cfg.followup_enabled):
        # Оба включены — клиент получит и письмо бота, и сообщение менеджера.
        log.warning("touches: followup_enabled тоже включён — клиент получит два "
                    "касания, одно от бота и одно от менеджера")

    now_dt = _aware(now) or datetime.now(timezone.utc)
    if sessionmaker is None:
        from app.integrations.crm.db import get_sessionmaker
        sessionmaker = get_sessionmaker()

    day = bishkek_today(now_dt)
    done_by_user, today_by_owner = await _counts(sessionmaker, day)
    convs = await get_conversation_store().all_conversations_light()
    targets = select_touch_targets(convs, now_dt, cfg, done_by_user=done_by_user,
                                   today_by_owner=today_by_owner)
    if not targets:
        return 0
    created = 0
    async with sessionmaker() as session:
        for target in targets:
            conv = target["conv"]
            ident = (str(getattr(conv, "phone", "") or "")
                     or str(getattr(conv, "user_id", "") or "")).strip()
            if not ident:
                continue
            direction = str(getattr(conv, "funnel", "") or "").strip()
            if direction not in DIRECTIONS:
                continue
            is_whatsapp = str(getattr(conv, "channel", "") or "").strip().lower() in (
                "whatsapp", "wappi")
            try:
                contact = await ContactService.find_or_create_by_identity(
                    session, "phone", ident, assume_e164=is_whatsapp)
                await CalendarTaskService.create(
                    session, manager_id=target["owner"], direction=direction,
                    kind="call", scheduled_date=day, scheduled_at=None,
                    contact_id=contact.id, user_id=getattr(conv, "user_id", "") or "",
                    priority="normal", created_by="bot",
                    comment=(f"Касание {target['number']} — клиент молчит "
                             f"{target['silent_days']} дн. Текст: {target['text']}"))
                created += 1
            except Exception:  # noqa: BLE001 — один лид не должен валить остальные
                log.warning("touch task failed user=%s",
                            getattr(conv, "user_id", "?"), exc_info=True)
        await session.commit()
    if created:
        log.info("touch tasks created=%d", created)
    return created
