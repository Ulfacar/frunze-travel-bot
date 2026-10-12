"""One cached history verification must retain each receipt's own source prefix."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone

from app.config import settings
from app.domain import conditional_deadlines as service,conditional_deadline_sources as sources,entry_anchors,entry_deadlines,applicant_profiles
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,write,actual


def test_two_source_prefixes_replay_exactly_with_one_fresh_cache(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    rule='KG.DL.REGISTRATION_EXTENSION';allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    first,first_request=write(env,args)
    at=datetime(2026,10,13,10,tzinfo=timezone.utc)+timedelta(seconds=1)
    for module in (service,sources,entry_anchors,applicant_profiles):
        monkeypatch.setattr(module,'_now',lambda:at)
    doc=deepcopy(prepared[2]['input'])
    doc['profile']['passport_pages_ok']=False
    newer=actual.profiles.save(env,prepared[0],doc=doc,revision=prepared[2]['revision'],key='NEW-REVIEW-PROFILE')
    prepared=(prepared[0],prepared[1],newer)
    changed=actual.args(env,prepared)
    changed['operation']['data']['value']['valid_until']='2026-11-02'
    actual.write(env,changed)
    second,second_request=write(env,args,key='SECOND-CACHED')
    assert first['snapshot']['report']['profile']!=second['snapshot']['report']['profile']
    assert first['snapshot']['report']['anchors']!=second['snapshot']['report']['anchors']
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    read_args={k:v for k,v in args.items() if k not in ('applicant_id','authority')}
    for old,request,revision in [(first,first_request,1),(second,second_request,2)]:
        assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==old
        result=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**read_args,revision=revision,replay=True))
        assert result['selected']['snapshot']==old['snapshot']
        assert result['conditional_current']['review_due_on']==(None if revision==1 else '2026-11-02')
