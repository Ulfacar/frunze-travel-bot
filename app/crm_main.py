"""Dedicated authenticated CRM; no bot lifespan, webhooks or provider workers."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.engine import make_url
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.staticfiles import StaticFiles

from app.config import settings

COOKIE = '__Host-frunze_crm'
SCHEMA = 'e6_sop_review_evidence_0043'
NATIVE_MODULES = frozenset({
    'contracts', 'precontract', 'workday', 'kg_actual_dates', 'kg_answers',
    'kg_applicant_history', 'kg_applicant_profiles', 'kg_applications',
    'kg_approved_qualification', 'kg_assessment', 'kg_deadline_tasks',
    'kg_deadlines', 'kg_document_inventory', 'kg_document_packages',
    'kg_document_quarantine', 'kg_documents', 'kg_entry', 'kg_history',
    'kg_interviews', 'kg_issued', 'kg_knowledge', 'kg_knowledge_decisions',
    'kg_knowledge_publication', 'kg_notifications', 'kg_portal',
    'kg_process_journal', 'kg_processes', 'kg_quotes', 'kg_review_card',
    'kg_sop_reviews', 'kg_specialist', 'kg_templates', 'kg_work_review',
})
ROUTER_POSTS = frozenset({'login_submit', 'logout', 'set_direction',
    'task_create', 'task_complete', 'task_cancel', 'task_reschedule',
    'calendar_task_quick_create', 'calendar_task_complete', 'calendar_task_cancel',
    'calendar_task_snooze', 'calendar_task_reschedule'})


def validate_configuration(*, test_sqlite=False):
    """Reject bot/runtime defaults before importing or serving native handlers."""
    if not settings.crm_standalone_enabled:
        raise RuntimeError('Dedicated CRM mode must be explicitly enabled')
    origin = urlsplit(settings.crm_public_origin)
    if (origin.scheme != 'https' or not origin.hostname or origin.username or
            origin.password or origin.path or origin.query or origin.fragment or
            origin.port not in (None, 443)):
        raise RuntimeError('CRM_PUBLIC_ORIGIN must be a canonical HTTPS origin')
    if settings.crm_public_origin != f'https://{origin.hostname}':
        raise RuntimeError('CRM_PUBLIC_ORIGIN must be canonical')
    if not settings.session_https_only or len(settings.session_secret) < 48:
        raise RuntimeError('CRM requires secure sessions and an independent strong secret')
    if settings.session_secret == 'change-me-frunze-session-secret' or settings.demo_login:
        raise RuntimeError('Demo authentication is forbidden in the dedicated CRM')
    if (not settings.admin_enabled or settings.panel_backend != 'postgres' or
            settings.crm_backend != 'postgres' or settings.state_backend != 'memory' or
            not settings.authz_enforce_enabled):
        raise RuntimeError('CRM requires persistent isolated storage and access enforcement')
    if not settings.managers:
        raise RuntimeError('CRM requires explicit named accounts with explicit roles')
    names = set()
    for account in settings.managers:
        if (not re.fullmatch(r'[a-z][a-z0-9_]{2,63}', account.login) or
                account.login in names or len(account.password.strip()) < 20 or
                account.password != account.password.strip() or account.telegram_chat_id):
            raise RuntimeError('Invalid CRM account configuration')
        names.add(account.login)
    if not any(account.admin for account in settings.managers):
        raise RuntimeError('CRM requires an explicitly configured administrator')
    if settings.bots or settings.telegram_bots:
        raise RuntimeError('Channel registrations are forbidden in the dedicated CRM')
    for name in ('wappi_token', 'telegram_bot_token', 'openrouter_api_key',
                 'anthropic_api_key', 'stt_api_key', 'bitrix24_webhook_url',
                 'managers_telegram_bot_token', 'managers_telegram_chat_id'):
        if getattr(settings, name, ''):
            raise RuntimeError('Provider credentials are forbidden in the dedicated CRM')
    url = make_url(settings.database_url)
    if test_sqlite and url.drivername == 'sqlite+aiosqlite':
        return origin.hostname
    if (url.drivername != 'postgresql+asyncpg' or url.host != 'db' or
            url.database != settings.crm_database_name or url.username != 'frunze_crm' or
            url.database != 'frunze_crm' or len(url.password or '') < 32):
        raise RuntimeError('CRM must use its dedicated database and role')
    if os.name != 'posix' or os.getuid() != 10001:
        raise RuntimeError('Dedicated CRM requires its non-root Linux image')
    status = dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if (status.get('NoNewPrivs','').strip() != '1' or status.get('Seccomp','').strip() != '2' or
            int(status.get('CapEff','1').strip(),16) != 0 or int(status.get('CapBnd','1').strip(),16) != 0):
        raise RuntimeError('CRM container kernel restrictions are missing')
    return origin.hostname


def principal_binding(account):
    payload = json.dumps([account.login, account.name, account.password, account.admin],
                         ensure_ascii=False, separators=(',', ':')).encode()
    return hmac.new(settings.session_secret.encode(), b'crm-principal/1\0'+payload,
                    hashlib.sha256).hexdigest()


class CrmBoundary:
    """A fail-closed boundary outside every native handler, including old forms."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        session = scope['session']
        current = session.get('manager')
        account = next((m for m in settings.managers if isinstance(current, dict)
                        and current.get('login') == m.login), None)
        if (account is None or not hmac.compare_digest(
                str(session.get('crm_principal', '')).encode(),
                principal_binding(account).encode())):
            session.clear()
            account = None
        else:
            session['manager'] = dict(login=account.login, name=account.name or account.login,
                                      admin=account.admin)
        path, method = scope['path'], scope['method']
        public = path in ('/', '/health', '/admin/login') or path.startswith('/crm-static/')
        if not public and account is None:
            response = (RedirectResponse('/admin/login?next=/admin/work', status_code=303)
                        if method in ('GET', 'HEAD') else JSONResponse({'detail':'login required'},401))
            return await response(scope, receive, send)
        if method not in ('GET', 'HEAD', 'OPTIONS'):
            if (request.headers.get('origin') != settings.crm_public_origin or
                    request.headers.get('sec-fetch-site') == 'cross-site'):
                return await JSONResponse({'detail':'same-origin form required'},403)(scope,receive,send)
            limit = 32768 if path == '/admin/login' else 18 * 1024 * 1024
            body_buffer = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                if len(body_buffer) + len(chunk) > limit:
                    return await JSONResponse({'detail':'request too large'},413)(scope,receive,send)
                body_buffer.extend(chunk)
                if not message.get('more_body', False):
                    break
            delivered = False
            async def bounded_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type':'http.request','body':bytes(body_buffer),'more_body':False}
                return await receive()
            receiver = bounded_receive
        else:
            receiver = receive

        async def protected_send(message):
            if message['type'] == 'http.response.start':
                if path == '/admin/login' and method == 'POST' and message['status'] == 303:
                    signed = session.get('manager', {})
                    actor = next((m for m in settings.managers if m.login == signed.get('login')), None)
                    if actor is not None:
                        session['crm_principal'] = principal_binding(actor)
                headers = list(message.get('headers', []))
                headers.extend([(b'cache-control',b'no-store'),(b'x-content-type-options',b'nosniff'),
                    (b'x-frame-options',b'DENY'),(b'referrer-policy',b'same-origin'),
                    (b'content-security-policy', b"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")])
                message = {**message,'headers':headers}
            await send(message)
        await self.app(scope, receiver, protected_send)


def create_app(*, test_sqlite=False):
    host = validate_configuration(test_sqlite=test_sqlite)
    from app.admin import router as admin
    from app.integrations.crm.db import get_sessionmaker

    @asynccontextmanager
    async def lifespan(app):
        # Read-only readiness. Schema/bootstrap is an explicit separate command.
        async with get_sessionmaker()() as session:
            version = await session.scalar(text('SELECT version_num FROM alembic_version'))
            if version != SCHEMA:
                raise RuntimeError('Dedicated CRM schema is not current')
            from app.crm_intake import CrmBootstrap
            marker = await session.get(CrmBootstrap, 'standalone-v1')
            if (marker is None or marker.state != 'ready' or marker.source_sha256 !=
                    '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'):
                raise RuntimeError('Dedicated CRM bootstrap is incomplete')
            await session.execute(text('SELECT id FROM conversations LIMIT 1'))
        yield

    app = FastAPI(title='Frunze CRM', docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    for route in admin.router.routes:
        endpoint = getattr(route, 'endpoint', None)
        module = getattr(endpoint, '__module__', '').removeprefix('app.admin.')
        methods = getattr(route, 'methods', set())
        if (methods <= {'GET','HEAD'} or module in NATIVE_MODULES or
                (module == 'router' and getattr(endpoint,'__name__','') in ROUTER_POSTS)):
            if getattr(route,'path','') not in ('/admin/login/demo','/admin/system','/admin/cards'):
                app.router.routes.append(route)

    @app.get('/')
    async def root():
        return RedirectResponse('/admin/work',303)

    @app.get('/health')
    async def health():
        try:
            async with get_sessionmaker()() as session:
                await session.execute(text('SELECT 1'))
            return {'status':'ok','service':'frunze-crm','revision':settings.crm_release_revision}
        except Exception:
            return JSONResponse({'status':'unavailable'},503)

    from app.crm_intake import router as intake_router
    app.include_router(intake_router)
    app.mount('/crm-static',StaticFiles(directory=Path(__file__).parent/'admin'/'static'),name='crm-static')
    app.add_middleware(CrmBoundary)
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret,
                       session_cookie=COOKIE,max_age=8*3600,https_only=True,same_site='lax')
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[host,'127.0.0.1','localhost'])
    return app
