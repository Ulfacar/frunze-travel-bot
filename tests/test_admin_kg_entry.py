"""KG interview HTTP -> real domain snapshots in isolated synthetic SQLite."""
import asyncio
from datetime import date
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

import app.admin.kg_entry as ui
import app.admin.router as ar
import app.main as main
from app.admin.kg_entry_form import values_from_request
from app.config import ManagerConfig, Settings
from app.domain.entry_storage import EntryStorageUnavailable, save_stay_history
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.models import EntryQualification, ServiceCase
from app.domain.permissions import Actor
from app.domain.qualification_storage import read_qualification, save_qualification
from app.knowledge.validation import load_document
from tests.test_admin_workday import _clear, _login, _make_domain_sm, _managers, _on, _seed_case
from tests.test_entry_storage import FIX

ADMIN=Actor('admin',True)


class Form(HTMLParser):
    """Read actual selected inputs/options; no hard-coded security tokens."""
    def __init__(self,html,form_id='kg-entry-form'):
        super().__init__(convert_charrefs=True)
        self.form_id=form_id;self.data={};self.current=None;self.textarea=None;self.nodes=[];self.active=False;self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.active=a.get('id')==self.form_id
        if not self.active:return
        self.nodes.append((tag,a));name=a.get('name')
        if tag=='input' and name and (a.get('type')!='checkbox' or 'checked' in a):
            self.data[name]=a.get('value','')
        if tag=='textarea' and name:self.textarea=name;self.data[name]=''
        if tag=='select' and name:self.current={'name':name,'multi':'multiple' in a,'all':[],'selected':[]}
        if tag=='option' and self.current is not None:
            value=a.get('value','');self.current['all'].append(value)
            if 'selected' in a:self.current['selected'].append(value)
    def handle_endtag(self,tag):
        if tag=='textarea':self.textarea=None
        if tag=='form':self.active=False
        if not self.active:return
        if tag=='select' and self.current is not None:
            s=self.current;values=s['selected'] or s['all'][:1]
            self.data[s['name']]=values if s['multi'] else values[0]
            self.current=None
    def handle_data(self,data):
        if self.active and self.textarea:self.data[self.textarea]+=data


@pytest.fixture
def env(monkeypatch,tmp_path):
    _clear();_managers(monkeypatch);_on(monkeypatch)
    ar.settings.managers.append(ManagerConfig(login='medina',name='Тестовый менеджер',password='frunze'))
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ar,'_bishkek_today',lambda:date(2026,10,9))
    sm=_make_domain_sm(tmp_path)
    monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:sm)
    cases={key:_seed_case(sm,owner='medina' if direction=='visa' else 'ademi',reference='SYN-'+key,direction=direction)['case_id']
           for key,direction in [('visa','visa'),('other','visa'),('tours','tours')]}
    async def seed():
        set_id=await create_kg_entry_set(sm.kw['bind'],actor=ADMIN)
        imported=await import_bundle(sm.kw['bind'],actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
        assert imported.accepted
        async with sm() as session:
            contacts={key:(await session.get(ServiceCase,cid)).contact_id for key,cid in cases.items()}
        return imported.version_id,contacts
    version,contacts=asyncio.run(seed())
    client=_login('admin')
    yield {'sm':sm,'engine':sm.kw['bind'],'cases':cases,'contacts':contacts,'version':version,'client':client,
           'url':f"/admin/case/{cases['visa']}/kg-entry"}
    client.close();asyncio.run(sm.kw['bind'].dispose());_clear()


def form_data(env, *, url=None, client=None):
    response=(client or env['client']).get(url or env['url'])
    assert response.status_code==200,response.text[-1000:]
    return Form(response.text).data


def post(env,data, *, url=None,client=None):
    return (client or env['client']).post(url or env['url'],data=data,follow_redirects=False)


def count(env):
    async def run():
        async with env['sm']() as session:return await session.scalar(select(func.count()).select_from(EntryQualification))
    return asyncio.run(run())


def saved(env, *, contact='visa',qid=None):
    return asyncio.run(read_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts'][contact],qualification_id=qid))


def complete_data(env):
    data=form_data(env)
    data.update(values_from_request(load_document(FIX/'synthetic_qualification_review.json')))
    return data


def test_case_link_get_read_only_and_labels(env):
    c=env['client']
    assert env['url'] in c.get(f"/admin/case/{env['cases']['visa']}").text
    page=c.get(env['url']);form=Form(page.text)
    assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert 'Анкета общая для визовых услуг' in page.text and count(env)==0
    controls=[a for tag,a in form.nodes if tag in ('input','select','textarea') and a.get('type')!='hidden']
    labels={a['for'] for tag,a in form.nodes if tag=='label' and 'for' in a}
    assert all(a.get('id') in labels or a.get('aria-label') for a in controls)
    assert {'_kg_signature','_kg_csrf','_kg_key'} <= form.data.keys()


def test_native_save_reload_old_version_and_idempotent_retry(env):
    first=form_data(env);first['language']='en'
    response=post(env,first)
    assert response.status_code==303 and response.headers['x-action-outcome']=='qualification_saved'
    page=env['client'].get(response.headers['location'])
    assert 'What citizenships do you hold?' in page.text and saved(env)['input']['profile']=={}
    assert Form(page.text).data['language']=='en'
    assert post(env,first).headers['location']==response.headers['location'] and count(env)==1
    second=complete_data(env);second['purpose']='work_hire'
    result=post(env,second);assert result.status_code==303
    assert saved(env)['revision']==2 and saved(env)['result']['status']=='manager_review'
    latest=env['client'].get(result.headers['location'])
    assert 'Цель связана с работой' in latest.text and 'Предыдущая версия' in latest.text
    old=env['client'].get(response.headers['location'])
    assert 'Предыдущая версия доступна для просмотра' in old.text
    assert not any(tag=='button' and a.get('type')=='submit' for tag,a in Form(old.text).nodes)
    assert saved(env)['result']['may_quote'] is False and count(env)==2


def test_unknown_false_and_location_change_are_preserved_correctly(env):
    data=complete_data(env);data['violations.overstay']='unknown'
    assert post(env,data).status_code==303
    data=form_data(env)
    assert data['violations.overstay']=='unknown'
    data.update({'violations.overstay':'false','current_location':'in_kg','current_basis_in_kg':'visa',
                 'current_visa_type':'TS','in_kg_since_state':'value','in_kg_since':'2026-10-01'})
    assert post(env,data).status_code==303
    data=form_data(env);data['current_location']='abroad'
    assert post(env,data).status_code==303
    p=saved(env)['input']['profile']
    assert p['violations']['overstay'] is False and 'current_visa_type' not in p and 'in_kg_since' not in p


@pytest.mark.parametrize('method',['get','post'])
@pytest.mark.parametrize('login',[None,'ademi','medina'])
def test_non_admin_denied_directly_before_domain(env,monkeypatch,method,login):
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    def forbidden():raise AssertionError('domain must not be accessed')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    try:assert getattr(client,method)(env['url']).status_code==(401 if login is None else 403)
    finally:client.close()


def test_off_gate_and_write_gate(env,monkeypatch):
    data=form_data(env)
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(env['url']).status_code==404 and post(env,data).status_code==404
    assert env['url'] not in env['client'].get(f"/admin/case/{env['cases']['visa']}").text
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    _on(monkeypatch,write=False)
    page=env['client'].get(env['url'])
    assert page.status_code==200 and 'Сохранение анкет отключено' in page.text
    assert post(env,data).status_code==403 and count(env)==0


def test_other_direction_and_foreign_qualification_do_not_open(env):
    data=form_data(env)
    tours=f"/admin/case/{env['cases']['tours']}/kg-entry"
    assert env['client'].get(tours).status_code==404 and post(env,data,url=tours).status_code==404
    assert post(env,data).status_code==303
    qid=saved(env)['qualification_id']
    other=f"/admin/case/{env['cases']['other']}/kg-entry"
    assert env['client'].get(other+f'?qualification_id={qid}').status_code==404
    assert post(env,form_data(env),url=other).status_code==403
    assert count(env)==1


@pytest.mark.parametrize('field',list(ui.META)+['_kg_signature','_kg_csrf'])
def test_signed_envelope_tampering_never_writes(env,field):
    data=form_data(env);data[field]='tampered'
    assert post(env,data).status_code==403 and count(env)==0


def test_csrf_cannot_cross_sessions(env):
    data=form_data(env);other=_login('admin')
    try:
        form_data(env,client=other)
        assert post(env,data,client=other).status_code==403 and count(env)==0
    finally:other.close()


@pytest.mark.parametrize('fault',['extra','duplicate','too_big','too_many','wrong_type','bad_utf8'])
def test_bounded_parser_rejects_untrusted_fields(env,fault):
    data=form_data(env);headers={'Content-Type':'application/x-www-form-urlencoded'}
    raw=urlencode(data,doseq=True)
    if fault=='extra':raw+='&contact_id=PRIVATE'
    elif fault=='duplicate':raw+='&_kg_key=PRIVATE'
    elif fault=='too_big':raw+='&private='+'X'*20_000
    elif fault=='too_many':raw+='&'+('&'.join('citizenship=RUS' for _ in range(75)))
    elif fault=='wrong_type':headers['Content-Type']='application/json'
    else:raw=raw.encode()+b'&private=\xff'
    response=env['client'].post(env['url'],content=raw,headers=headers)
    assert response.status_code in (413,415,422) and 'PRIVATE' not in response.text and count(env)==0


@pytest.mark.parametrize('fault',['dates','passport','unknown_citizenship','empty_date'])
def test_validation_keeps_form_values_without_false_success(env,fault):
    data=complete_data(env)
    if fault=='dates':data['exit_date']='2026-01-01'
    elif fault=='passport':data['entry_passport_country']='CHN'
    elif fault=='unknown_citizenship':data['citizenship']=['RUS','unknown']
    else:data['passport_expiry']=''
    response=post(env,data)
    assert response.status_code==422 and response.headers['x-action-outcome']=='invalid'
    assert Form(response.text).data['_kg_key']==data['_kg_key'] and count(env)==0


def test_stale_tabs_conflict_and_keep_the_second_interview(env):
    first=form_data(env);second=form_data(env);second['purpose']='study'
    assert post(env,first).status_code==303
    response=post(env,second)
    assert response.status_code==409 and 'другой вкладке' in response.text
    assert Form(response.text).data['purpose']=='study' and count(env)==1
    assert post(env,first).status_code==303 and count(env)==1


def test_validation_echo_is_html_escaped(env):
    data=complete_data(env);payload='\"><script>window.syntheticAttack=1</script>'
    data['passport_expiry']=payload
    response=post(env,data)
    assert response.status_code==422 and payload not in response.text
    assert '&lt;script&gt;' in response.text and count(env)==0


def test_off_gate_does_not_touch_domain(env,monkeypatch):
    data=form_data(env)
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    def forbidden():raise AssertionError('domain accessed while flag is OFF')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    assert env['client'].get(env['url']).status_code==404 and post(env,data).status_code==404


def test_incomplete_outdated_history_is_shown_as_needing_verification(env):
    history={'format':'kg-stay-history/1','as_of':'2026-10-01','history_complete':None,'intervals':[]}
    asyncio.run(save_stay_history(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],expected_revision=0,
                                 request_key='synthetic-history',document=history))
    response=post(env,complete_data(env));assert response.status_code==303
    page=env['client'].get(response.headers['location'])
    assert 'Полнота истории поездок не подтверждена.' in page.text
    assert 'История поездок составлена на другую дату' in page.text


def test_old_report_date_is_separate_from_new_review_date(env):
    req=load_document(FIX/'synthetic_qualification_review.json');req['as_of']='2026-10-01'
    asyncio.run(save_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],expected_revision=0,
        request_key='old-date',knowledge_version_id=env['version'],request=req))
    page=env['client'].get(env['url'])
    assert 'Проверка на дату 2026-10-01' in page.text
    assert 'Новая проверка будет выполнена на дату 2026-10-09' in page.text
    assert post(env,Form(page.text).data).status_code==303
    assert saved(env)['input']['as_of']=='2026-10-09'


def test_existing_condition_facts_are_preserved_from_server_base_then_explicitly_removed(env):
    req=load_document(FIX/'synthetic_qualification_review.json')
    req['condition_facts']={'schema_version':'kg-entry-condition-facts/1','foreign_visas':{'items':[],'complete':True}}
    asyncio.run(save_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],expected_revision=0,
        request_key='seed',knowledge_version_id=env['version'],request=req))
    data=form_data(env);data['purpose']='study'
    assert post(env,data).status_code==303
    assert saved(env)['input']['condition_facts']==req['condition_facts']
    data=form_data(env);data['clear_conditions']='yes'
    assert post(env,data).status_code==303 and 'condition_facts' not in saved(env)['input']


def test_lost_commit_reply_is_retryable_without_duplicate(env):
    data=complete_data(env);fired=False
    def lost_ack(session):
        nonlocal fired
        if not fired:
            fired=True;raise RuntimeError('PRIVATE-ACK')
    event.listen(Session,'after_commit',lost_ack)
    try:response=post(env,data)
    finally:event.remove(Session,'after_commit',lost_ack)
    assert fired and response.status_code==503 and 'PRIVATE' not in response.text
    assert count(env)==1
    echoed=Form(response.text).data
    assert echoed['_kg_key']==data['_kg_key']
    assert post(env,echoed).status_code==303 and count(env)==1


def test_save_and_reload_failure_still_leaves_retryable_form(env,monkeypatch):
    data=complete_data(env)
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('PRIVATE')
    with monkeypatch.context() as patch:
        patch.setattr(ui,'save_qualification',unavailable);patch.setattr(ui,'_context',unavailable)
        response=post(env,data)
    assert response.status_code==503 and 'PRIVATE' not in response.text
    form=Form(response.text)
    assert any(tag=='button' and a.get('type')=='submit' and 'disabled' not in a for tag,a in form.nodes)
    assert form.data['citizenship']==['RUS'] and form.data['_kg_key']==data['_kg_key']
    assert post(env,form.data).status_code==303 and count(env)==1


@pytest.mark.parametrize('fault',['missing','corrupt'])
def test_missing_or_corrupt_knowledge_never_creates_qualification(env,fault):
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text('DELETE FROM knowledge_imports' if fault=='missing' else "UPDATE knowledge_versions SET bundle_hash=:bad"),{'bad':'0'*64})
    asyncio.run(corrupt())
    page=env['client'].get(env['url'])
    assert page.status_code==(200 if fault=='missing' else 503)
    assert 'База знаний ещё не загружена' in page.text if fault=='missing' else 'временно недоступна' in page.text
    assert count(env)==0


def test_flag_default_and_compose_forwarding():
    from pathlib import Path
    assert Settings.model_fields['admin_kg_entry_enabled'].default is False
    compose=Path('docker-compose.yml').read_text(encoding='utf-8')
    assert 'ADMIN_KG_ENTRY_ENABLED: ${ADMIN_KG_ENTRY_ENABLED:-false}' in compose
