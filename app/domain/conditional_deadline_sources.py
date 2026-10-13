"""Current source/subject observations for explicitly delegated review dates."""
from datetime import datetime

from sqlalchemy import select

from app.domain import entry_anchors as anchors, entry_applications as apps, applicant_profiles as profiles
from app.domain import applicant_stay_history as stays, entry_interviews as interviews, specialist_interruptions as interruptions
from app.domain import knowledge_publication as publication, knowledge_decisions as decisions
from app.domain import conditional_deadline_rules as rules
from app.domain.conditional_deadline_policy import ConditionalAuthority
from app.domain.entry_anchor_rules import PERIODS, CHANGES, EAEU, fail
from app.domain.entry_storage import _hash, _plain, _id, EntryStorageInvalid
from app.domain.models import EntryInterview, _now
from app.knowledge.interview_rules import Answers


def _finish(report, reason=None):
    report['reason'] = reason
    report['evidence_hash'] = _hash({k:v for k,v in report.items() if k != 'checked_at'})
    return report


def _blank(case, person, application, rule_id, at):
    return dict(format=rules.FORMAT, case_id=case.id, applicant_id=person.id, application_id=application.id,
        rule_id=rule_id, checked_at=apps._utc(at), on=apps._local_day(at).isoformat(), status='unknown',
        scope='internal_specialist_review_only', review_due_on=None, operational_due_on=None,
        permission_to_work=None, permission_to_remain=None, filing_allowed=False, may_quote=False,
        delivery='not_sent', within_review_date=None, source=None, profile=None, application_event=None,
        interview=None, interruptions=None, anchors=None, stay_history=None, renewal_context=None, calculations=[], trigger=None)


async def source(session, authority, at):
    p = authority.policy.document
    context, published = await publication._runtime_context(session)
    if published['active'] is None: fail('conditional_deadline_no_publication')
    version, bundle, projection = await context.source(published['active'])
    manifest = published['manifests'][version.id]
    view = dict(version_id=version.id, source_hash=version.source_hash, bundle_hash=version.bundle_hash,
        projection_hash=projection['projection_hash'], catalog_hash=projection['catalog_hash'],
        publication_revision=len(published['rows']), publication_hash=published['rows'][-1].snapshot_hash,
        manifest_hash=_hash(manifest), rule=None, required=[])
    if any(view[k] != p[k] for k in ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash')):
        fail('conditional_deadline_source_changed')
    spec = rules.definition(p['rule_id'])
    if spec['source_kind'] == 'retained_null_deadline_unit':
        unit = next((r for r in bundle['units'] if r['unit_id'] == p['rule_id']), None)
        if (unit is None or unit['kind'] != 'deadline' or _hash(unit) != p['rule_hash'] or unit['value'] is not None or
                unit['section'] != spec['section'] or unit['page'] != spec['printed_page']):
            fail('conditional_deadline_original_rule_changed')
        view['rule'] = dict(unit_id=unit['unit_id'], hash=_hash(unit), value=None, section=unit['section'], page=unit['page'])
    else:
        view['rule'] = dict(unit_id=p['rule_id'], hash=_hash(spec), value=None, section=spec['section'], page=spec['printed_page'])
    available = await publication._runtime_in_session(context, published, policy=authority.publication, ids=p['required_units'], at=at)
    if available['unavailable']: fail('conditional_deadline_source_unavailable')
    view['required'] = [entry for entry in manifest['units'] if entry['unit_id'] in p['required_units']]
    return view


async def personal_context(session, case, person, application, at):
    prows = (await profiles._history(session, case, person))[0]
    if not prows: fail('conditional_deadline_profile_required')
    profile = prows[-1]; events = await apps._events(session, application)
    if any(apps._utc(r.created_at) > apps._utc(at) for r in (case, person, application, profile, events[-1])):
        fail('conditional_deadline_future_source')
    ids = list((await session.scalars(select(EntryInterview.id).where(EntryInterview.case_id == case.id,
        EntryInterview.applicant_id == person.id).limit(2))).all())
    if len(ids) > 1: fail('conditional_deadline_interview_ambiguous')
    header = None; ievents = []; state = None; interview_pin = None; reported = {}
    if ids:
        header, policy = await interviews._header(session, case, person, ids[0])
        ievents, state, _ = await interviews._history(session, header, policy)
        if state.get('collection_blocked'):
            fail('conditional_deadline_collection_or_dialogue_blocked')
        if apps._utc(header.created_at) > apps._utc(at) or ievents and apps._utc(ievents[-1].created_at) > apps._utc(at):
            fail('conditional_deadline_future_interview')
        interview_pin = dict(id=header.id, hash=header.snapshot_hash, head=anchors.pin(ievents[-1]) if ievents else None)
        answers = Answers(state['answers'], catalog_document=_plain(header.catalog)); profile_data = _plain(profile.input_snapshot)['profile']
        reported = {key:answers.get(key) for key in ('current_until','registration.until','current_inviter','inviter.name','purpose','current_visa_type') if key in state['answers']}
        for answer, field in (('location', 'current_location'), ('purpose', 'purpose'), ('passport_country', 'entry_passport_country'), ('current_basis', 'current_basis_in_kg')):
            if answer in state['answers'] and answers.get(answer) != profile_data.get(field):
                fail('conditional_deadline_interview_conflict')
    loaded = await interruptions.load(session, case_id=case.id, applicant_id=person.id, interview=header, events=ievents)
    stopped = interruptions.observe(loaded, at=at)
    if stopped['errors']: fail('conditional_deadline_collection_or_dialogue_blocked')
    return profile, events[-1], interview_pin, stopped['pins'], reported


def _applicability(rule_id, selected, profile, application, reported):
    p = _plain(profile.input_snapshot)['profile']
    for receipt in selected:
        if receipt['kind'] not in PERIODS: continue
        until = receipt['operation']['data']['value']['valid_until']
        if receipt['kind']=='registration_period':
            if any(value not in (None,'unknown',until) for value in (p.get('registration_until'),reported.get('registration.until'))):
                fail('conditional_deadline_registration_date_conflict')
        basis = {'visa_period':'visa','permit_period':'ep','resident_period':'resident_card'}.get(receipt['kind'])
        if basis and p.get('current_basis_in_kg')==basis and any(value not in (None,'unknown',until) for value in (p.get('current_basis_until'),reported.get('current_until'))):
            fail('conditional_deadline_basis_date_conflict')
    if rule_id in rules.VISA_RENEWAL_RULES or rule_id in rules.VISA_SCOPES:
        if (p.get('current_location') != 'in_kg' or p.get('current_basis_in_kg') != 'visa' or
                p.get('current_basis_until') != selected[0]['operation']['data']['value']['valid_until']):
            fail('conditional_deadline_renewal_scope_unresolved' if rule_id in rules.VISA_RENEWAL_RULES else 'conditional_deadline_visa_scope_unresolved')
        if rule_id in rules.VISA_SCOPES and reported.get('current_visa_type') not in (None, 'unknown', p.get('current_visa_type')):
            fail('conditional_deadline_visa_type_conflict')
        if rule_id in rules.VISA_SCOPES:
            visa_type, purposes = rules.VISA_SCOPES[rule_id]
            if p.get('current_visa_type') != visa_type or p.get('purpose') not in purposes:
                fail('conditional_deadline_visa_scope_unresolved')
        if rule_id in rules.VISA_RENEWAL_RULES and p.get('current_visa_type') in (None, 'unknown', 'not_applicable', 'TS', 'TR', 'R'):
            fail('conditional_deadline_renewal_scope_unresolved')
    if rule_id == 'KG.DL.INTERNAL_EAEU_REG_REVIEW':
        value = selected[0]['operation']['data']['value']
        if (p.get('current_location') != 'in_kg' or p.get('entry_passport_country') not in EAEU-{'KGZ'} or p.get('citizenship') != [p.get('entry_passport_country')] or
                value['tax_status'] != 'pending' or value['basis_type'] not in ('employment', 'self_employed', 'appointment', 'family')):
            fail('conditional_deadline_eaeu_scope_unresolved')
        if value['basis_type'] == 'family':
            if p.get('purpose') != 'family_of_foreigner': fail('conditional_deadline_family_scope_unresolved')
        elif p.get('purpose') != 'work_hire': fail('conditional_deadline_employment_scope_unresolved')


async def evaluate(session, *, actor, case, person, application, rule_id, authority=None, at=None):
    """Caller owns case/application/person locks; all source reads precede writes."""
    if at is None and authority is not None:
        await publication._runtime_context(session)
    at = _now() if at is None else at; report = _blank(case, person, application, rule_id, at)
    spec = rules.definition(rule_id)
    if authority is None: return _finish(report, 'conditional_deadline_authority_missing')
    if not isinstance(authority, ConditionalAuthority): fail('conditional_deadline_authority_invalid')
    authority.validate(); p = authority.policy.document
    if p['rule_id'] != rule_id or actor not in p['operators']: return _finish(report, 'conditional_deadline_operator_unavailable')
    if not p['valid_from'] <= report['on'] <= p['review_due_on']: return _finish(report, 'conditional_deadline_authority_expired')
    try:
        profile, event, interview_pin, stop_pins, reported = await personal_context(session, case, person, application, at)
        report.update(profile=anchors.pin(profile), application_event=anchors.pin(event), interview=interview_pin, interruptions=stop_pins)
        report['source'] = await source(session, authority, at)
        if profile.knowledge_version_id != report['source']['version_id']: fail('conditional_deadline_profile_source_changed')
        if event.status in ('closed', 'refused') and spec['anchor_kind'] != 'permit_terminated':
            fail('conditional_deadline_application_closed')
        observed = await anchors.current(session, case, person, application, policy=authority.anchors, at=at)
        report['anchors'] = dict(revision=observed['revision'], head=observed['head'], selected=[])
        if spec['anchor_kind'] == 'actual_absence':
            if application.procedure != 'registration': fail('conditional_deadline_application_scope')
            hrows, _, _ = await stays._history(session, case, person)
            h = stays._evidence(hrows, [profile], at)
            if h['status'] != 'recorded_inputs' or not h['document']['history_complete']:
                fail('conditional_deadline_actual_absence_unresolved')
            arows, latest, _, _ = await anchors.history(session, case, person, application)
            replacements, _ = await anchors.passport_observations(session, case, person, application, arows, latest)
            if any(apps._utc(r.created_at) >= apps._utc(hrows[-1].created_at) for r in replacements):
                fail('conditional_deadline_absence_passport_changed')
            intervals = sorted(h['document']['intervals'], key=lambda r:r['entry_date'])
            for earlier, later in zip(intervals, intervals[1:]):
                if earlier['exit_date'] is None or earlier['exit_date'] >= later['entry_date']:
                    fail('conditional_deadline_actual_absence_overlaps')
            if len(intervals) < 2 or intervals[-2]['exit_date'] is None: fail('conditional_deadline_actual_return_required')
            before, after = intervals[-2:]
            if not before['confirmed'] or not after['confirmed'] or before['passport_country'] != after['passport_country']:
                fail('conditional_deadline_actual_absence_unresolved')
            pdoc = _plain(profile.input_snapshot)['profile']
            if (after['exit_date'] is None and pdoc.get('current_location') == 'abroad' or
                    pdoc.get('current_location') == 'in_kg' and (after['exit_date'] is not None or
                    pdoc.get('in_kg_since') not in (None, 'unknown', after['entry_date']))):
                fail('conditional_deadline_absence_presence_conflict')
            report['stay_history'] = dict(**anchors.pin(hrows[-1]), passport_ref=h['passport_ref'],
                exited_on=before['exit_date'], returned_on=after['entry_date'])
            trigger = rules.absence_threshold(authority.policy, before['exit_date'], after['entry_date'])
            report['trigger'] = trigger
            if not trigger['triggered']: return _finish(report, 'conditional_deadline_absence_below_threshold')
            report.update(status='review_trigger', review_due_on=report['on'], within_review_date=True)
            return _finish(report, 'actual_absence_requires_registration_review')
        kinds = CHANGES if spec['anchor_kind'] == 'effective_registration_changes' else {spec['anchor_kind']}
        relevant = [r for r in observed['observations'] if r['receipt']['kind'] in kinds and r['receipt']['operation']['action'] != 'withdraw']
        if not relevant: fail('conditional_deadline_actual_anchor_required')
        if any(not r['usable'] for r in relevant): fail('conditional_deadline_actual_anchor_unresolved')
        selected = [r['receipt'] for r in relevant]
        if spec['anchor_kind'] != 'effective_registration_changes' and len(selected) != 1: fail('conditional_deadline_actual_anchor_ambiguous')
        _applicability(rule_id, selected, profile, application, reported)
        if rule_id in rules.VISA_RENEWAL_RULES:
            contexts = [r for r in observed['observations'] if r['receipt']['kind']=='visa_renewal_context' and r['receipt']['operation']['action']=='record']
            if len(contexts)!=1 or not contexts[0]['usable']: fail('conditional_deadline_renewal_premises_required')
            receipt=contexts[0]['receipt'];value=receipt['operation']['data']['value'];pdoc=_plain(profile.input_snapshot)['profile']
            if (value['period_anchor_id']!=selected[0]['id'] or value['period_anchor_hash']!=selected[0]['snapshot_hash'] or
                    value['current_type']!=pdoc.get('current_visa_type') or value['target_purpose']!=pdoc.get('purpose') or
                    value['target_type'] in ('TS','TR','R') or value['current_inviter_ref']!=value['target_inviter_ref']):
                fail('conditional_deadline_renewal_premises_conflict')
            if (reported.get('current_visa_type') not in (None,'unknown',value['current_type']) or
                    reported.get('current_inviter') is not None and reported.get('inviter.name') is not None and
                    reported['current_inviter']!=reported['inviter.name']):
                fail('conditional_deadline_renewal_interview_conflict')
            report['renewal_context']=dict(id=receipt['id'],revision=receipt['revision'],hash=receipt['snapshot_hash'])
        for receipt in selected:
            data = receipt['operation']['data']; value = data['value']
            if spec['anchor_kind'] == 'registration_payment_code' and value['event_meaning'] != p['code_anchor']:
                fail('conditional_deadline_payment_anchor_unresolved')
            if rule_id == 'KG.DL.INTERNAL_EAEU_REG_REVIEW':
                count = (rules.day(value['valid_until']) - rules.day(value['valid_from'])).days + int(p['period_counting'] == 'both_boundary_dates')
                if count != 60: fail('conditional_deadline_actual_sixty_day_period_required')
            anchor_on = value['valid_until'] if receipt['kind'] in PERIODS else data['on']
            calculation = rules.calculate(authority.policy, anchor_on, authority.calendars, on=report['on'])
            report['anchors']['selected'].append(dict(id=receipt['id'], revision=receipt['revision'], hash=receipt['snapshot_hash']))
            report['calculations'].append(dict(anchor_id=receipt['id'], anchor_on=anchor_on, calculation=calculation))
        due = min(r['calculation']['due'] for r in report['calculations'])
        report.update(status='calculated', review_due_on=due,
            within_review_date=report['on']<=due if p['boundary_inclusive'] else report['on']<due)
        return _finish(report, 'conditional_specialist_review_date_only')
    except EntryStorageInvalid as exc:
        # Evidence corruption is an error, not ordinary missing authority.
        code = str(exc)
        if not code.startswith('conditional_deadline_') and code not in ('calendar_year_missing', 'calendar_provisional', 'calendar_search_limit'):
            raise
        report.update(review_due_on=None, within_review_date=None, calculations=[], status='unknown')
        return _finish(report, code)
