"""Independent source-specific actual-visa applicability controls on frozen R20."""
from datetime import datetime, timezone

from app.domain import entry_interviews
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock, setup, authority, arguments, preview, renewal, actual
from tests import test_entry_interviews as interview


def visa_profile(env, prepared, visa_type, purpose, key):
    doc=actual.profiles.request()
    doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose=purpose,
        current_location='in_kg',in_kg_since='2026-09-03',current_basis_in_kg='visa',
        current_visa_type=visa_type,current_basis_until='2026-11-01')
    profile=actual.profiles.save(env,prepared[0],doc=doc,revision=prepared[2]['revision'],key=key)
    return prepared[0],prepared[1],profile


def report(env,prepared,rule):
    return preview(env,arguments(env,prepared,rule,authority(env,rule)))['report']


def test_visa_sop_scope_requires_own_kind_and_reconciles_interview(env,tmp_path,monkeypatch):
    monkeypatch.setattr(entry_interviews,'_now',lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
    prepared=setup(env,tmp_path,'visa_period')
    prepared=visa_profile(env,prepared,'TS','tourism','TS-CURRENT')
    actual.write(env,actual.args(env,prepared,'visa_period'))
    ts='KG.DL.INTERNAL_TS_EXIT_REVIEW'
    positive=report(env,prepared,ts)
    assert positive['review_due_on']=='2026-10-27' and positive['renewal_context'] is None
    assert positive['filing_allowed'] is False and positive['operational_due_on'] is None
    iv=interview.start(env,prepared[0],owner_login='admin')
    for key,value in [('location','in_kg'),('current_basis','visa'),('current_visa_type','B')]:
        interview.correct(env,iv,{key:value})
    denied=report(env,prepared,ts)
    assert denied['reason']=='conditional_deadline_visa_type_conflict' and denied['review_due_on'] is None
    interview.correct(env,iv,{'current_visa_type':'TS'})
    assert report(env,prepared,ts)['review_due_on']=='2026-10-27'

    business=actual.setup(env,'visa_period',key='B-SOURCE')
    business,context=renewal(env,business)
    b='KG.DL.INTERNAL_B_RENEWAL_PREPARATION'
    assert report(env,business,b)['reason']=='conditional_deadline_renewal_premises_required'
    actual.write(env,context)
    assert report(env,business,b)['review_due_on']=='2026-10-08'

    relative=actual.setup(env,'visa_period',key='RL-SOURCE')
    relative=visa_profile(env,relative,'RL','relatives_kg_citizen','RL-CURRENT')
    actual.write(env,actual.args(env,relative,'visa_period'))
    wrong=actual.setup(env,'permit_period',key='PERMIT-NOT-RL')
    wrong=visa_profile(env,wrong,'RL','relatives_kg_citizen','RL-PERMIT-PROFILE')
    actual.write(env,actual.args(env,wrong,'permit_period'))
    for rule,due in [('KG.DL.INTERNAL_RL_RES_PREPARATION','2026-10-08'),('KG.DL.INTERNAL_RL_RES_REVIEW','2026-10-19')]:
        assert report(env,relative,rule)['review_due_on']==due
        denied=report(env,wrong,rule)
        assert denied['review_due_on'] is None and denied['reason']=='conditional_deadline_actual_anchor_required'
