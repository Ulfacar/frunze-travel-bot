"""Retained source prefixes and replay; fresh authority never rewrites receipts."""
from datetime import datetime

from sqlalchemy import select

from app.domain import entry_anchors as anchors, entry_applications as apps, applicant_profiles as profiles
from app.domain import applicant_stay_history as stays, entry_interviews as interviews
from app.domain import knowledge_publication as publication, knowledge_decisions as decisions
from app.domain import specialist_interruptions as interruptions, conditional_deadline_rules as rules
from app.domain.conditional_deadline_policy import from_document
from app.domain.entry_anchor_rules import fail, shape
from app.domain.entry_storage import _hash, _plain
from app.domain.models import EntryConditionalEvidence, EntryInterview
from app.domain.specialist_evidence import publication_prefix
from app.domain.knowledge_publication_rules import unavailable_reasons
from app.knowledge.review import canonical


def instant(value):
    try:
        at = datetime.fromisoformat(value)
        if apps._utc(at) != value: raise ValueError
        return at
    except (ValueError, TypeError): fail('conditional_deadline_time_invalid')


def picked(rows, reference, at):
    if type(reference) is not dict: fail('conditional_deadline_pin_invalid')
    shape(reference, ('id', 'revision', 'hash'))
    row = anchors.selected(rows, reference['id'], at)
    if canonical(anchors.pin(row)) != canonical(reference): fail('conditional_deadline_pin_invalid')
    return row


async def cached(cache, key, loader):
    if key not in cache: cache[key] = await loader()
    return cache[key]


async def verify(session, case, person, application, row, *, cache):
    snapshot = _plain(row.snapshot)
    shape(snapshot, ('format', 'authority', 'report', 'cleared', 'previous_hash'))
    if snapshot['format'] != rules.FORMAT or type(snapshot['cleared']) is not bool: fail('conditional_deadline_snapshot_invalid')
    report = snapshot['report']; identity = ('authority',_hash(snapshot['authority']))
    if identity not in cache: cache[identity] = from_document(snapshot['authority'])
    authority = cache[identity]; p = authority.policy.document
    at = instant(report['checked_at']); on = apps._local_day(at).isoformat()
    if (report['evidence_hash'] != _hash({k:v for k,v in report.items() if k not in ('evidence_hash','checked_at')}) or
            report['format'] != rules.FORMAT or report['on'] != on or report['case_id'] != case.id or
            report['applicant_id'] != person.id or report['application_id'] != application.id or
            report['rule_id'] != row.rule_unit_id or p['rule_id'] != row.rule_unit_id or
            not p['valid_from'] <= on <= p['review_due_on'] or report['status'] not in ('calculated', 'review_trigger') or
            report['scope'] != 'internal_specialist_review_only' or report['operational_due_on'] is not None or
            report['permission_to_work'] is not None or report['permission_to_remain'] is not None or
            report['filing_allowed'] is not False or report['may_quote'] is not False or report['delivery'] != 'not_sent' or
            apps._utc(at) > apps._utc(row.created_at)):
        fail('conditional_deadline_report_invalid')
    profile = picked((await cached(cache,'profiles',lambda:profiles._history(session,case,person)))[0], report['profile'], at)
    picked(await cached(cache,'events',lambda:apps._events(session,application)), report['application_event'], at)
    source = report['source']; context, full = await cached(cache,'publication',lambda:publication._runtime_context(session))
    prefix = publication_prefix(full, source['publication_revision'])
    if (not prefix['rows'] or prefix['rows'][-1].snapshot_hash != source['publication_hash'] or
            prefix['active'] != source['version_id'] or apps._utc(prefix['rows'][-1].created_at) > apps._utc(at) or
            any(apps._utc(r.created_at) < apps._utc(at) for r in full['rows'][len(prefix['rows']):]) or
            prefix['policies'][source['version_id']] != publication._policy(authority.publication)):
        fail('conditional_deadline_publication_pin_invalid')
    version, bundle, projection = await context.source(source['version_id'])
    if profile.knowledge_version_id != version.id or row.knowledge_version_id != version.id: fail('conditional_deadline_version_mismatch')
    manifest = prefix['manifests'][version.id]
    if (source['manifest_hash'] != _hash(manifest) or any(source[k] != p[k] for k in ('source_hash','bundle_hash','projection_hash','catalog_hash')) or
            source['source_hash'] != version.source_hash or source['bundle_hash'] != version.bundle_hash or
            source['projection_hash'] != projection['projection_hash'] or source['catalog_hash'] != projection['catalog_hash']):
        fail('conditional_deadline_source_pin_invalid')
    required = [entry for entry in manifest['units'] if entry['unit_id'] in p['required_units']]
    if canonical(required) != canonical(source['required']) or {v['unit_id'] for v in required} != set(p['required_units']):
        fail('conditional_deadline_reviews_invalid')
    for entry in required:
        unit = decisions._unit(bundle, entry['unit_id']); reviews = await context.reviews(version.id, unit)
        selected = anchors.selected(reviews, entry['decision_id'], at)
        if selected.snapshot_hash != entry['decision_hash'] or _hash(unit) != entry['unit_hash'] or unavailable_reasons(unit, decisions._view(selected), day=apps._local_day(at), now=publication._utc(at)):
            fail('conditional_deadline_reviews_invalid')
    spec = rules.definition(row.rule_unit_id)
    unit = decisions._unit(bundle, row.rule_unit_id) if spec['source_kind'] == 'retained_null_deadline_unit' else None
    expected_rule = dict(unit_id=row.rule_unit_id, hash=_hash(unit or spec), value=None, section=spec['section'], page=spec['printed_page'])
    if (source['rule'] != expected_rule or p['rule_hash'] != expected_rule['hash'] or unit and
            (unit['kind'] != 'deadline' or unit['value'] is not None or unit['section'] != spec['section'] or unit['page'] != spec['printed_page'])):
        fail('conditional_deadline_rule_pin_invalid')
    header = None; ievents = []; retained = report['interview']
    if retained:
        header, ip = await cached(cache,('interview',retained['id']),lambda:interviews._header(session,case,person,retained['id']))
        ievents, _, _ = await cached(cache,('interview_events',header.id),lambda:interviews._history(session,header,ip))
        if header.snapshot_hash != retained['hash']: fail('conditional_deadline_interview_pin_invalid')
        if retained['head']:
            head = picked(ievents, retained['head'], at); ievents = ievents[:head.revision]
        else: ievents = []
    loaded = await cached(cache,('interruptions',_hash(retained)),lambda:interruptions.load(session, case_id=case.id, applicant_id=person.id, interview=header, events=ievents))
    stopped = interruptions.observe(loaded, at=at, retained=report['interruptions'])
    if stopped['errors']: fail('conditional_deadline_retained_stop_invalid')
    rows, _, _, _ = await cached(cache,'anchors',lambda:anchors.history(session, case, person, application))
    anchor_pin = report['anchors']; count = anchor_pin['revision']
    if type(count) is not int or not 0 <= count <= len(rows): fail('conditional_deadline_anchor_pin_invalid')
    prefix_anchors = rows[:count]; anchor_head = prefix_anchors[-1] if prefix_anchors else None
    if anchor_pin['head'] != (anchor_head.snapshot_hash if anchor_head else None): fail('conditional_deadline_anchor_pin_invalid')
    latest = {}
    for anchor in prefix_anchors: latest[anchor.anchor_key] = anchor
    if row.rule_unit_id in rules.VISA_RENEWAL_RULES:
        context = next((r for r in latest.values() if anchors.pin(r)==report['renewal_context']), None)
        if context is None or context.kind!='visa_renewal_context' or context.action!='record': fail('conditional_deadline_renewal_pin_invalid')
    calculations = []
    for reference in anchor_pin['selected']:
        anchor = next((r for r in latest.values() if anchors.pin(r) == reference), None)
        if anchor is None or anchor.action != 'record' or apps._utc(anchor.created_at) > apps._utc(at): fail('conditional_deadline_anchor_pin_invalid')
        data = _plain(anchor.command)['operation']['data']
        anchor_on = data['value']['valid_until'] if anchor.kind in anchors.rules.PERIODS else data['on']
        calculations.append(dict(anchor_id=anchor.id, anchor_on=anchor_on, calculation=rules.calculate(authority.policy, anchor_on, authority.calendars, on=on)))
    history_pin = report['stay_history']
    if spec['anchor_kind'] == 'actual_absence':
        history = picked((await cached(cache,'stays',lambda:stays._history(session,case,person)))[0], {k:history_pin[k] for k in ('id','revision','hash')}, at)
        data = stays._evidence([history], [profile], at)
        intervals = sorted(data['document']['intervals'], key=lambda r:r['entry_date'])
        if len(intervals) < 2 or history_pin['passport_ref'] != data['passport_ref'] or history_pin['exited_on'] != intervals[-2]['exit_date'] or history_pin['returned_on'] != intervals[-1]['entry_date']:
            fail('conditional_deadline_history_pin_invalid')
        trigger = rules.absence_threshold(authority.policy, history_pin['exited_on'], history_pin['returned_on'])
        due = on
        if trigger != report['trigger'] or not trigger['triggered']: fail('conditional_deadline_trigger_invalid')
    else:
        if not calculations: fail('conditional_deadline_calculation_missing')
        due = min(r['calculation']['due'] for r in calculations)
    if canonical(calculations) != canonical(report['calculations']) or due != report['review_due_on']: fail('conditional_deadline_replay_changed')
    pin = cache['pins'].get(row.id)
    expected = dict(application_id=application.id, case_id=case.id, rule_unit_id=row.rule_unit_id, applicant_id=person.id,
        profile_id=report['profile']['id'], application_event_id=report['application_event']['id'],
        anchor_id=anchor_head.id if anchor_head else None, history_id=history_pin['id'] if history_pin else None, receipt_hash=row.snapshot_hash)
    if pin is None or any(getattr(pin, k) != v for k,v in expected.items()): fail('conditional_deadline_independent_pin_invalid')
    return authority
