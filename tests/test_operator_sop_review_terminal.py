"""Successful terminal exceptions still bind the current own application attempt."""
import asyncio
import pytest
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env,ADMIN
from tests.test_entry_applications import enforce_sqlite_foreign_keys, record, application
from tests import test_operator_sop_reviews as core, test_entry_processes as process, test_entry_issued as issued
from tests.test_entry_process_dependencies import regularization_at_u06


def test_u09_approved_own_attempt_ignores_unrelated_new_root(env,tmp_path):
    core.connected.source(env,tmp_path,source_file=core.ROOT/'runs/specialist-source.pdf')
    root,child,allowed,_=regularization_at_u06(env,'exit_visa','exit_visa','L')
    record(env,child,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{child['id']:06}")
    issued.file(env,child);issued.review(env,child)
    process.transition(env,root,'U07',package_policy=allowed)
    issued.write(env,child,'travel',dict(direction='exit',on='2026-09-05',proof='7'*64,source='official_record',passport_fingerprint='b'*64))
    process.transition(env,root,'U08',package_policy=allowed)
    process.attest(env,root,'completion_reviewed',role='exit_visa')
    process.transition(env,root,'U09',package_policy=allowed)
    authority=core.authority(env,core.rules.PREFIX+'ENTRY_BAN_REVIEW',package=allowed)
    args=dict(actor=ADMIN,case_id=root['case_id'],applicant_id=root['applicant_id'],application_id=root['id'],
        rule_unit_id=authority.policy.document['rule_id'],authority=authority)
    assert core.preview(env,args)['report']['status']=='available'
    saved,request=core.write(env,args)
    with pytest.raises(EntryStorageInvalid,match='invalid_application_transition'):
        record(env,child,'close',status='closed',source='client_request',reference=None,occurred_on='2026-10-13')
    with pytest.raises(EntryStorageInvalid):
        application(env,{'id':root['applicant_id']},'FOLLOWING-EXIT-ATTEMPT',procedure='exit_visa',previous=child['id'])
    later=application(env,{'id':root['applicant_id']},'UNRELATED-EXIT-ROOT',procedure='exit_visa')
    assert later['id']!=child['id']
    current=core.preview(env,args)['report']
    assert current['status']=='available',current
    assert current['evidence']['active_application_id']==child['id']
    assert asyncio.run(core.service.record(env['engine'],**(request|dict(authority=None))))==saved
