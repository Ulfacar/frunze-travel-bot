"""Declared complete history can still contain contradictory closed intervals."""
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,preview,actual
from tests import test_applicant_stay_history as histories


def test_absence_uses_actual_history_not_only_last_two_start_dates(env,tmp_path):
    prepared=setup(env,tmp_path)
    # R19 fixture correction: the latest actual stay is closed, so use an explicit abroad profile.
    doc=actual.profiles.read(env,prepared[0])['saved']['input']
    doc['profile']['current_location']='abroad'
    doc['profile'].pop('in_kg_since',None);doc['profile'].pop('current_basis_in_kg',None)
    profile=actual.profiles.save(env,prepared[0],doc=doc,revision=prepared[2]['revision'],key='COHERENT-CLOSED-STAY')
    prepared=(prepared[0],prepared[1],profile)
    allowed=authority(env,'KG.DL.INTERNAL_ABSENCE_REG_REVIEW')
    args=arguments(env,prepared,'KG.DL.INTERNAL_ABSENCE_REG_REVIEW',allowed)
    doc=histories.document(as_of='2026-10-13',history_complete=True,intervals=[
        histories.interval(ref='older',entry_date='2026-08-01',exit_date='2026-08-31'),
        histories.interval(ref='return',entry_date='2026-10-01',exit_date='2026-10-05')])
    histories.save(env,prepared[0],prepared[2],doc=doc)
    good=preview(env,args)['report']
    assert good['status']=='review_trigger' and good['trigger']['days']==31
    doc['intervals'].append(histories.interval(ref='contradictory-long-stay',entry_date='2026-07-01',exit_date='2026-09-30'))
    histories.save(env,prepared[0],prepared[2],revision=1,key='WITH-OVERLAP',doc=doc)
    recorded=histories.read(env,prepared[0])
    assert recorded['current']['status']=='recorded_inputs', 'The generic journal intentionally stores factual inputs without qualifying them'
    unsafe=preview(env,args)['report']
    assert unsafe['review_due_on'] is None and unsafe['status']=='unknown', unsafe
