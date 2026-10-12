"""Actual absence inference must reconcile supplied current presence facts."""
from copy import deepcopy

from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,preview,actual
from tests import test_applicant_stay_history as histories


def test_absence_known_profile_presence_matches_history_or_requires_review(env,tmp_path):
    prepared=setup(env,tmp_path)
    profile_revision=prepared[2]['revision']
    history_revision=0
    base_doc=deepcopy(prepared[2]['input'])
    base_doc['profile']['in_kg_since']='2026-10-01'
    history_doc=histories.document(as_of='2026-10-13',history_complete=True,intervals=[
        histories.interval(ref='before',entry_date='2026-08-01',exit_date='2026-08-31'),
        histories.interval(ref='return',entry_date='2026-10-01',exit_date=None)])
    rule='KG.DL.INTERNAL_ABSENCE_REG_REVIEW'
    args=arguments(env,prepared,rule,authority(env,rule))

    def confirm(profile_doc,actual_history,label):
        nonlocal prepared,profile_revision,history_revision
        profile=actual.profiles.save(env,prepared[0],doc=profile_doc,revision=profile_revision,key=label+'-PROFILE')
        profile_revision+=1
        prepared=(prepared[0],prepared[1],profile)
        actual.write(env,actual.args(env,prepared))
        histories.save(env,prepared[0],profile,revision=history_revision,key=label+'-HISTORY',doc=actual_history)
        history_revision+=1
        return preview(env,args)['report']

    positive=confirm(base_doc,history_doc,'CONSISTENT')
    assert positive['status']=='review_trigger' and positive['trigger']['days']==31
    cases=[]
    different_entry=deepcopy(base_doc);different_entry['profile']['in_kg_since']='2026-09-03'
    cases.append(('entry_inside_absence',different_entry,history_doc))
    abroad=deepcopy(base_doc);abroad['profile']['current_location']='abroad'
    abroad['profile'].pop('in_kg_since');abroad['profile'].pop('current_basis_in_kg',None)
    cases.append(('abroad_with_open_stay',abroad,history_doc))
    closed=deepcopy(history_doc);closed['intervals'][-1]['exit_date']='2026-10-05'
    cases.append(('in_kg_with_closed_latest_stay',base_doc,closed))
    outcomes=[(label,confirm(profile_doc,actual_history,label)['review_due_on']) for label,profile_doc,actual_history in cases]
    assert all(due is None for _,due in outcomes),outcomes
