"""Independent native signed-envelope compatibility at valid recipe bounds."""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException,Request
from app.admin import kg_specialist as ui
from app.domain.entry_storage import EntryStorageInvalid,_hash
from app.domain.permissions import Actor
from app.domain.specialist_policy import SpecialistPolicy
from tests.test_admin_kg_specialist import configure,url,fields
from tests.test_specialist_decisions import env,admins,clock,enforce_sqlite_foreign_keys,setup,read,record,quote_policy
from tests.test_quote_rules import recipe,line,na


def test_valid_32_line_recipe_native_preview_signed_save_and_exact_retry(env,tmp_path,monkeypatch):
    setup(env,tmp_path,language='ru')
    r=recipe(id='SYN-B');r['lines'][2]=na('bank')
    for i in range(28):
        r['lines'].append(line('government',id='FEE-'+str(i),title_ru='Ж'*180,title_en='E'*180,
            reference='R'*80,urgent_reference='U'*80,reason='Ж'*180))
    env['quote_policy']=quote_policy(r)
    p=env['policy'].document();p['capabilities'][0]['quote_policy_hash']=env['quote_policy'].digest
    p['capabilities'][0]['recipes'][0]['hash']=_hash(r);env['policy']=SpecialistPolicy(p)
    configure(env,monkeypatch);record(env)
    path=url(env,'ru');page=env['client'].get(path)
    prepared=env['client'].post(path,data=fields(page,'preview'),follow_redirects=False)
    assert prepared.status_code==200
    save=fields(prepared,'save');operation=json.loads(save['_sp_payload'])
    assert len(operation['preview']['quote']['result']['lines'])==32
    body=urlencode(save).encode();assert len(save['_sp_payload'])>24000 and len(body)>65536
    assert read(env)['revision']==1
    for attempt in range(2):
        response=env['client'].post(path,content=body,headers={'Content-Type':'application/x-www-form-urlencoded'},follow_redirects=False)
        assert response.status_code==303,response.text[-1000:]
        assert read(env)['revision']==2
    receipt=read(env)['history'][-1] if read(env)['history'][-1]['action']=='quote' else read(env)['history'][0]
    assert receipt['action']=='quote'
    assert receipt['command']['operation']==operation
    Path('runs/reviewer-native-bounds.json').write_text(json.dumps(dict(recipe_bytes=len(json.dumps(r,ensure_ascii=False).encode()),
        payload_characters=len(save['_sp_payload']),payload_utf8_bytes=len(save['_sp_payload'].encode()),form_bytes=len(body),
        lines=32,journal_revisions=2,duplicate_quote_created=False)),encoding='utf8')


def test_stream_cap_and_oversize_payload_are_bounded_before_signature_or_offer():
    scope={'type':'http','method':'POST','path':'/','query_string':b'',
        'headers':[(b'content-type',b'application/x-www-form-urlencoded')],'session':{'kg_specialist_csrf':'a'*64}}
    chunks=iter([b'x'*ui.BODY_LIMIT,b'x',b'not-consumed'])
    calls=[]
    async def receive():
        calls.append(1)
        return {'type':'http.request','body':next(chunks),'more_body':True}
    with pytest.raises(HTTPException) as error:
        asyncio.run(ui._form(Request(scope,receive),Actor('admin',True),(1,1,1),'en'))
    assert error.value.status_code==422 and len(calls)==2
    with pytest.raises(EntryStorageInvalid,match='specialist_form_size_limit'):
        ui._envelope(Request(scope),Actor('admin',True),(1,1,1),'en','save',1,{'x':'Ж'*(ui.PAYLOAD_LIMIT//2)})
