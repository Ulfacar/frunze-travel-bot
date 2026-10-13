"""Original authority, canonical selected time and independent own-source pins."""
from app.domain import operator_sop_rules as rules, operator_sop_sources as sources
from app.domain import entry_applications as apps, conditional_deadline_evidence as retained
from app.domain.entry_storage import _hash, _plain
from app.domain.entry_anchor_rules import shape
from app.domain.entry_process_policy import authorize
from app.domain.operator_sop_policy import from_document
from app.domain.permissions import Actor
from app.knowledge.review import canonical


async def verify(session,case,person,application,row,*,cache):
    snapshot=_plain(row.snapshot)
    shape(snapshot,('format','authority','report','schedule','cleared','previous_hash'))
    if snapshot['format']!=rules.FORMAT or type(snapshot['cleared']) is not bool: rules.fail('operator_sop_snapshot_invalid')
    identity=('authority',_hash(snapshot['authority']))
    if identity not in cache: cache[identity]=from_document(snapshot['authority'])
    authority=cache[identity];p=authority.policy.document;report=snapshot['report']
    at=retained.instant(report['checked_at']);on=apps._local_day(at).isoformat()
    schedule=snapshot['schedule'];selection={k:schedule[k] for k in ('on','time','reason','reference','proof')}
    if canonical(rules.selected_schedule(selection))!=canonical(schedule): rules.fail('operator_sop_schedule_invalid')
    operation=_plain(row.command)['operation']
    if operation['action']=='operator_review' and canonical(operation['schedule'])!=canonical(selection): rules.fail('operator_sop_schedule_changed')
    if (report['evidence_hash']!=_hash({k:v for k,v in report.items() if k not in ('evidence_hash','checked_at')}) or
            report['format']!=rules.FORMAT or report['on']!=on or report['case_id']!=case.id or
            report['applicant_id']!=person.id or report['application_id']!=application.id or
            report['rule_id']!=row.rule_unit_id or p['rule_id']!=row.rule_unit_id or
            not p['valid_from']<=on<=p['review_due_on'] or report['status']!='available' or
            report['scope']!='operator_selected_internal_review_only' or report['operational_due_on'] is not None or
            report['calculated'] is not False or report['official'] is not False or report['filing_allowed'] is not False or
            report['may_quote'] is not False or report['delivery']!='not_sent' or apps._utc(at)>apps._utc(row.created_at)):
        rules.fail('operator_sop_report_invalid')
    authorize(Actor(row.created_by,True),authority.process,day=apps._local_day(at))
    await sources.source(session,authority,at,original=report['source'],cache=cache)
    observed,profile=await sources.observe(cache['context'],person,row.rule_unit_id,authority,at,original=report['evidence'],cache=cache)
    if profile.knowledge_version_id!=row.knowledge_version_id or row.knowledge_version_id!=report['source']['version_id']:
        rules.fail('operator_sop_version_mismatch')
    pin=cache['pins'].get(row.id)
    expected=dict(application_id=application.id,case_id=case.id,rule_unit_id=row.rule_unit_id,applicant_id=person.id,
        process_event_id=observed['process']['id'],profile_id=observed['profile']['id'],
        active_application_id=observed['active_application_id'],active_procedure=observed['active_procedure'],
        application_event_id=observed['application_event']['id'],receipt_hash=row.snapshot_hash)
    if pin is None or any(getattr(pin,k)!=v for k,v in expected.items()): rules.fail('operator_sop_independent_pin_invalid')
    return authority
