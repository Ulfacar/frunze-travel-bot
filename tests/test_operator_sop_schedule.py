from copy import deepcopy
import pytest
from app.domain import operator_sop_rules as rules
from app.domain.entry_storage import EntryStorageInvalid


def schedule(**changes):
    return dict(on='2026-10-13',time=None,reason='source_followup',reference='SYNTHETIC-OPERATOR',proof='a'*64)|changes


def test_date_only_and_bishkek_exact_time_are_distinct():
    chosen=rules.selected_schedule(schedule())
    assert chosen['at'] is None and chosen['time'] is None and chosen['official'] is False
    assert chosen['calculated'] is False and chosen['origin']=='operator_selected'
    assert rules.selected_schedule(schedule(time='00:00'))['at']=='2026-10-12T18:00:00+00:00'
    assert rules.selected_schedule(schedule(time='23:59'))['at']=='2026-10-13T17:59:00+00:00'


@pytest.mark.parametrize('changes',[
    {'time':''},{'time':'9:00'},{'time':'24:00'},{'time':'12:60'},{'time':'12:30:00'},
    {'time':'１２:３０'},{'time':True},{'time':0},{'time':{}},
    {'on':'2026-2-1'},{'on':'20261013'},{'on':'2026-02-30'},{'on':True},
    {'reason':'official_due'},{'proof':'f'*63},{'reference':'lowercase'},
])
def test_noncanonical_or_wrong_meaning_schedule_is_refused(changes):
    with pytest.raises(EntryStorageInvalid):rules.selected_schedule(schedule(**changes))


def test_underflowing_local_instant_is_controlled_domain_refusal():
    with pytest.raises(EntryStorageInvalid):
        rules.selected_schedule(schedule(on='0001-01-01',time='00:00'))


def test_closed_catalogue_and_confirmed_operation():
    # Six visa additions and two combined W03-W04 source duties extend32.
    assert len(rules.DUTIES)==40
    for duty in rules.DUTIES:
        value=rules.definition(rules.PREFIX+duty)
        assert value['scope']=='operator_selected_internal_review_only'
        assert value['calculation']=='not_performed' and value['stages']
    with pytest.raises(EntryStorageInvalid):rules.definition(rules.PREFIX+'CUSTOM')
    command=dict(action='operator_review',confirmed=True,evidence_hash='b'*64,schedule=schedule())
    assert rules.operation(command)==command
    for confirm in (False,1,'true'):
        with pytest.raises(EntryStorageInvalid):rules.operation(command|{'confirmed':confirm})


def test_per_stage_source_references_and_narrow_terminal_catalogue():
    for duty,stage,section,page in [
        ('INVITER_FOLLOWUP','V11','14.2','62'),
        ('READY_SUBMISSION_REVIEW','V14','14.2','63'),
        ('ENTRY_EVE_REVIEW','V23','14.2','63'),
        ('ENTRY_CONFIRMATION_REVIEW','V23','14.2','63'),
        ('FEEDBACK_REVIEW','V25','19.1','79'),
        ('RETURN_TRIP_REVIEW','V25','19.1','79'),
        ('APPLICATION_STATUS','V17','19.1','78'),
        ('APPLICATION_STATUS','W12','19.9','82'),
        ('VERIFICATION_24H','V15','19.1','78'),
        ('VERIFICATION_48H','V15','19.1','78'),
        ('OTHER_AFTERCARE','V24','19.1','79'),
        ('EXEMPTION_REVIEW','V05','14.2','62'),
        ('EXEMPTION_REVIEW','V24','14.2','63'),
        ('DOCUMENTS_D14','V13','14.2','63'),
        ('WORK_COMMERCIAL_24H','W03','19.9','81'),
        ('WORK_COMMERCIAL_24H','W04','19.9','81'),
        ('WORK_COMMERCIAL_48H','W03','19.9','81'),
        ('WORK_COMMERCIAL_48H','W04','19.9','81'),
    ]:
        value=rules.definition(rules.PREFIX+duty)
        reference=next(r for r in value['source_refs'] if r['stage']==stage)
        assert (reference['section'],reference['printed_page'])==(section,page)
    assert rules.TERMINAL_DUTIES==frozenset(('STUDENT_ANNUAL','FEEDBACK_REVIEW','RETURN_TRIP_REVIEW','ENTRY_BAN_REVIEW','OTHER_AFTERCARE'))
    assert all(not any(stage.startswith(('X','WX','RX','UX')) for stage in rules.definition(rules.PREFIX+key)['stages']) for key in rules.TERMINAL_DUTIES)
