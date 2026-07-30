"""P1.4: петля «бот ошибся» — от жалобы до регрессионного теста.

Требование встречи 29.07: «бот иногда ошибается», «надо вот этот бот тоже контролить»,
«чтобы к сентябрю был опытным». Важное, что стоит сказать заказчику прямо: **простое
накопление переписок модель не обучает**. Опытнее бот становится только через явный цикл:

1. поймали ошибку (владелец пересылает кривой диалог);
2. записали с категорией — ``report()``;
3. починили;
4. закрыли, указав РЕГРЕССИОННЫЙ ТЕСТ — ``mark_fixed()`` без теста не закрывает;
5. проверили, что не вернулась — тест в общем прогоне.

Почему без интерфейса в панели: ожидать от менеджеров, которые не осилили Start в
Telegram, что они нажмут кнопку и выберут категорию — нереалистично. Канал — владелец,
категорию ставим мы. Отсюда же CLI: ``python scripts/bot_error.py``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, select

logger = logging.getLogger("bot_errors")

# Категории — из реальных жалоб по проекту, не абстрактные.
CATEGORIES = {
    "price": "назвал цену/скидку, которых не должен был",
    "country": "напутал страну или условия визы",
    "misunderstood": "не понял запрос, ответил не по делу",
    "no_handoff": "не передал менеджеру, когда был обязан",
    "tone": "тон/язык: не как живой менеджер",
    "other": "прочее",
}
OPEN, FIXED, WONTFIX = "open", "fixed", "wontfix"


class BotErrorInput(ValueError):
    """Неверные данные записи (неизвестная категория, закрытие без теста)."""


def _sessionmaker(sessionmaker=None):
    if sessionmaker is not None:
        return sessionmaker
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


async def report(*, category: str, quote: str = "", expected: str = "",
                 user_id: str = "", source: str = "owner", note: str = "",
                 sessionmaker=None) -> int:
    """Записать ошибку. Возвращает id. Контекст диалога подтягивается сам по user_id."""
    from app.integrations.crm.db import BotError, Conversation
    if category not in CATEGORIES:
        raise BotErrorInput(
            f"неизвестная категория {category!r}; доступны: {', '.join(sorted(CATEGORIES))}")
    if not (quote or expected or note):
        raise BotErrorInput("нужна хотя бы цитата, ожидание или заметка — пустую не пишем")
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        bot_id = funnel = ""
        if user_id:
            conv = (await session.execute(select(Conversation).where(
                Conversation.user_id == user_id))).scalar_one_or_none()
            if conv is not None:
                bot_id, funnel = (conv.bot_id or ""), (conv.funnel or "")
        row = BotError(source=source, category=category, user_id=user_id,
                       bot_id=bot_id, funnel=funnel, quote=quote.strip(),
                       expected=expected.strip(), note=note.strip(), status=OPEN)
        session.add(row)
        await session.commit()
        logger.info("bot error recorded id=%s category=%s", row.id, category)
        return row.id


async def mark_fixed(error_id: int, *, covered_by_test: str, fix_ref: str = "",
                     sessionmaker=None) -> bool:
    """Закрыть ошибку. БЕЗ регрессионного теста не закрывается — это и есть весь смысл
    петли: «починили» без теста означает «починили до следующего раза»."""
    from app.integrations.crm.db import BotError
    if not (covered_by_test or "").strip():
        raise BotErrorInput(
            "нужен регрессионный тест (covered_by_test): без него ошибка вернётся")
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        row = await session.get(BotError, error_id)
        if row is None or row.status == FIXED:
            return False
        row.status = FIXED
        row.covered_by_test = covered_by_test.strip()
        row.fix_ref = (fix_ref or "").strip()
        row.fixed_at = datetime.now(timezone.utc)
        await session.commit()
        return True


async def mark_wontfix(error_id: int, *, note: str, sessionmaker=None) -> bool:
    """Закрыть без исправления — с обязательным объяснением, почему так и оставили."""
    from app.integrations.crm.db import BotError
    if not (note or "").strip():
        raise BotErrorInput("wontfix требует объяснения")
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        row = await session.get(BotError, error_id)
        if row is None or row.status != OPEN:
            return False
        row.status = WONTFIX
        row.note = ((row.note + "\n") if row.note else "") + note.strip()
        row.fixed_at = datetime.now(timezone.utc)
        await session.commit()
        return True


async def open_errors(*, limit: int = 50, sessionmaker=None) -> list:
    from app.integrations.crm.db import BotError
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        # id в tie-break обязателен: created_at — server_default с точностью до секунды,
        # и несколько записей одной минутой давали бы произвольный порядок.
        return (await session.execute(
            select(BotError).where(BotError.status == OPEN)
            .order_by(BotError.created_at.desc(), BotError.id.desc())
            .limit(limit))).scalars().all()


async def counts(*, sessionmaker=None) -> dict[str, dict[str, int]]:
    """Сводка «сколько открыто и закрыто по категориям» — чем меряем прогресс к сентябрю."""
    from app.integrations.crm.db import BotError
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        rows = (await session.execute(
            select(BotError.category, BotError.status, func.count(BotError.id))
            .group_by(BotError.category, BotError.status))).all()
    out: dict[str, dict[str, int]] = {}
    for category, status, n in rows:
        out.setdefault(category, {})[status] = n
    return out


async def untested_fixes(*, sessionmaker=None) -> list:
    """Закрытые без ссылки на тест. Должно быть пусто: иначе петля протекает."""
    from app.integrations.crm.db import BotError
    sm = _sessionmaker(sessionmaker)
    async with sm() as session:
        return (await session.execute(select(BotError).where(
            BotError.status == FIXED, BotError.covered_by_test == ""))).scalars().all()
