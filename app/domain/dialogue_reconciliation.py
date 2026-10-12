"""Verify original attestation ancestry through actual durable client turns."""
from app.domain import dialogue_journal as journal, entry_applications as applications
from app.domain.entry_storage import _hash, _plain
from app.knowledge import dialogue_reconciliation as rules, interview_rules


async def verify_in_session(session, *, dialogue_session_id, policy, fact, interview, events,
                            state, profile, history, at):
    def deny(reason): return dict(status='unknown', reason=reason)
    registry = await journal.registry(session)
    header = next((r for r in registry if r.id == dialogue_session_id), None)
    if header is None: return deny('dialogue_session_missing')
    doc = _plain(header.document); _, assignment = journal.validate_header(header)
    if (header.interview_id != interview.id or header.case_id != interview.case_id or
        header.applicant_id != interview.applicant_id or _hash(doc['policy']) != policy.digest or
        _hash(doc['fact']) != fact.digest): return deny('dialogue_original_attestation_changed')
    on = applications._local_day(at).isoformat()
    if not policy.document['valid_from'] <= on <= policy.document['review_due_on']:
        return deny('dialogue_reconciliation_authority_expired')
    rows, current, _ = await journal.history(session, header, interview=interview, events=events)
    if current['head'] != journal.head(events[-1]) or current['stopped']:
        return deny('dialogue_unreconciled_interview_head')
    if rows and applications._utc(rows[-1].created_at) > applications._utc(at):
        return deny('dialogue_reconciliation_clock_reversed')
    analysis = interview_rules.analyze(state['answers'], on=on, language=state['language'],
        pre_consent=interview.policy['pre_consent'], catalog_document=_plain(interview.catalog))
    if state['phase'] != 'active' or state['collection_blocked'] or not analysis['consent_complete'] or analysis['stops']:
        return deny('dialogue_collection_not_active')
    if analysis['questions'] != _plain(state['drafts']):
        return deny('dialogue_questions_need_refresh')
    turns = {r.document['payload']['after']['hash']: r for r in rows if r.kind == 'turn' and
             r.document['payload']['parsed']['action'] == 'answer'}
    tail = [e for e in events if e.revision > doc['baseline']['revision']]
    if len(tail) != len(turns): return deny('dialogue_unreconciled_interview_tail')
    evidence = []
    for e in tail:
        turn = turns.get(e.snapshot_hash)
        if (e.action != 'answer' or turn is None or e.created_by != assignment['actor']):
            return deny('dialogue_unreconciled_interview_event')
        changes = _plain(e.command)['operation']['changes']
        error = rules.changed_fields(changes, answers=_plain(e.snapshot)['answers'], fact=fact.document,
            profile=profile, history=history, catalog_document=_plain(interview.catalog))
        if error: return deny(error)
        evidence.append(dict(event=journal.head(e), turn_hash=turn.snapshot_hash))
    proof = dict(status='verified', algorithm=rules.VERSION, map_hash=rules.MAP_HASH,
        authority_hash=policy.digest, session_id=header.id, session_hash=header.snapshot_hash,
        original_fact_hash=fact.digest, original_head=doc['baseline'], current_head=journal.head(events[-1]),
        tail=evidence, meaning='original_attestation_applicable_under_verified_changes_not_new_attestation')
    proof['evidence_hash'] = _hash(proof)
    return proof
