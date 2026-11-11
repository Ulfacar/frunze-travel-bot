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
from datetime import date, datetime, timedelta, timezone

from app.config import settings

log = logging.getLogger(__name__)

BISHKEK = timedelta(hours=6)          # задачи живут по календарному дню Бишкека
FLAG = "visa_touch_tasks_enabled"
CLOSE_FLAG = "auto_close_after_touches_enabled"
TERMINAL_OUTCOMES = {"won", "lost"}
# Причина из справочника панели (`router.LOST_REASONS`). Берём код, а не текст:
# тексты менеджер ещё поправит, а код в отчёте «почему теряем» должен быть стабильным.
NO_ANSWER_REASON = "no_answer"

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


def gap_after_previous(number: int, cfg) -> int:
    """Сколько дней должно пройти ПОСЛЕ предыдущего касания, прежде чем делать это.

    Без этой паузы касания сыпались пачкой: срок считается от последнего сообщения
    клиента, а прогон идёт каждые пять минут, поэтому лид, молчащий десять дней,
    получал касание 1 на одном тике, касание 2 — на следующем и касание 3 — на
    третьем. Три задачи с текстами «1 день / 3 дня / 6 дней» за четверть часа,
    которые клиенту подряд отправлять нельзя. Найдено ревью 12.11.2026.

    Пауза берётся из её же графика: между первым и вторым касанием два дня,
    между вторым и третьим — три. Минимум сутки, чтобы правка графика на
    одинаковые числа не вернула пачку.
    """
    schedule = list(getattr(cfg, "touch_after_days", None) or (1, 3, 6))
    if number <= 1 or number > len(schedule):
        return 0
    return max(1, int(schedule[number - 1]) - int(schedule[number - 2]))


def due_after_days(number: int, cfg) -> int | None:
    """Через сколько дней молчания пора делать касание `number`. None — касаний больше нет."""
    schedule = list(getattr(cfg, "touch_after_days", None) or (1, 3, 6))
    if number < 1 or number > len(schedule):
        return None
    return int(schedule[number - 1])


def select_touch_targets(convs: list, now: datetime, cfg, *,
                         done_by_user: dict[str, int] | None = None,
                         today_by_owner: dict[str, int] | None = None,
                         last_touch_by_user: dict[str, object] | None = None,
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
    last_touch = last_touch_by_user or {}
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
        # Фильтра мусора здесь намеренно НЕТ, хотя ревью 12.11.2026 его предлагало.
        # Проверено: `leadstate.is_noise` для кандидата касания недостижим — он
        # требует диалога БЕЗ владельца, а мы ниже берём только диалоги с владельцем;
        # `looks_unseen_conversation` читает историю сообщений, которой нет в лёгкой
        # выборке `all_conversations_light`, и всегда вернул бы False. Поставить их
        # значило бы завести мёртвый код и ложное чувство защиты.
        # Сам риск здесь мал: касание — это ЗАДАЧА МЕНЕДЖЕРУ, а не сообщение клиенту.
        # Бот никому не пишет, человек смотрит карточку и решает сам.
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
        gap = gap_after_previous(number, cfg)
        previous = last_touch.get(getattr(c, "user_id", ""))
        if gap and previous is not None:
            # Дата касания — календарный день Бишкека (так её кладёт задача), поэтому
            # сравниваем днями, а не метками времени.
            done_on = previous if isinstance(previous, date) else None
            if done_on is not None and (now + BISHKEK).date() - done_on < timedelta(days=gap):
                continue        # предыдущее касание слишком свежее
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


def select_closable(convs: list, now: datetime, cfg, *,
                    done_by_user: dict[str, int] | None = None,
                    allowed_funnels: set[str] | None = None) -> list[dict]:
    """Кого пора перевести в «Не реализовано». Чистая функция: ни базы, ни сети.

    Её ответ на вопрос 4: «Если клиент не отвечает, переводим его в стадию
    „Не реализовано“ с причиной „Не выходит на связь“. При этом сохраняем всю историю
    переписки, чтобы при повторном обращении можно было продолжить работу».

    Два условия вместе, и второе важнее первого. Мало того, что все касания сделаны —
    после последнего должно пройти `auto_close_after_days` молчания. Иначе закрытие
    прилетит клиенту, который как раз сегодня читает третье сообщение; счётчик касаний
    говорит лишь о том, что менеджеру поставили задачу, а не о том, что клиент успел
    ответить.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    done_by_user = done_by_user or {}
    funnels = (allowed_funnels if allowed_funnels is not None
               else set(getattr(cfg, "touch_funnels", None) or ("visa",)))
    needed = len(list(getattr(cfg, "touch_after_days", None) or (1, 3, 6)))
    silence = int(getattr(cfg, "auto_close_after_days", 7) or 0)

    out: list[dict] = []
    for c in convs:
        if str(getattr(c, "funnel", "") or "") not in funnels:
            continue
        if getattr(c, "archived", False):
            continue
        if str(getattr(c, "outcome", "") or "") in TERMINAL_OUTCOMES:
            continue            # уже закрыт — ни победу, ни отказ не переписываем
        if str(getattr(c, "last_sender", "") or "") not in ("manager", "bot"):
            continue            # клиент ответил последним — он не пропал
        if done_by_user.get(getattr(c, "user_id", ""), 0) < needed:
            continue            # касания ещё не кончились
        last = _aware(getattr(c, "last_message_at", None))
        if last is None or (silence and last > now - timedelta(days=silence)):
            continue            # молчит не настолько долго
        out.append({"conv": c, "silent_days": (now - last).days})

    out.sort(key=lambda item: -item["silent_days"])
    limit = max(0, int(getattr(cfg, "auto_close_batch_limit", 20)))
    return out[:limit] if limit else out


async def _answered_after_touches(sessionmaker, user_ids: list[str],
                                  last_touch: dict) -> set[str]:
    """Кто из кандидатов писал нам ПОСЛЕ последнего касания.

    Счётчик касаний вечен: три задачи, созданные в октябре, остаются «тремя
    касаниями» навсегда. Поэтому клиент, который на касание ОТВЕТИЛ, подождал ответа
    менеджера и снова замолчал, попадал под закрытие с причиной «Не выходит на связь»
    — хотя на связь он выходил. Такая запись потом идёт в отчёт «почему теряем»
    (аудит 12.11.2026).
    """
    if not user_ids:
        return set()
    from sqlalchemy import select
    from app.integrations.crm.db import ConvMessage, Conversation
    answered: set[str] = set()
    async with sessionmaker() as session:
        rows = (await session.execute(
            select(Conversation.user_id, ConvMessage.created_at)
            .join(ConvMessage, ConvMessage.conversation_id == Conversation.id)
            .where(Conversation.user_id.in_(user_ids),
                   ConvMessage.sender == "client"))).all()
    for user_id, created_at in rows:
        touched_on = last_touch.get(str(user_id))
        if touched_on is None or created_at is None:
            continue
        stamp = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        if (stamp + BISHKEK).date() >= touched_on:
            answered.add(str(user_id))
    return answered


async def _closed_today(sessionmaker, day) -> int:
    """Сколько диалогов бот закрыл сегодня. Журнал — единственный след автозакрытия."""
    from sqlalchemy import func, select
    from app.integrations.crm.db import AuditLog
    async with sessionmaker() as session:
        return int(await session.scalar(
            select(func.count()).select_from(AuditLog)
            .where(AuditLog.manager == "bot", AuditLog.action == "outcome",
                   func.date(AuditLog.created_at) == day)) or 0)


async def close_stale(now: datetime | None = None, *, sessionmaker=None,
                      dry_run: bool = False) -> int:
    """Перевести отмолчавшихся в «Не реализовано». Возвращает число закрытых.

    История переписки остаётся нетронутой — меняются только исход и причина, как она
    и просила. Повторное обращение клиента СНИМАЕТ это закрытие: входящее сообщение
    сбрасывает исход и причину в `store.add_message`, если причина наша (`no_answer`).
    Раньше это было лишь обещанием в тексте: `_is_auto_downgrade` не даёт авто-исходам
    переписать финал, и вернувшийся клиент оставался невидимым для сторожа ожидания,
    утреннего листа и самих касаний (аудит 12.11.2026).
    """
    from app.core import flags
    from app.integrations.panel.store import get_conversation_store

    cfg = settings
    if not await flags.get_flag(CLOSE_FLAG, cfg.auto_close_after_touches_enabled):
        return 0
    now_dt = _aware(now) or datetime.now(timezone.utc)
    if sessionmaker is None:
        from app.integrations.crm.db import get_sessionmaker
        sessionmaker = get_sessionmaker()

    from app.domain.calendar_tasks import bishkek_today
    day = bishkek_today(now_dt)
    done_by_user, _today, last_touch = await _counts(sessionmaker, day)
    store = get_conversation_store()
    targets = select_closable(await store.all_conversations_light(), now_dt, cfg,
                              done_by_user=done_by_user)

    # Клиент, ответивший после касаний, закрывается с ЛОЖНОЙ причиной «не выходит на
    # связь» — счётчик касаний вечен и об ответе не знает. Спрашиваем базу поимённо,
    # и только по кандидатам: их единицы, запрос дешёвый.
    answered = await _answered_after_touches(
        sessionmaker, [getattr(t["conv"], "user_id", "") for t in targets], last_touch)
    targets = [t for t in targets
               if getattr(t["conv"], "user_id", "") not in answered]

    # Суточный предел. Порция `auto_close_batch_limit` — это предел НА ПРОГОН, а
    # прогон идёт каждые пять минут: 288 раз в сутки. Предохранитель, который в
    # подсказке тумблера выглядит как «не больше 20», им не был (аудит 12.11.2026).
    daily = max(0, int(getattr(cfg, "auto_close_daily_limit", 20) or 0))
    if daily:
        already = await _closed_today(sessionmaker, day)
        if already >= daily:
            return 0
        targets = targets[:max(0, daily - already)]

    if dry_run:
        return len(targets)

    closed = 0
    for target in targets:
        user_id = getattr(target["conv"], "user_id", "")
        try:
            await store.update_meta(user_id, outcome="lost",
                                    outcome_reason=NO_ANSWER_REASON)
            await store.add_audit("bot", "outcome", user_id,
                                  f"lost:{NO_ANSWER_REASON}")
            closed += 1
        except Exception:  # noqa: BLE001 — один диалог не должен валить остальные
            log.warning("auto-close failed user=%s", user_id, exc_info=True)
    if closed:
        log.info("auto-closed after touches: %d", closed)
    return closed


async def _counts(sessionmaker, day) -> tuple[dict[str, int], dict[str, int], dict[str, date]]:
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
        # Бюджет считаем по дате СОЗДАНИЯ, а не по дате, на которую задача стоит.
        # Иначе его обходит обычное действие менеджера: «Перенести на завтра»
        # меняет scheduled_date, задача уходит из сегодняшнего счёта, и через пять
        # минут приходит новая порция. Медина могла получать их весь день
        # (аудит 12.11.2026).
        today = (await session.execute(
            select(CalendarTask.manager_id, func.count())
            .where(*is_touch, func.date(CalendarTask.created_at) == day)
            .group_by(CalendarTask.manager_id))).all()
        # Дата последнего касания по диалогу — чтобы следующее не ушло в тот же час.
        latest = (await session.execute(
            select(CalendarTask.user_id, func.max(CalendarTask.scheduled_date))
            .where(*is_touch).group_by(CalendarTask.user_id))).all()
    return ({str(u): int(c) for u, c in by_user if u},
            {str(m): int(c) for m, c in today if m},
            {str(u): d for u, d in latest if u and d})


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
    done_by_user, today_by_owner, last_touch_by_user = await _counts(sessionmaker, day)
    convs = await get_conversation_store().all_conversations_light()
    targets = select_touch_targets(convs, now_dt, cfg, done_by_user=done_by_user,
                                   today_by_owner=today_by_owner,
                                   last_touch_by_user=last_touch_by_user)
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


async def run_all(now: datetime | None = None, *, sessionmaker=None) -> None:
    """Джоба планировщика: сначала касания, потом закрытие отмолчавшихся.

    Порядок важен: закрытие смотрит на число сделанных касаний, и если бы оно шло
    первым, клиент закрывался бы на один прогон раньше срока.
    """
    await run(now, sessionmaker=sessionmaker)
    await close_stale(now, sessionmaker=sessionmaker)
