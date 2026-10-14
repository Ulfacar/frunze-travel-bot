"""B1 на настоящем Postgres: захват ключа отправки атомарен (ревью B1, находка 1).

Индекс `messages.idempotency_key` не уникальный (legacy-таблица бота, миграцию не трогаем),
поэтому атомарность держит транзакционная advisory-блокировка. SQLite её не проверяет.
Запуск только на изолированном локальном кластере (FRUNZE_LOCAL_PG_CONNECTION).
"""
import asyncio
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.integrations.crm import db
from app.integrations.panel.store import PostgresConversationStore
from tests.test_entry_process_postgres import connection, database, db_url


def test_concurrent_same_key_creates_one_message(monkeypatch):
    config = connection()
    name = 'frunze_e610_' + uuid.uuid4().hex[:24]
    database(config, name)
    try:
        engine = create_async_engine(db_url(config, name), pool_size=10)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(db, '_engine', engine)
        monkeypatch.setattr(db, '_sessionmaker', sm)
        store = PostgresConversationStore()
        key = 'getvisa:996700000001'
        # Окно гонки: без блокировки все восемь успевают «не найти» ключ до первой вставки.
        original = store._ensure_row

        async def slow_ensure_row(*args, **kwargs):
            await asyncio.sleep(0.05)
            return await original(*args, **kwargs)
        monkeypatch.setattr(store, '_ensure_row', slow_ensure_row)

        async def run():
            async with engine.begin() as conn:
                await conn.run_sync(db.Base.metadata.create_all)
            await store.add_message(key, 'client', 'нужна виза', channel='whatsapp', bot_id='getvisa',
                                    chat_id='996700000001@c.us', phone='996700000001')
            # Прогрев пула: иначе семь запросов ждут открытия соединения, первый успевает
            # закоммитить, и гонка закрывается сама — тест прошёл бы и без блокировки
            # (проверено мутантом 14.10).
            from sqlalchemy import text as sql

            async def warm():
                async with sm() as s_:
                    await s_.execute(sql('SELECT pg_sleep(0.2)'))
            await asyncio.gather(*[warm() for _ in range(8)])
            results = await asyncio.gather(*[
                store.add_message_once(key, 'manager', 'ответ', idempotency_key='crm-send:k',
                                       status='pending') for _ in range(8)])
            async with sm() as s:
                rows = await s.scalar(select(func.count()).select_from(db.ConvMessage)
                                      .where(db.ConvMessage.idempotency_key == 'crm-send:k'))
            await engine.dispose()
            return results, rows

        results, rows = asyncio.run(run())
        assert rows == 1
        assert sum(created for _, created in results) == 1
        assert len({mid for mid, _ in results}) == 1
    finally:
        database(config, name, drop=True)
