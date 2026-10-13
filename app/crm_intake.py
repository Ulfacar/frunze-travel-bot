"""Explicit manual intake for the separate CRM; no invented incoming message."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import DateTime, ForeignKey, Integer, String, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Mapped, mapped_column

from app.admin import router as ar
from app.admin.contracts import _csrf
from app.core.live_authz import actor_for
from app.domain.models import DomainError
from app.domain.phones import normalize_phone
from app.integrations.crm.db import Base, Conversation, AuditLog, get_sessionmaker


class CrmIntakeReceipt(Base):
    """Dedicated CRM legacy schema, created only by its explicit fresh bootstrap."""
    __tablename__ = 'crm_intake_receipts'
    request_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('conversations.id'), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrmBootstrap(Base):
    __tablename__ = 'crm_bootstrap'
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)


router = APIRouter(dependencies=[Depends(ar._load_new_look)])


def signature(request, actor, key):
    data = json.dumps(['crm-intake/1',actor,key,_csrf(request)],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),data,hashlib.sha256).hexdigest()


def values(request, actor):
    key = secrets.token_hex(24)
    return dict(request_key=key,signature=signature(request,actor,key),
                csrf_token=_csrf(request),name='',phone='')


def permitted(manager):
    actor = actor_for(manager)
    if not actor.is_full_admin and 'visa' not in actor.allowed_directions:
        raise HTTPException(403)
    return actor


def render(request, manager, form, error='', status=200):
    return ar.templates.TemplateResponse(request,'crm_intake.html',
        dict(manager=manager,values=form,error=error),status_code=status,
        headers={'Cache-Control':'no-store'})


@router.get('/admin/intake')
async def intake_form(request:Request,manager=Depends(ar.require_admin)):
    actor = permitted(manager)
    return render(request,manager,values(request,actor.manager_id))


@router.post('/admin/intake')
async def intake_submit(request:Request,manager=Depends(ar.require_admin)):
    actor = permitted(manager)
    if len(await request.body()) > 8192:
        raise HTTPException(413)
    submitted = await request.form()
    fields = {'request_key','signature','csrf_token','name','phone'}
    if set(submitted) != fields or any(len(submitted.getlist(k)) != 1 for k in fields):
        raise HTTPException(422)
    form = {k:str(submitted[k]) for k in fields}
    if any(len(v)>255 for v in form.values()):
        raise HTTPException(422)
    if (not re.fullmatch('[0-9a-f]{48}',form['request_key']) or
        not hmac.compare_digest(_csrf(request).encode(),form['csrf_token'].encode()) or
        not hmac.compare_digest(signature(request,actor.manager_id,form['request_key']).encode(),form['signature'].encode())):
        raise HTTPException(403)
    name = form['name'].strip()
    if not 1 <= len(name) <= 120 or any(ord(c)<32 for c in name):
        return render(request,manager,form,'Укажите имя длиной до 120 символов.',422)
    try:
        raw_phone = form['phone'].strip()
        if not re.fullmatch(r'\+[1-9][0-9 ()-]{7,30}', raw_phone):
            raise DomainError('explicit international phone required')
        phone = normalize_phone(raw_phone)
    except DomainError:
        return render(request,manager,form,'Укажите международный номер с кодом страны.',422)
    user_id = 'manual_visa:'+phone
    payload = json.dumps([actor.manager_id,name,phone,'visa'],ensure_ascii=False,separators=(',',':')).encode()
    digest = hashlib.sha256(payload).hexdigest()
    sm = get_sessionmaker()
    for attempt in range(2):
        try:
            async with sm() as session, session.begin():
                if session.bind.dialect.name == 'postgresql':
                    lock = int.from_bytes(hashlib.sha256(('crm-intake:'+form['request_key']).encode()).digest()[:8],'big',signed=True)
                    await session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':lock})
                receipt = await session.get(CrmIntakeReceipt,form['request_key'])
                if receipt:
                    if receipt.actor != actor.manager_id or receipt.payload_hash != digest:
                        raise HTTPException(409,'Эта форма уже сохранена с другими данными.')
                    conversation = await session.get(Conversation,receipt.conversation_id)
                    if not conversation or not ar._can_view_conversation(conversation,manager):
                        raise HTTPException(404)
                    if (conversation.user_id != user_id or conversation.phone != phone or
                            conversation.channel != 'manual' or conversation.bot_id != 'manual_visa' or
                            conversation.funnel != 'visa'):
                        raise HTTPException(409,'Ссылка сохранения не соответствует этому обращению.')
                else:
                    conversation = await session.scalar(select(Conversation).where(Conversation.user_id==user_id).with_for_update())
                    if conversation is not None:
                        if (conversation.channel != 'manual' or conversation.bot_id != 'manual_visa' or
                            conversation.phone != phone or conversation.funnel != 'visa' or
                            not ar._can_view_conversation(conversation,manager)):
                            raise HTTPException(409,'Номер уже учтён; обратитесь к администратору.')
                    else:
                        conversation = Conversation(user_id=user_id,phone=phone,channel='manual',
                            bot_id='manual_visa',funnel='visa',stage='greeting',intercepted=True,
                            assigned_to=actor.manager_id,assigned_at=datetime.now(timezone.utc),
                            qualification={'name':name},source='manual',last_text='',last_sender='')
                        session.add(conversation)
                        await session.flush()
                    session.add(CrmIntakeReceipt(request_key=form['request_key'],actor=actor.manager_id,
                        payload_hash=digest,conversation_id=conversation.id,created_at=datetime.now(timezone.utc)))
                    session.add(AuditLog(manager=actor.manager_id,action='manual_intake',user_id=user_id,
                        detail='Manual intake recorded; no channel message or consent'))
                target = conversation.user_id
            return RedirectResponse('/admin/conversation/'+quote(target,safe='')+'/preliminary',303)
        except IntegrityError:
            if attempt:
                return render(request,manager,form,'Запись изменилась. Повторите эту же форму.',409)
        except SQLAlchemyError:
            return render(request,manager,form,
                'Реестр временно недоступен. Повторите эту же форму для проверки сохранения.',503)

