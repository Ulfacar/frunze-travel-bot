import asyncio
from urllib.parse import quote

import pytest
from sqlalchemy import select

import app.admin.precontract as ui
import app.admin.router as ar
from app.domain.models import Product,ServiceCase,ServiceCaseOpening
from tests.test_admin_contracts import env as contract_env,Rendered,snapshot
from tests.test_admin_workday import _login


@pytest.fixture
def env(contract_env,monkeypatch):
    sm,conv,ids,old_client=contract_env
    conv.funnel='visa';conv.assigned_to='medina'
    client=_login('admin')
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    yield dict(sm=sm,conv=conv,ids=ids,client=client,url=f'/admin/conversation/{quote(conv.user_id,safe="")}/preliminary')
    client.close()


def inputs(response):
    assert response.status_code==200,response.text[-800:]
    return {n['attrs']['name']:n['attrs'].get('value','') for n in Rendered(response.text).by_attr('name') if n['tag']=='input'}


def open_data(env):
    data=inputs(env['client'].get(env['url']))
    async def version():
        async with env['sm']() as s:return (await s.get(Product,env['ids']['visa'])).current_version_id
    data['product_choice']=f"{env['ids']['visa']}:{asyncio.run(version())}"
    return data


def signed_data(env,url):
    data=inputs(env['client'].get(url));data.update(reference='SYN-CONTRACT',signed_at='2026-10-13T14:00',
        amount='100.50',currency='KGS',amount_unknown_reason='',confirmed='yes')
    return data


def test_real_native_unsigned_case_readonly_get_and_same_case_signature_with_retries(env):
    client=env['client'];before=snapshot(env['sm']);data=open_data(env)
    assert snapshot(env['sm'])==before
    response=client.post(env['url'],data=data,follow_redirects=False)
    assert response.status_code==303,response.text
    card=response.headers['location'];case_id=int(card.rsplit('/',1)[1]);sign_url=card+'/contract'
    page=client.get(card);assert page.status_code==200 and sign_url in page.text
    assert f'{card}/kg-entry' in page.text and client.get(f'{card}/kg-entry').status_code==200
    original=snapshot(env['sm']);assert len(original['service_cases'])==1 and not original['calendar_tasks']
    assert original['service_cases'][0]._mapping['signed_at'] is None
    sig=signed_data(env,sign_url)
    saved=client.post(sign_url,data=sig,follow_redirects=False)
    assert saved.status_code==303 and saved.headers['location']==card,saved.text
    after=snapshot(env['sm'])
    assert len(after['service_cases'])==1 and len(after['calendar_tasks'])==1
    assert after['service_cases'][0]._mapping['id']==case_id
    assert not after['service_payments']
    for url,values in ((env['url'],data),(sign_url,sig)):
        retry=client.post(url,data=values,follow_redirects=False)
        assert retry.status_code==303 and retry.headers['location']==card,retry.text
    assert snapshot(env['sm'])==after


@pytest.mark.parametrize('field,value',[('original_owner','aisina'),('request_key','a'*48),('csrf_token','bad'),('signature','bad')])
def test_forged_open_envelope_is_rejected_without_creation(env,field,value):
    data=open_data(env);data[field]=value
    assert env['client'].post(env['url'],data=data).status_code==403
    assert not snapshot(env['sm'])['service_cases']


def test_signature_target_peer_and_unsigned_confirmation_are_server_checked(env):
    data=open_data(env);created=env['client'].post(env['url'],data=data,follow_redirects=False)
    url=created.headers['location']+'/contract';sig=signed_data(env,url)
    assert _login('aisina').get(url).status_code==404
    changed=url.replace('/case/1/','/case/999/')
    assert env['client'].post(changed,data=sig).status_code==403
    sig['confirmed']=''
    response=env['client'].post(url,data=sig)
    assert response.status_code==422 and sig['request_key'] in response.text
    assert snapshot(env['sm'])['service_cases'][0]._mapping['signed_at'] is None


def test_lost_signature_ack_keeps_exact_form_for_retry(env,monkeypatch):
    from sqlalchemy.exc import OperationalError
    data=open_data(env);created=env['client'].post(env['url'],data=data,follow_redirects=False)
    url=created.headers['location']+'/contract';sig=signed_data(env,url)
    original=ui.service.record_signed_contract
    async def unknown(session,**kw):
        await original(session,**kw)
        await session.commit()
        raise OperationalError('SYN',{},RuntimeError('synthetic lost response'))
    with monkeypatch.context() as patch:
        patch.setattr(ui.service,'record_signed_contract',unknown)
        response=env['client'].post(url,data=sig)
        assert response.status_code==503 and sig['request_key'] in response.text
    before=snapshot(env['sm'])
    response=env['client'].post(url,data=sig,follow_redirects=False)
    assert response.status_code==303 and snapshot(env['sm'])==before


@pytest.mark.parametrize('operation',['open','sign'])
def test_failed_get_is_controlled_and_does_not_claim_saved_state(env,monkeypatch,operation):
    from sqlalchemy.exc import OperationalError
    url=env['url']
    if operation=='sign':
        result=env['client'].post(url,data=open_data(env),follow_redirects=False)
        url=result.headers['location']+'/contract'
    before=snapshot(env['sm'])
    def unavailable():raise OperationalError('SYN',{},RuntimeError('synthetic unavailable registry'))
    with monkeypatch.context() as patch:
        patch.setattr(ar,'_domain_sessionmaker',unavailable)
        response=env['client'].get(url)
        assert response.status_code==503 and 'Реестр временно недоступен' in response.text
        assert response.headers['cache-control']=='no-store'
    assert snapshot(env['sm'])==before


def test_native_own_applicant_intake_and_internal_quote_survive_same_case_signature(env,monkeypatch):
    from app.admin.kg_entry_form import values_from_request
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    from app.domain import entry_applications,applicant_profiles,entry_quotes
    from app.domain.models import EntryApplicant,EntryApplication,EntryQuoteRevision,EntryApplicantProfile
    from tests.test_admin_kg_entry import ADMIN,FIX,Form
    from tests import test_admin_kg_applications as applications_ui
    from tests import test_admin_kg_applicant_profiles as profiles_ui
    from tests import test_admin_kg_quotes as quotes_ui
    from tests.test_applicant_profiles import request
    from tests.test_entry_quotes import policy
    monkeypatch.setattr(ar.settings,'admin_user','admin')
    monkeypatch.setattr(ar.settings,'kg_quote_policy',policy().document())
    engine=env['sm'].kw['bind']
    async def knowledge():
        sid=await create_kg_entry_set(engine,actor=ADMIN)
        imported=await import_bundle(engine,actor=ADMIN,set_id=sid,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
        assert imported.accepted
    asyncio.run(knowledge())
    client=env['client'];opening=open_data(env)
    response=client.post(env['url'],data=opening,follow_redirects=False)
    assert response.status_code==303
    card=response.headers['location'];cid=int(card.rsplit('/',1)[1])
    own=env|{'engine':engine,'cases':{'visa':cid},'url':card+'/kg-entry'}
    app=applications_ui.create(own)  # real no-JS applicant and application forms
    application=asyncio.run(entry_applications.read_application(engine,actor=ADMIN,case_id=cid,application_id=app['id']))
    person_id=application['applicant_id']
    profile_url=profiles_ui.ui._url(cid,person_id)
    form=profiles_ui.values(own,profile_url);form.update(values_from_request(request()))
    result=client.post(profile_url,data=form,follow_redirects=False)
    assert result.status_code==303,result.text[-1000:]
    restored=Form(client.get(result.headers['location']).text).data
    assert restored['purpose']==form['purpose']
    profile=asyncio.run(applicant_profiles.read_applicant_profile(engine,actor=ADMIN,case_id=cid,applicant_id=person_id))
    assert profile['saved']['result']['applicant_id']==person_id
    assert not profile['saved']['result']['may_quote']  # intake is not legal clearance
    quoted=quotes_ui.save_form(own,app)
    assert quotes_ui.post(own,app,quoted).status_code==303
    before=asyncio.run(entry_quotes.read_quotes(engine,actor=ADMIN,case_id=cid,application_id=app['id'],policy=policy()))
    receipt=before['history'][0]['receipt']
    assert receipt['applicant_id']==person_id and receipt['result']['payment']=='not_created'
    assert receipt['result']['legal_eligibility']=='not_assessed'
    sig=signed_data(env,card+'/contract')
    result=client.post(card+'/contract',data=sig,follow_redirects=False)
    assert result.status_code==303 and result.headers['location']==card
    assert asyncio.run(entry_quotes.read_quotes(engine,actor=ADMIN,case_id=cid,application_id=app['id'],policy=policy()))==before
    assert asyncio.run(applicant_profiles.read_applicant_profile(engine,actor=ADMIN,case_id=cid,applicant_id=person_id))==profile
    async def identities():
        async with env['sm']() as s:
            return {m.__tablename__:list(await s.scalars(select(m.id))) for m in
                (ServiceCase,EntryApplicant,EntryApplication,EntryApplicantProfile,EntryQuoteRevision)}
    assert asyncio.run(identities())=={'service_cases':[cid],'entry_applicants':[person_id],
        'entry_applications':[app['id']],'entry_applicant_profiles':[1],'entry_quote_revisions':[1]}
    assert not snapshot(env['sm'])['service_payments']
