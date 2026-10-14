"""B1: CRM на данных бота (`CRM_DATA_MODE=bot`). Доказательства из предаудита
ai/reviews/2026-10-14-b1-pre-audit.md, раздел 2.

Синтетика: SQLite вместо БД бота, фейковый Redis, фейковый Wappi. Ни одного вызова
провайдера, реальных номеров или токенов.
"""
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import BotConfig, ManagerConfig, TelegramBotConfig, settings
from app.core import bots, state
from app.crm_main import BOT_GETS, BOT_POSTS, BOT_SEND_POSTS, SCHEMA, create_app, validate_configuration
from app.domain.models import DomainBase
from app.integrations.crm import db

ORIGIN = 'https://crm.test'
PASSWORD = 'SYNTHETIC-private-password-2026'
VISA_KEY = 'getvisa:996700000001'
TOUR_KEY = 'frunze_tours:996700000002'


class FakeRedis:
    def __init__(self):
        self.data = {'frunze:dialog:seed': '{}'}

    async def ping(self):
        return True

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value

    async def scan_iter(self, match='*', count=100):
        prefix = match.rstrip('*')
        for key in list(self.data):
            if key.startswith(prefix):
                yield key


@pytest.fixture
def configured(monkeypatch, tmp_path):
    assert not Path('.env').exists()
    url = 'sqlite+aiosqlite:///' + str(tmp_path / 'bot.db').replace('\\', '/')
    values = dict(crm_standalone_enabled=True, crm_data_mode='bot', crm_bot_send_enabled=True,
        crm_public_origin=ORIGIN, session_https_only=True, session_secret='SYNTHETIC-' + ('x' * 60),
        demo_login=False, admin_enabled=True, panel_backend='postgres', crm_backend='postgres',
        state_backend='redis', redis_url='redis://redis:6379/0', authz_enforce_enabled=True,
        telegram_bots=[], database_url=url, wappi_token='SYNTHETIC-wappi-token',
        bots=[BotConfig(id='getvisa', scenario='visa', wappi_profile_id='prof-visa'),
              BotConfig(id='frunze_tours', scenario='tours', wappi_profile_id='prof-tours')],
        managers=[ManagerConfig(login='admin', name='Owner', password=PASSWORD, admin=True),
                  ManagerConfig(login='medina', name='Medina', password=PASSWORD),
                  ManagerConfig(login='eliza', name='Eliza', password=PASSWORD)])
    for name in ('telegram_bot_token', 'openrouter_api_key', 'anthropic_api_key', 'stt_api_key',
                 'bitrix24_webhook_url', 'managers_telegram_bot_token', 'managers_telegram_chat_id'):
        values[name] = ''
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(bots, 'registry', bots.BotRegistry(values['bots']))
    redis = FakeRedis()
    monkeypatch.setattr(state, '_redis_store', state.RedisStateStore(redis_client=redis, ttl=3600))
    return dict(url=url, redis=redis)


@pytest.fixture
def crm(configured, monkeypatch):
    url = configured['url']
    engine = create_async_engine(url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(db, '_engine', engine)
    monkeypatch.setattr(db, '_sessionmaker', sm)
    from app.integrations.panel import store
    monkeypatch.setattr(store, '_pg_store', None)

    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(db.Base.metadata.create_all)
            await connection.run_sync(DomainBase.metadata.create_all)
            await connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)'))
            await connection.execute(text('INSERT INTO alembic_version VALUES (:v)'), {'v': SCHEMA})
        panel = store.get_conversation_store()
        await panel.add_message(VISA_KEY, 'client', 'нужна виза', channel='whatsapp', bot_id='getvisa',
                                chat_id='996700000001@c.us', phone='996700000001')
        await panel.add_message(TOUR_KEY, 'client', 'тур в Анталию', channel='whatsapp',
                                bot_id='frunze_tours', chat_id='996700000002@c.us', phone='996700000002')
        # Как на проде: бот проставляет воронку каждому диалогу (14.10: у всех 4048 она есть).
        await panel.update_meta(VISA_KEY, funnel='visa')
        await panel.update_meta(TOUR_KEY, funnel='tours')
    asyncio.run(prepare())
    from app.admin import ratelimit
    ratelimit.reset()
    sent = []

    async def fake_send(self, chat_id, text_, **kw):
        sent.append(dict(profile=self._profile_id, chat=chat_id, text=text_, kw=kw))
        return sent_result['id']
    sent_result = {'id': 'wappi-accepted-1'}
    from app.channels import wappi
    monkeypatch.setattr(wappi.WappiAdapter, 'send', fake_send)
    app = create_app(test_sqlite=True)
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield dict(client=client, app=app, sent=sent, result=sent_result, redis=configured['redis'])
    asyncio.run(engine.dispose())


def login(client, account='admin'):
    r = client.post('/admin/login', data={'login': account, 'password': PASSWORD}, headers={'Origin': ORIGIN})
    assert r.status_code == 303, r.text[-300:]


def send(client, key, body, send_key='k' * 32, origin=ORIGIN):
    return client.post(f'/admin/conversation/{key}/send', data={'text': body, 'send_key': send_key},
                       headers={'Origin': origin})


def messages(key):
    from app.integrations.panel.store import get_conversation_store
    conv = asyncio.run(get_conversation_store().get(key))
    return [(m.sender, m.text, m.status, m.provider_msg_id) for m in conv.messages]


# --- старт: что режим bot обязан запрещать (AC2) ---

@pytest.mark.parametrize('change', [
    {'openrouter_api_key': 'x'}, {'anthropic_api_key': 'x'}, {'stt_api_key': 'x'},
    {'bitrix24_webhook_url': 'https://portal/rest/1/x'}, {'telegram_bot_token': 'x'},
    {'managers_telegram_bot_token': 'x'}, {'managers_telegram_chat_id': '1'},
    {'demo_login': True}, {'state_backend': 'memory'}, {'authz_enforce_enabled': False},
    {'telegram_bots': [TelegramBotConfig(id='t', scenario='visa', token='x')]},
    {'wappi_token': ''},
    {'bots': [BotConfig(id='getvisa', scenario='visa', wappi_profile_id='')]},
    {'bots': [BotConfig(id='getvisa', scenario='visa', wappi_profile_id='p', bitrix_bot_id='7')]},
    {'crm_data_mode': 'other'},
])
def test_bot_mode_refuses_unsafe_configuration(configured, monkeypatch, change):
    for key, value in change.items():
        monkeypatch.setattr(settings, key, value)
    with pytest.raises(RuntimeError):
        validate_configuration(test_sqlite=True)


def test_wappi_token_forbidden_while_sending_disabled(configured, monkeypatch):
    monkeypatch.setattr(settings, 'crm_bot_send_enabled', False)
    with pytest.raises(RuntimeError):
        validate_configuration(test_sqlite=True)


@pytest.mark.parametrize('user', ['postgres', 'frunze'])
def test_bot_mode_refuses_superuser_or_bot_role(configured, monkeypatch, user):
    monkeypatch.setattr(settings, 'database_url', f'postgresql+asyncpg://{user}:{"p" * 40}@db/frunze_crm')
    with pytest.raises(RuntimeError, match='least-privilege'):
        validate_configuration(test_sqlite=False)


# --- таблица маршрутов (AC6, M4) ---

def _routes(app):
    out = set()
    for route in app.router.routes:
        endpoint = getattr(route, 'endpoint', None)
        if getattr(endpoint, '__module__', '') == 'app.admin.router':
            out.add(endpoint.__name__)
    return out


def test_route_table_is_exact_allowlist(crm):
    assert _routes(crm['app']) == BOT_GETS | BOT_POSTS | BOT_SEND_POSTS
    paths = {getattr(r, 'path', '') for r in crm['app'].router.routes}
    for forbidden in ('/admin/flags/{key}', '/admin/conversation/{user_id}/resend/{message_id}',
                      '/admin/conversation/{user_id}/suggest', '/admin/cards', '/admin/system',
                      '/admin/intake', '/admin/work', '/admin/followup/run', '/admin/login/demo'):
        assert forbidden not in paths, forbidden
    assert not any(p.startswith('/admin/case/') for p in paths)


def test_send_route_absent_when_sending_disabled(configured, monkeypatch, crm):
    monkeypatch.setattr(settings, 'crm_bot_send_enabled', False)
    monkeypatch.setattr(settings, 'wappi_token', '')
    assert 'send_message' not in _routes(create_app(test_sqlite=True))


def test_forbidden_route_answers_404_for_admin(crm):
    login(crm['client'])
    r = crm['client'].post(f'/admin/conversation/{VISA_KEY}/resend/1', headers={'Origin': ORIGIN})
    assert r.status_code == 404
    assert crm['sent'] == []


# --- чтение и перехват (AC3, AC4) ---

def test_manager_sees_bot_conversation(crm):
    login(crm['client'], 'medina')
    assert crm['client'].get('/admin').status_code == 200
    page = crm['client'].get(f'/admin/conversation/{VISA_KEY}')
    assert page.status_code == 200 and 'нужна виза' in page.text
    assert 'Предложить ответ' not in page.text


def test_out_of_scope_conversation_is_hidden(crm):
    login(crm['client'], 'medina')
    assert crm['client'].get(f'/admin/conversation/{TOUR_KEY}').status_code == 404
    assert send(crm['client'], TOUR_KEY, 'привет').status_code == 404
    assert crm['sent'] == []


# --- отправка (B2, B3, M6) ---

def test_owner_reply_goes_through_conversation_bot_profile_and_intercepts(crm):
    login(crm['client'], 'medina')
    r = send(crm['client'], VISA_KEY, 'Добрый день, пришлите паспорт')
    assert r.headers['X-Action-Outcome'] == 'sent'
    assert crm['sent'] == [dict(profile='prof-visa', chat='996700000001@c.us',
                                text='Добрый день, пришлите паспорт', kw={'require_acceptance_id': True})]
    assert messages(VISA_KEY)[-1] == ('manager', 'Добрый день, пришлите паспорт', 'sent', 'wappi-accepted-1')
    st = asyncio.run(state.get_state_store().load(VISA_KEY))
    assert st.intercepted is True


def test_other_manager_cannot_send_into_owned_dialog(crm):
    login(crm['client'], 'medina')
    send(crm['client'], VISA_KEY, 'первый ответ', send_key='a' * 32)
    crm['sent'].clear()
    crm['client'].post('/admin/logout', headers={'Origin': ORIGIN})
    login(crm['client'], 'eliza')
    r = send(crm['client'], VISA_KEY, 'перехват', send_key='b' * 32)
    assert r.headers['X-Action-Outcome'] == 'denied'
    assert crm['sent'] == []


def test_flag_row_off_does_not_disable_ownership(crm):
    from app.core.flags import set_flag
    login(crm['client'], 'medina')
    send(crm['client'], VISA_KEY, 'первый ответ', send_key='a' * 32)
    asyncio.run(set_flag('authz_enforce_enabled', False))
    crm['sent'].clear()
    crm['client'].post('/admin/logout', headers={'Origin': ORIGIN})
    login(crm['client'], 'eliza')
    assert send(crm['client'], VISA_KEY, 'перехват', send_key='b' * 32).headers['X-Action-Outcome'] == 'denied'
    assert crm['sent'] == []


def test_domain_failure_denies_instead_of_allowing(crm, monkeypatch):
    from app.domain import live_assign

    async def boom(*a, **k):
        raise RuntimeError('db down')
    monkeypatch.setattr(live_assign, 'contact_for_channel', boom)
    login(crm['client'], 'medina')
    assert send(crm['client'], VISA_KEY, 'ответ').headers['X-Action-Outcome'] == 'denied'
    assert crm['sent'] == []


def test_empty_provider_id_is_failure_not_sent(crm):
    crm['result']['id'] = ''
    login(crm['client'], 'medina')
    assert send(crm['client'], VISA_KEY, 'ответ').headers['X-Action-Outcome'] == 'failed'
    assert messages(VISA_KEY)[-1][2] == 'failed'


def test_same_form_key_is_not_sent_twice(crm):
    login(crm['client'], 'medina')
    assert send(crm['client'], VISA_KEY, 'ответ', send_key='c' * 32).headers['X-Action-Outcome'] == 'sent'
    assert send(crm['client'], VISA_KEY, 'ответ', send_key='c' * 32).headers['X-Action-Outcome'] == 'duplicate'
    assert len(crm['sent']) == 1
    assert [m for m in messages(VISA_KEY) if m[0] == 'manager'] == [('manager', 'ответ', 'sent', 'wappi-accepted-1')]


@pytest.mark.parametrize('bad_key', ['', 'short', 'x' * 65, 'a' * 20 + '!'])
def test_missing_or_bad_form_key_is_refused(crm, bad_key):
    login(crm['client'], 'medina')
    assert send(crm['client'], VISA_KEY, 'ответ', send_key=bad_key).headers['X-Action-Outcome'] == 'denied'
    assert crm['sent'] == []


def test_non_whatsapp_channel_is_refused(crm):
    from app.integrations.panel.store import get_conversation_store
    asyncio.run(get_conversation_store().add_message('getvisa:777', 'client', 'hi', channel='telegram',
                                                     bot_id='getvisa', chat_id='777', phone='777'))
    login(crm['client'], 'medina')
    assert send(crm['client'], 'getvisa:777', 'ответ').headers['X-Action-Outcome'] == 'denied'
    assert crm['sent'] == []


def test_cross_site_post_refused_before_handler(crm):
    login(crm['client'], 'medina')
    assert send(crm['client'], VISA_KEY, 'ответ', origin='https://evil.test').status_code == 403
    assert crm['sent'] == []


# --- готовность: чужой/пустой Redis (M3) ---

def test_startup_refuses_redis_without_bot_dialogs(configured, monkeypatch, crm):
    configured['redis'].data.clear()
    app = create_app(test_sqlite=True)
    with pytest.raises(RuntimeError, match='Redis'):
        with TestClient(app, base_url=ORIGIN):
            pass


# --- разрешённые маршруты без отправки (ревью B1, находка 3) ---

def test_allowed_non_send_routes_work_for_owner(crm):
    c = crm['client']
    login(c, 'medina')
    post = lambda path, data=None: c.post(path, data=data or {}, headers={'Origin': ORIGIN})
    r = post(f'/admin/conversation/{VISA_KEY}/takeover')
    assert r.status_code == 200 and r.headers['X-Action-Outcome'] == 'claimed'
    assert asyncio.run(state.get_state_store().load(VISA_KEY)).intercepted is True
    assert post(f'/admin/conversation/{VISA_KEY}/stage', {'stage': 'qualifying'}).status_code in (200, 400)
    assert post(f'/admin/conversation/{VISA_KEY}/outcome', {'outcome': 'lost'}).status_code == 200
    r = post(f'/admin/conversation/{VISA_KEY}/task/create',
             {'kind': 'call', 'scheduled_date': '2026-10-20', 'scheduled_time': '10:00'})
    assert r.status_code in (200, 303), r.text[-300:]
    assert post(f'/admin/conversation/{VISA_KEY}/release').status_code == 200
    assert asyncio.run(state.get_state_store().load(VISA_KEY)).intercepted is False
    assert c.get('/admin/calendar').status_code == 200
    assert crm['sent'] == []


def test_reassign_is_full_admin_only(crm):
    c = crm['client']
    login(c, 'medina')
    r = c.post(f'/admin/conversation/{VISA_KEY}/reassign', data={'target': 'eliza'}, headers={'Origin': ORIGIN})
    assert r.status_code == 403
    c.post('/admin/logout', headers={'Origin': ORIGIN})
    login(c, 'admin')
    r = c.post(f'/admin/conversation/{VISA_KEY}/reassign', data={'target': 'eliza'}, headers={'Origin': ORIGIN})
    assert r.status_code == 200
    from app.integrations.panel.store import get_conversation_store
    assert asyncio.run(get_conversation_store().get(VISA_KEY)).assigned_to == 'eliza'


# --- CRM и бот на общем Redis: после перехвата из CRM бот молчит (ревью B1, находка 3) ---

def test_bot_turn_after_crm_takeover_stays_silent(crm, monkeypatch):
    import app.core.orchestrator as orch
    from app.channels.base import Message
    from app.core.orchestrator import Orchestrator

    class FakeFunnel:
        async def handle(self, msg, st):
            return f'bot:{msg.text}'
    monkeypatch.setattr(orch, 'get_funnel', lambda name: FakeFunnel())

    class Channel:
        name = 'whatsapp'

        def __init__(self):
            self.sent = []

        async def send(self, chat_id, text_, **kw):
            self.sent.append(text_)
            return 'bot-msg'
    channel = Channel()
    bot = settings.bots[0]
    o = Orchestrator(channel=channel, bot=bot)
    login(crm['client'], 'medina')
    crm['client'].post(f'/admin/conversation/{VISA_KEY}/takeover', headers={'Origin': ORIGIN})
    asyncio.run(o.handle(Message(channel='whatsapp', chat_id='996700000001@c.us',
                                 user_id='996700000001', text='а когда будет готово?')))
    assert channel.sent == []


def test_duplicate_retry_does_not_reintercept_released_dialog(crm):
    """Поздний повтор того же ключа после «Вернуть боту» не заглушает бота снова (ревью r2 #3)."""
    c = crm['client']
    login(c, 'medina')
    assert send(c, VISA_KEY, 'ответ', send_key='d' * 32).headers['X-Action-Outcome'] == 'sent'
    c.post(f'/admin/conversation/{VISA_KEY}/release', headers={'Origin': ORIGIN})
    assert asyncio.run(state.get_state_store().load(VISA_KEY)).intercepted is False
    assert send(c, VISA_KEY, 'ответ', send_key='d' * 32).headers['X-Action-Outcome'] == 'duplicate'
    assert asyncio.run(state.get_state_store().load(VISA_KEY)).intercepted is False
    assert len(crm['sent']) == 1
