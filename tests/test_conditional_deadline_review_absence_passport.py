"""The absence consumer must not ignore later own-person passport observations."""
from datetime import datetime,timedelta,timezone

from app.domain import entry_anchors,conditional_deadline_sources
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,preview,actual
from tests import test_applicant_stay_history as histories


def test_own_other_application_passport_change_requires_fresh_history_confirmation(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    # R19 fixture correction only: preserve the actual open return and match its profile entry.
    profile_doc=actual.profiles.read(env,prepared[0])['saved']['input']
    profile_doc['profile']['in_kg_since']='2026-10-01'
    profile=actual.profiles.save(env,prepared[0],doc=profile_doc,revision=prepared[2]['revision'],key='COHERENT-OPEN-STAY')
    prepared=(prepared[0],prepared[1],profile)
    doc=histories.document(as_of='2026-10-13',history_complete=True,intervals=[
        histories.interval(ref='before',entry_date='2026-08-01',exit_date='2026-08-31'),
        histories.interval(ref='returned',entry_date='2026-10-01',exit_date=None)])
    histories.save(env,prepared[0],prepared[2],doc=doc)
    rule='KG.DL.INTERNAL_ABSENCE_REG_REVIEW'
    args=arguments(env,prepared,rule,authority(env,rule))
    assert preview(env,args)['report']['trigger']['days']==31
    at=datetime(2026,10,13,10,tzinfo=timezone.utc)+timedelta(seconds=1)
    monkeypatch.setattr(entry_anchors,'_now',lambda:at)
    monkeypatch.setattr(conditional_deadline_sources,'_now',lambda:at)
    other=actual.setup(env,key='OTHER-PERSON')
    change=actual.args(env,other,'passport_change','REPLACED-OTHER')
    actual.write(env,change)
    assert preview(env,args)['report']['review_due_on']=='2026-10-13'
    second=actual.application(env,prepared[0],'SAME-PERSON-SECOND',procedure='registration')
    actual.app_event(env,second,'SECOND-SUBMIT',reference='AP'+str(second['id']).zfill(6))
    same=(prepared[0],second,prepared[2])
    own_change=actual.args(env,same,'passport_change','REPLACED-OWN')
    actual.write(env,own_change)
    result=preview(env,args)['report']
    assert result['review_due_on'] is None,result
