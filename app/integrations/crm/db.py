"""Слой БД для сделок бота (SQLAlchemy async).

Это НЕ замена Bitrix24 как источника правды по клиенту — это собственная
персистентная запись бота: переживает рестарт (в отличие от CrmStub в памяти)
и служит фундаментом под аналитику ИИ (конверсия ИИ vs менеджер — «не Bitrix-зона»).

Движок/сессии создаются лениво из `settings.database_url`. Для тестов sessionmaker
можно подменить (SQLite в памяти) — сетевой Postgres не требуется.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        func, inspect, text)
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.config import settings


class Base(DeclarativeBase):
    pass


class Deal(Base):
    """Сделка/лид, как её видит бот (зеркало действий в воронке)."""

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True)
    funnel: Mapped[str] = mapped_column(String(32))           # tours | visa | tickets
    stage: Mapped[str] = mapped_column(String(64), default="new")
    contact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)       # квалификация
    notes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    """Диалог бот↔клиент — карточка на канбан-доске админ-панели.

    Создаётся при первом входящем сообщении (ещё до сделки). `stage`/`funnel` —
    позиция в воронке (колонка доски), `intercepted` — перехвачен ли менеджером.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # user_id — КЛЮЧ диалога вида "<bot_id>:<номер>": один номер у разных ботов = разные
    # диалоги (перехват/состояние/карточка раздельные). Телефон для показа — в `phone`.
    user_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    phone: Mapped[str] = mapped_column(String(64), default="")      # номер клиента для отображения
    channel: Mapped[str] = mapped_column(String(32), default="")
    chat_id: Mapped[str] = mapped_column(String(128), default="")  # адрес ответа (Bitrix DIALOG_ID ≠ user_id)
    bot_id: Mapped[str] = mapped_column(String(64), default="")
    funnel: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(64), default="greeting")
    intercepted: Mapped[bool] = mapped_column(default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    qualification: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ai_summary: Mapped[str] = mapped_column(Text, default="")
    manager_next_step: Mapped[str] = mapped_column(Text, default="")
    escalation_reason: Mapped[str] = mapped_column(Text, default="")
    lead_temperature: Mapped[str] = mapped_column(String(16), default="new")
    # Логин менеджера, ведущего диалог. Nullable намеренно: на проде колонку добавлял
    # self-heal-DDL (`VARCHAR(64) DEFAULT ''`) без NOT NULL, поэтому NULL там ВОЗМОЖЕН.
    # Объявляем так же, иначе `create_all` в тестах даёт NOT NULL и ветка «бесхозный =
    # NULL» физически не покрывается. Новые строки по-прежнему получают "" по default.
    assigned_to: Mapped[str | None] = mapped_column(String(64), default="")
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # P1.1: когда по ГОТОВОЙ заявке ушёл мгновенный пуш владельцу. NULL = ещё не ушёл;
    # условный UPDATE по этой колонке и есть дедуп (стадия office бота не перехватывает,
    # поэтому инструмент эскалации может вызваться повторно на следующих ходах).
    handoff_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(24), default="")       # in_progress|office|manager|won|lost
    last_text: Mapped[str] = mapped_column(Text, default="")  # превью последней реплики для карточки
    last_sender: Mapped[str] = mapped_column(String(16), default="")  # client|bot|manager — для сигналов
    followup_sent: Mapped[bool] = mapped_column(default=False)  # legacy: автодожим отправлен (один раз)
    followup_count: Mapped[int] = mapped_column(default=0)  # сколько пингов дожима отправлено (ритм 2×/нед)
    bitrix_lead_id: Mapped[str] = mapped_column(String(32), default="")  # id лида Bitrix (зеркало диалога)
    bitrix_stage_by_bot: Mapped[str] = mapped_column(String(32), default="")
    bitrix_dossier_by_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    bitrix_deal_id: Mapped[str] = mapped_column(String(32), default="")
    # Мотор готовности «Покупатели сегодня» (детерминированный, из app/core/readiness.py).
    readiness_tier: Mapped[str] = mapped_column(String(16), default="")       # green|warm|noise|insufficient
    readiness_reason: Mapped[str] = mapped_column(Text, default="")
    readiness_signals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    readiness_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_value: Mapped[float | None] = mapped_column(Float, nullable=True)   # оценка чека
    estimated_value_currency: Mapped[str] = mapped_column(String(8), default="")
    # Авто-исход через LLM (advisory, НЕ затирает ручной outcome). Пусто, пока фича выключена.
    outcome_inferred: Mapped[str] = mapped_column(String(16), default="")       # won|lost|ghosted|active
    outcome_inferred_reason: Mapped[str] = mapped_column(Text, default="")
    # Источник лида (Click-to-WhatsApp Ads): откуда пришёл клиент. Write-once — первое касание.
    source: Mapped[str] = mapped_column(String(16), default="")        # ad | post | "" (organic/неизвестно)
    source_id: Mapped[str] = mapped_column(String(128), default="")    # id объявления/поста
    source_headline: Mapped[str] = mapped_column(String(300), default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # весь нормализованный referral
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # last_message_at = время последнего СООБЩЕНИЯ (ставит add_message явно), НЕ последнего
    # апдейта строки. Без onupdate: иначе фоновый sweep/исход/перехват двигали бы его на «сейчас»
    # и застойные диалоги ложно всплывали бы как активные сегодня.
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    messages: Mapped[list["ConvMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="ConvMessage.id"
    )


class ConvMessage(Base):
    """Одно сообщение в диалоге (для чат-окна панели — чистый человекочитаемый лог).

    Для исходящих (bot|manager) дополнительно трекаем доставку: status переходит
    pending→sent→delivered/failed; provider_msg_id — id сообщения у Wappi (для сверки
    с delivery-status вебхуками); idempotency_key защищает от двойной отправки.
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender: Mapped[str] = mapped_column(String(16))          # client | bot | manager
    text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="")       # "" (входящее) | pending|sent|delivered|failed
    provider_msg_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class AuditLog(Base):
    """Журнал действий менеджеров (кто/что/когда над каким диалогом) — подотчётность."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manager: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(32))          # login|takeover|release|send|outcome|resend
    user_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BotError(Base):
    """P1.4: журнал ошибок бота — «бот иногда ошибается, к сентябрю чтобы был опытным».

    Простое накопление переписок модель НЕ обучает, поэтому нужен явный цикл: поймали →
    записали с категорией → починили → закрыли РЕГРЕССИОННЫМ ТЕСТОМ → проверили, что не
    вернулась. Поле ``covered_by_test`` обязательно при закрытии: без теста «починили»
    означает «починили до следующего раза».

    Интерфейса в панели намеренно нет: менеджеры, которые не осилили Start в Telegram,
    категорию не выберут. Канал — владелец: «перешли кривой диалог в наш чат», категорию
    ставим мы.
    """

    __tablename__ = "bot_errors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
    source: Mapped[str] = mapped_column(String(16), default="owner")   # owner|manager|auto
    # price|country|misunderstood|no_handoff|tone|other — см. app/core/bot_errors.CATEGORIES
    category: Mapped[str] = mapped_column(String(24), default="other", index=True)
    user_id: Mapped[str] = mapped_column(String(160), default="", index=True)
    bot_id: Mapped[str] = mapped_column(String(64), default="")
    funnel: Mapped[str] = mapped_column(String(32), default="")
    quote: Mapped[str] = mapped_column(Text, default="")      # что бот сказал не так
    expected: Mapped[str] = mapped_column(Text, default="")   # как должно было быть
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    covered_by_test: Mapped[str] = mapped_column(String(200), default="")
    fix_ref: Mapped[str] = mapped_column(String(80), default="")       # коммит/PR
    fixed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class AppFlag(Base):
    """Рантайм-флаги фич (вкл/выкл из админки), переживающие рестарт."""

    __tablename__ = "app_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FaqEntry(Base):
    """Deterministic FAQ rule managed from the admin panel."""

    __tablename__ = "faq_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    funnel: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    title: Mapped[str] = mapped_column(String(160), default="")
    patterns: Mapped[list[str]] = mapped_column(JSON, default=list)
    negative_terms: Mapped[list[str]] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text, default="")
    handoff_only: Mapped[bool] = mapped_column(default=False)
    allow_during_qualification: Mapped[bool] = mapped_column(default=True)
    updated_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TourOffer(Base):
    """Подборка туров, отправленная клиенту, — она же страница `/t/{slug}`.

    Храним снимок, а не ссылку на живой поиск: TourVisor отдаёт результат по `requestid`,
    который живёт минуты, а клиент открывает подборку и вечером, и назавтра. Показать ему
    пустую страницу вместо тех же вариантов, что он видел в чате, — хуже, чем показать
    цену суточной давности рядом с честной оговоркой «цены меняются, уточните у менеджера».
    """

    __tablename__ = "tour_offers"

    slug: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="")
    bot_id: Mapped[str] = mapped_column(String(64), default="")
    departure: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    views: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Ленивый singleton фабрики сессий по `settings.database_url`."""
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_models(engine: AsyncEngine) -> None:
    """Создать таблицы (дев/тесты без Alembic). В проде схему ведёт Alembic."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn, "conversations", {
            "phone": "VARCHAR(64) DEFAULT ''",
            "ai_summary": "TEXT DEFAULT ''",
            "manager_next_step": "TEXT DEFAULT ''",
            "escalation_reason": "TEXT DEFAULT ''",
            "lead_temperature": "VARCHAR(16) DEFAULT 'new'",
            "assigned_to": "VARCHAR(64) DEFAULT ''",
            "assigned_at": "TIMESTAMPTZ",
            "handoff_notified_at": "TIMESTAMPTZ",
            "outcome": "VARCHAR(24) DEFAULT ''",
            "followup_sent": "BOOLEAN DEFAULT FALSE",
            "followup_count": "INTEGER DEFAULT 0",
            "bitrix_lead_id": "VARCHAR(32) DEFAULT ''",
            "bitrix_stage_by_bot": "VARCHAR(32) DEFAULT ''",
            "bitrix_dossier_by_bot": "BOOLEAN DEFAULT FALSE",
            "bitrix_deal_id": "VARCHAR(32) DEFAULT ''",
            "archived": "BOOLEAN DEFAULT FALSE",
            "readiness_tier": "VARCHAR(16) DEFAULT ''",
            "readiness_reason": "TEXT DEFAULT ''",
            "readiness_signals": "JSON DEFAULT '{}'",
            "readiness_scored_at": "TIMESTAMPTZ",
            "estimated_value": "DOUBLE PRECISION",
            "estimated_value_currency": "VARCHAR(8) DEFAULT ''",
            "outcome_inferred": "VARCHAR(16) DEFAULT ''",
            "outcome_inferred_reason": "TEXT DEFAULT ''",
            "source": "VARCHAR(16) DEFAULT ''",
            "source_id": "VARCHAR(128) DEFAULT ''",
            "source_headline": "VARCHAR(300) DEFAULT ''",
            "source_url": "TEXT DEFAULT ''",
            "source_payload": "JSON DEFAULT '{}'",
        })
        await _ensure_columns(conn, "messages", {
            "status": "VARCHAR(16) DEFAULT ''",
            "provider_msg_id": "VARCHAR(128) DEFAULT ''",
            "idempotency_key": "VARCHAR(128) DEFAULT ''",
        })
        await _ensure_columns(conn, "faq_entries", {
            "funnel": "VARCHAR(32)",
            "enabled": "BOOLEAN DEFAULT TRUE",
            "priority": "INTEGER DEFAULT 0",
            "title": "VARCHAR(160) DEFAULT ''",
            "patterns": "JSON DEFAULT '[]'",
            "negative_terms": "JSON DEFAULT '[]'",
            "answer": "TEXT DEFAULT ''",
            "handoff_only": "BOOLEAN DEFAULT FALSE",
            "allow_during_qualification": "BOOLEAN DEFAULT TRUE",
            "updated_by": "VARCHAR(64) DEFAULT ''",
        })


async def _ensure_columns(conn, table: str, additions: dict[str, str]) -> None:
    """Идемпотентно добавить недостающие колонки (апгрейд старых инсталляций без Alembic)."""
    existing = await conn.run_sync(
        lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns(table)}
    )
    for column, ddl in additions.items():
        if column not in existing:
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    """Идемпотентно создать схему на боевом движке (вызывается при старте приложения,
    если crm_backend=postgres). Для управляемых миграций в проде — Alembic."""
    get_sessionmaker()  # инициализирует _engine
    assert _engine is not None
    await init_models(_engine)
