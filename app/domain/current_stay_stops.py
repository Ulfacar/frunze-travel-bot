"""Fresh current-stay stop evidence. No eligibility, writes, delivery or activation."""
from datetime import date

from sqlalchemy import select

from app.domain import applicant_profiles as profiles, applicant_stay_history as stays
from app.domain import entry_applications as transactions, entry_interviews as interviews
from app.domain import knowledge_publication as publication, assessment_rules
from app.domain.current_stay_policy import CurrentStayPolicy, CurrentStayFact, VERSION, PARAMETERS, STOPS
from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash, _id, _plain
from app.domain.models import EntryInterview, _now
from app.domain.qualification_policy import QualificationPolicy
from app.knowledge import interview_rules
from app.knowledge.current_stay_checks import working_margin, observed_headroom
from app.knowledge.stay_days import StayDayReview, StayReviewError, COUNT_RULE_IDS
from app.knowledge.work_calendar import WorkCalendars

KEYS = ('expired_stay', 'working_day_margin', 'visa_free_headroom')


def _unknown(reason): return dict(status='unknown', reason=reason)


def _conditions(fact, profile):
    c = {k: v['value'] for k, v in fact['conditions'].items()}
    result = dict(schema_version='kg-entry-condition-facts/1',
        entry_passport_country=profile.get('entry_passport_country'), document_type=profile.get('document_type'))
    if c['residence_country'] is not None:
        result['residence_documents'] = dict(complete=c['other_residence_absent'] is True, items=[
            dict(country=c['residence_country'], kind='other', permanent=True)])
    if c['foreign_visa_absent'] is True:
        result['foreign_visas'] = dict(complete=True, items=[])
    if c['organized_group_absent'] is True:
        result['tour_group'] = dict(organized=False)
    return result


async def evaluate(engine, *, actor, case_id, applicant_id, policy=None, fact=None,
                   qualification_policy=None, publication_policy=None, calendars=None):
    _authorize(actor); _id(case_id); _id(applicant_id)
    async def read(session):
        return await evaluate_in_session(session, actor=actor, case_id=case_id, applicant_id=applicant_id,
            policy=policy, fact=fact, qualification_policy=qualification_policy,
            publication_policy=publication_policy, calendars=calendars)
    return await transactions._run(engine, read)


async def evaluate_in_session(session, *, actor, case_id, applicant_id, policy=None, fact=None,
                              qualification_policy=None, publication_policy=None, calendars=None):
    """Caller owns transaction; obtains case/person/publication locks in that order.

An incoming composer must take route/capacity locks first. The timestamp is
sampled only after all current-evidence locks. No nested session or provider.
"""
    return await _evaluate_in_session(session, actor=actor, case_id=case_id, applicant_id=applicant_id,
        policy=policy, fact=fact, qualification_policy=qualification_policy,
        publication_policy=publication_policy, calendars=calendars)


async def evaluate_dialogue_in_session(session, *, actor, case_id, applicant_id, dialogue_session_id,
                                      session_policy, policy, fact, qualification_policy,
                                      publication_policy, calendars):
    """Recompute a separately authorized original-anchor proof under these locks.

    No caller-provided proof or rewritten factual attestation is accepted.
    The ordinary public reader keeps its exact current-head contract.
    """
    from app.domain.dialogue_session_policy import SessionPolicy
    _id(dialogue_session_id)
    if not isinstance(session_policy, SessionPolicy):
        raise EntryStorageInvalid('dialogue_session_policy_required')
    return await _evaluate_in_session(session, actor=actor, case_id=case_id, applicant_id=applicant_id,
        policy=policy, fact=fact, qualification_policy=qualification_policy,
        publication_policy=publication_policy, calendars=calendars,
        dialogue_session_id=dialogue_session_id, session_policy=session_policy)


async def _evaluate_in_session(session, *, actor, case_id, applicant_id, policy=None, fact=None,
                               qualification_policy=None, publication_policy=None, calendars=None,
                               dialogue_session_id=None, session_policy=None):
    _authorize(actor); _id(case_id); _id(applicant_id)
    for value, expected in ((policy, CurrentStayPolicy), (fact, CurrentStayFact),
                            (qualification_policy, QualificationPolicy), (calendars, WorkCalendars)):
        if value is not None and not isinstance(value, expected):
            raise EntryStorageInvalid('invalid_current_stay_authority')
    await transactions._case(session, case_id, lock=True)
    case, person = await profiles._subject(session, case_id, applicant_id)
    context, published = await publication._runtime_context(session)
    rows, _, _ = await profiles._history(session, case, person)
    now = _now(); today = transactions._local_day(now); on = today.isoformat()
    result = dict(format=VERSION, scope='current_stay_stops_only', case_id=case_id, applicant_id=applicant_id,
        checked_at=transactions._utc(now), as_of=on, checks={k: _unknown('not_evaluated') for k in KEYS},
        requires_specialist=True, entry_eligibility_evaluated=False, permission_to_remain=None,
        may_quote=False, delivery='not_sent', profile=None, source=None, authority=None, fact=None,
        interview=None, history=None, arithmetic=None, applicability=None, calendar=None)
    if dialogue_session_id is not None:
        result.update(format='kg-dialogue-current-stay/1', reconciliation=None)
    def finish(reason=None):
        if reason:
            result['checks'] = {k: _unknown(reason) for k in KEYS}
        result['requires_specialist'] = any(c['status'] != 'not_triggered' for c in result['checks'].values())
        result['evidence_hash'] = _hash(result)
        return result
    if not rows: return finish('individual_profile_missing')
    row = rows[-1]; request = _plain(row.input_snapshot); p = request['profile']
    result['profile'] = dict(id=row.id, snapshot_hash=row.snapshot_hash, revision=row.revision)
    if request['as_of'] != on or transactions._utc(row.created_at) > transactions._utc(now):
        return finish('individual_profile_needs_current_confirmation')
    location = p.get('current_location')
    if location not in ('abroad', 'in_kg'): return finish('current_location_unknown')
    if policy is None or fact is None: return finish('current_stay_authority_missing')
    authority = policy.document; attestation = fact.document
    result['authority'] = dict(hash=policy.digest, reference=authority['reference'])
    result['fact'] = dict(hash=fact.digest, reference=attestation['reference'], actor=attestation['actor'],
        provenance='explicit_server_attestation_not_government_verification')
    if (attestation['actor'] != actor.manager_id or attestation['policy_hash'] != policy.digest or
        attestation['case_id'] != case_id or attestation['applicant_id'] != applicant_id or
        attestation['profile_id'] != row.id or attestation['profile_hash'] != row.snapshot_hash):
        return finish('current_stay_attestation_scope_changed')
    if (attestation['as_of'] != on or any(not d['valid_from'] <= on <= d['review_due_on']
                                        for d in (attestation, authority))):
        return finish('current_stay_authority_outside_validity')
    if attestation['location'] != location: return finish('current_stay_location_conflict')
    history = await stays.current_in_session(session, case, person, at=now)
    result['history'] = {k: history[k] for k in ('status', 'history_id', 'profile_id', 'snapshot_hash', 'findings')}
    history_pin = None if history['history_id'] is None else dict(id=history['history_id'], snapshot_hash=history['snapshot_hash'])
    if attestation['history'] != history_pin: return finish('current_stay_history_changed')
    if history['status'] not in ('missing', 'recorded_inputs'): return finish('current_stay_history_' + history['status'])
    intervals = (history.get('document') or {}).get('intervals', [])
    opened = [v for v in intervals if v['exit_date'] is None]
    if history['status'] == 'recorded_inputs':
        if history['passport_ref'] != attestation['passport_ref']:
            return finish('current_stay_history_passport_conflict')
        if (location == 'abroad' and opened or location == 'in_kg' and (len(opened) != 1 or
                opened[0]['entry_date'] != attestation['entered_on'] or
                opened[0]['basis'] != attestation['current_basis'] or
                opened[0]['passport_country'] != p.get('entry_passport_country'))):
            return finish('current_stay_history_location_or_basis_conflict')
    ids = list((await session.scalars(select(EntryInterview.id).where(
        EntryInterview.case_id == case_id, EntryInterview.applicant_id == applicant_id).limit(2))).all())
    pin = attestation['interview']
    if len(ids) > 1 or (bool(ids) != (pin is not None)) or ids and ids[0] != pin['id']:
        return finish('current_stay_interview_changed')
    answers = None
    if ids:
        header, pinned = await interviews._header(session, case, person, ids[0])
        events, state, _ = await interviews._history(session, header, pinned)
        result['interview'] = dict(id=header.id, header_hash=header.snapshot_hash, head_hash=events[-1].snapshot_hash)
        if (dialogue_session_id is None and pin != result['interview'] or header.profile_id != row.id or
            transactions._utc(events[-1].created_at) > transactions._utc(now)):
            return finish('current_stay_interview_changed')
        if state['collection_blocked']: return finish('interview_collection_blocked')
        if dialogue_session_id is not None:
            from app.domain.dialogue_reconciliation import verify_in_session
            proof = await verify_in_session(session, dialogue_session_id=dialogue_session_id,
                policy=session_policy, fact=fact, interview=header, events=events, state=state,
                profile=p, history=history, at=now)
            if proof.get('status') != 'verified': return finish(proof['reason'])
            result['reconciliation'] = proof
        answers = interview_rules.Answers(state['answers'], catalog_document=_plain(header.catalog))
        expected = {'location': location, 'current_basis': attestation['current_basis'],
                    'actual_entry.on': attestation['entered_on'], 'current_until': attestation['lawful_until'],
                    'citizenships': sorted(p.get('citizenship', [])),
                    'residence_country': attestation['conditions']['residence_country']['value'],
                    'document_type': p.get('document_type'), 'passport_country': p.get('entry_passport_country')}
        for key, value in expected.items():
            if key in state['answers'] and answers.get(key) != value:
                return finish('current_stay_interview_fact_conflict')
        for key, field in (('foreign_residence.exists', 'other_residence_absent'),
                           ('long_visa.exists', 'foreign_visa_absent'), ('organized_group.exists', 'organized_group_absent')):
            if key in state['answers'] and (answers.get(key) is not False or attestation['conditions'][field]['value'] is not True):
                return finish('current_stay_interview_fact_conflict')
        # This narrow reader does not assign an interpretation to D1/D2's
        # reported history (which may include the current interval). A later
        # approved reconciliation can expand it; never ignore supplied rows.
        if any(k in state['answers'] for k in ('history_count', 'reported_window', 'reported_days')) or any(
                k.startswith('history.') for k in state['answers']):
            return finish('current_stay_interview_history_reconciliation_required')
        if 'previous_visits' in state['answers'] and (answers.get('previous_visits') is not False or
                history['status'] != 'recorded_inputs' or any(v['exit_date'] is not None for v in intervals)):
            return finish('current_stay_interview_history_conflict')
    elif dialogue_session_id is not None:
        return finish('dialogue_interview_required')
    if location == 'abroad':
        if any(p.get(k) not in (None, 'not_applicable') for k in
               ('in_kg_since', 'current_basis_in_kg', 'current_basis_until')):
            return finish('current_stay_profile_fact_conflict')
    elif (p.get('in_kg_since') != attestation['entered_on'] or
            p.get('current_basis_in_kg') != attestation['current_basis'] or
            p.get('current_basis_until') != attestation['lawful_until']):
        return finish('current_stay_profile_fact_conflict')
    if location == 'in_kg' and attestation['current_basis'] not in ('visa_free', 'visa'):
        return finish('current_basis_unknown_or_unsupported')
    active = published['active']
    if active is None: return finish('no_active_publication')
    version, bundle, projection = await context.source(active)
    result['source'] = dict(version_id=active, source_hash=version.source_hash, bundle_hash=version.bundle_hash,
        projection_hash=projection['projection_hash'], catalog_hash=projection['catalog_hash'],
        manifest_hash=_hash(published['manifests'][active]), publication_revision=len(published['rows']))
    if row.knowledge_version_id != active or any(authority[k] != result['source'][k] for k in
            ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash')):
        return finish('current_stay_source_changed')
    units = {u['unit_id']: u for u in bundle['units']}
    if any(r['unit_id'] not in units or r['unit_hash'] != _hash(units[r['unit_id']]) for r in authority['parameters']):
        return finish('current_stay_source_interpretation_changed')
    source = await publication._runtime_in_session(context, published, policy=publication_policy, ids=list(STOPS), at=now)
    unavailable = {r['unit_id'] for r in source['unavailable']}
    if location == 'abroad':
        result['checks'] = {k: _unknown('current_stay_source_unavailable') if uid in unavailable else
            dict(status='not_triggered', applicability='currently_abroad') for k, uid in zip(KEYS, STOPS)}
        return finish()
    until = attestation['lawful_until']
    if until is None:
        result['checks']['expired_stay'] = _unknown('actual_lawful_until_missing')
        result['checks']['working_day_margin'] = _unknown('actual_lawful_until_missing')
    else:
        until = date.fromisoformat(until)
        result['checks']['expired_stay'] = (_unknown('expired_stay_source_unavailable') if STOPS[0] in unavailable else
            dict(status='triggered' if until < today else 'not_triggered', applicability='applicable', lawful_until=until.isoformat()))
        c = authority['calendar']
        if STOPS[1] in unavailable:
            margin = _unknown('working_margin_source_unavailable')
        elif until < today:
            margin = dict(status='not_triggered', applicability='expired_instead')
        elif (calendars is None or calendars.content_hash != c['hash'] or
                any(y['completeness'] != 'complete' for y in calendars.describe()) or
                not c['valid_from'] <= on <= c['review_due_on']):
            margin = _unknown('approved_calendar_unavailable')
        else:
            margin = working_margin(today=today, until=until, calendars=calendars,
                include_today=c['include_today'], include_until=c['include_until'])
            if any(not c['valid_from'] <= d['date'] <= c['review_due_on'] for d in margin.get('days', [])):
                margin = _unknown('calendar_authority_does_not_cover_scan')
            result['calendar'] = dict(hash=calendars.content_hash, reference=c['reference'],
                include_today=c['include_today'], include_until=c['include_until'], status='separately_authorized_draft_data')
        result['checks']['working_day_margin'] = margin
    if attestation['current_basis'] == 'visa':
        result['checks']['visa_free_headroom'] = (_unknown('visa_free_stop_source_unavailable') if STOPS[2] in unavailable else
            dict(status='not_triggered', applicability='actual_non_visa_free_basis'))
        return finish()
    def vf_unknown(reason):
        result['checks']['visa_free_headroom'] = _unknown(reason)
        return finish()
    if STOPS[2] in unavailable: return vf_unknown('visa_free_stop_source_unavailable')
    if qualification_policy is None or qualification_policy.digest != authority['qualification_policy_hash']:
        return vf_unknown('current_stay_regime_authority_missing')
    qualification = qualification_policy.document
    if any(qualification[k] != result['source'][k] for k in ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash')):
        return vf_unknown('current_stay_regime_source_changed')
    if not qualification['valid_from'] <= on <= qualification['review_due_on']:
        return vf_unknown('current_stay_regime_authority_expired')
    error = assessment_rules.validate_regimes(authority, qualification, bundle, projection['payload']['catalog'])
    if error: return vf_unknown(error)
    facts = _conditions(attestation, p)
    if any(k not in facts or v != facts[k] for k, v in request.get('condition_facts', {}).items()):
        return vf_unknown('current_stay_condition_fact_conflict')
    result['applicability'] = assessment_rules.applicability(authority, facts)
    outcomes = result['applicability']
    if any(v['status'] == 'unknown' for v in outcomes.values()): return vf_unknown('competing_regime_facts_unknown')
    if any(v['status'] == 'met' and v['disposition'] == 'manual' for v in outcomes.values()):
        return vf_unknown('applicable_manual_regime_requires_specialist')
    matches = [k for k, v in outcomes.items() if v['status'] == 'met']
    if len(matches) != 1: return vf_unknown('competing_or_missing_regime')
    uid = matches[0]; counting = authority['counting']
    # The retained source schema represents named modes as a list parameter.
    # A single explicitly supported mode is required, not an arbitrary list.
    expected = dict(zip(COUNT_RULE_IDS, (counting['count_entry_day'], counting['count_exit_day'], [counting['window_anchor']])))
    if any(units[k]['value'] is None or type(units[k]['value'].get('value')) is not type(v) or
           units[k]['value']['value'] != v for k, v in expected.items()):
        return vf_unknown('current_stay_counting_source_unavailable_or_conflicting')
    required = sorted({k for k, v in outcomes.items() if v['disposition'] == 'executable'} | set(COUNT_RULE_IDS))
    ready = await publication._runtime_in_session(context, published, policy=publication_policy, ids=required, at=now)
    if ready['unavailable']: return vf_unknown('current_stay_regime_or_counting_unavailable')
    if history['status'] != 'recorded_inputs': return vf_unknown('personal_history_' + history['status'])
    if history['passport_ref'] != attestation['passport_ref'] or any(
            v['basis'] != 'visa_free' or v['passport_country'] != p.get('entry_passport_country') for v in intervals):
        return vf_unknown('personal_history_basis_or_passport_conflict')
    opened = [v for v in intervals if v['exit_date'] is None]
    if len(opened) != 1 or opened[0]['entry_date'] != attestation['entered_on']:
        return vf_unknown('personal_current_open_stay_conflict')
    ordered = sorted(intervals, key=lambda v: v['entry_date'])
    if any(b['entry_date'] <= (a['exit_date'] or on) for a, b in zip(ordered, ordered[1:])):
        return vf_unknown('personal_history_overlapping_visits')
    calculation = dict(schema_version='kg-stay-review-input/1', rule_unit_id=uid, as_of=on, history_complete=True,
        history=[dict(id=v['ref'], entry_date=v['entry_date'], exit_date=v['exit_date'], basis=v['basis'],
            passport_country=v['passport_country'], passport_continuity='same', confirmed=True) for v in intervals],
        trip=dict(mode='continue_open', start_date=on, end_date=on, passport_country=p['entry_passport_country'], basis='visa_free'),
        policy={'status': 'proposed', **{k: counting[k] for k in ('count_entry_day', 'count_exit_day', 'window_anchor', 'timezone')}})
    try:
        result['arithmetic'] = StayDayReview(**bundle, source_hash=version.source_hash).evaluate(calculation)
    except StayReviewError:
        return vf_unknown('observed_arithmetic_unsupported')
    result['checks']['visa_free_headroom'] = {**observed_headroom(result['arithmetic']), 'rule_unit_id': uid}
    return finish()
