"""Same-session, role-scoped process evidence. Browser facts are never inputs.

Historical replay selects the immutable source prefix existing at recording time;
current readiness uses the current prefix and current configured policies.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain import entry_document_packages as packages
from app.domain import entry_issued as issued
from app.domain import applicant_profiles as profiles
from app.domain import applicant_stay_history as stays
from app.domain.entry_package_rules import summarize
from app.domain.entry_process_policy import AUTHORITATIVE, ROLES
from app.domain.entry_process_rules import fact_role, invalid
from app.domain.entry_storage import _hash
from app.domain.knowledge_review import _plain
from app.domain.models import EntryApplicant, EntryApplication, EntryDocumentPackageEvent, ServiceEvent, ServicePayment
from app.domain.service_money import balance_from_rows
from app.knowledge.process_preview import WORK_CATALOG_SHA256

SOURCE_COLUMNS = dict(application_event='application_event_id', package='package_event_id',
    issued='issued_id', profile='profile_id', attestation='attestation_id',
    payment='payment_id', contract='contract_event_id', stay='stay_history_id')
PACKAGE_FACTS = {'consent_confirmed', 'documents_accepted', 'documents_current', 'documents_received',
    'receiving_party_docs_accepted', 'resident_package_received', 'corrections_needed',
    'corrections_completed', 'product_defined'}
ISSUED_FACTS = {'issued_document_downloaded', 'issued_document_checked', 'delivered_to_client',
    'receipt_confirmed', 'actual_entry_confirmed', 'actual_exit_or_end_confirmed',
    'departure_confirmed', 'exit_visa_issued'}
OFFICIAL_ATTESTATIONS = {'permit_issued', 'resident_issued_and_collected',
    'registration_confirmed', 'registration_certificate_received', 'protocol_received'}


def row_hash(row):
    if hasattr(row, 'snapshot_hash'):
        return row.snapshot_hash
    # Legacy money/event journals have no stored hash; pin their complete data.
    payload = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, Decimal): value = str(value)
        elif hasattr(value, 'isoformat'): value = applications._utc(value)
        else: value = _plain(value)
        payload[column.name] = value
    return _hash(payload)


def pin(kind, row, app):
    result = dict(kind=kind, source_hash=row_hash(row), application_id=app.id, procedure=app.procedure)
    if kind != 'application': result[SOURCE_COLUMNS[kind]] = row.id
    return result


def packet(value=None, reason='evidence_unavailable', pins=()):
    return dict(value=value, reason=reason, pins=list(pins))


class Sources:
    """Validated source caches shared by all historical replay contexts."""
    def __init__(self, session, case, root):
        self.session, self.case, self.root = session, case, root
        self.apps = {root.id: root}
        self.events, self.packages, self.issued = {}, {}, {}
        self.documents = {}
        self.profile_rows = None
        self.stay_rows = None
        self.ledgers = {}
        self.successors = {}

    async def lock_apps(self, ids):
        for app_id in sorted(set(ids)):
            app = await applications._application(self.session, self.case.id, app_id, lock=True)
            if app.applicant_id != self.root.applicant_id: invalid('process_subject_mismatch')
            self.apps[app_id] = app
        await self.session.scalar(select(EntryApplicant).where(EntryApplicant.id == self.root.applicant_id)
            .with_for_update(of=EntryApplicant))

    async def app(self, app_id, role):
        app = self.apps.get(app_id)
        if app is None:
            app = await applications._application(self.session, self.case.id, app_id)
            self.apps[app_id] = app
        if app.applicant_id != self.root.applicant_id or app.procedure != ROLES[role]:
            invalid('process_dependency_scope')
        return app

    async def application_events(self, app):
        if app.id not in self.events:
            self.events[app.id] = await applications._events(self.session, app)
        return self.events[app.id]

    async def package_history(self, app):
        if app.id not in self.packages:
            history = await packages._history(self.session, app)
            from app.domain.entry_quarantine import metadata
            await metadata(self.session, app.id, history=history[:2])
            self.packages[app.id] = history
        return self.packages[app.id]

    async def issued_history(self, app):
        if app.id not in self.issued:
            approval = issued._approval(app, await self.application_events(app))
            self.issued[app.id] = (await issued._history(self.session, app, approval))[0]
        return self.issued[app.id]

    async def document_history(self, app):
        if app.id not in self.documents:
            self.documents[app.id] = (await packages.legacy_documents._history(self.session, app))[0]
        return self.documents[app.id]

    async def profile_history(self):
        if self.profile_rows is None:
            person = await applications._applicant(self.session, self.case.id, self.root.applicant_id)
            self.profile_rows = (await profiles._history(self.session, self.case, person))[0]
        return self.profile_rows

    async def stay_history(self):
        if self.stay_rows is None:
            person = await applications._applicant(self.session, self.case.id, self.root.applicant_id)
            self.stay_rows, _, _ = await stays._history(self.session, self.case, person)
        return self.stay_rows

    async def ledger(self, observed=None):
        # A later unbounded money journal must not erase bounded historical
        # evidence or prevent stopping a workflow. Historical reads fetch only
        # their exact scoped IDs; live reads retain the fail-closed size limit.
        key = None
        if observed is not None:
            ids = [observed.get(name) for name in ('payments', 'contracts')]
            if any(type(values) is not list or len(values) > 101 or
                   any(type(i) is not int or i < 1 for i in values) or
                   len(set(values)) != len(values) for values in ids):
                invalid('process_observation_invalid')
            key = tuple(tuple(values) for values in ids)
        if key not in self.ledgers:
            payments = select(ServicePayment).where(ServicePayment.case_id == self.case.id)
            contracts = select(ServiceEvent).where(ServiceEvent.case_id == self.case.id,
                ServiceEvent.event_type.in_(['contract_signed', 'contract_amount_corrected']))
            if key is not None:
                payments = payments.where(ServicePayment.id.in_(key[0]))
                contracts = contracts.where(ServiceEvent.id.in_(key[1]))
            money_rows = list((await self.session.scalars(payments.order_by(ServicePayment.id).limit(101))).all())
            contract_rows = list((await self.session.scalars(contracts.order_by(ServiceEvent.id).limit(101))).all())
            self.ledgers[key] = money_rows, contract_rows
        return self.ledgers[key]


class Evidence:
    def __init__(self, sources, state, process_rows, policy, package_policy, *, at, historical=False, observed=None):
        self.sources, self.state, self.process_rows = sources, state, process_rows
        self.policy, self.package_policy = policy, package_policy
        self.at, self.historical = at, historical
        self.day = applications._local_day(at)
        self.recorded = observed
        self.observed = {'streams':{}, 'quarantine':{}}
        self.rules_version = 2
        if historical:
            if (type(observed) is not dict or observed.keys() not in (
                {'streams','quarantine'}, {'streams','quarantine','rules_version'}) or
                any(type(observed[k]) is not dict for k in ('streams','quarantine'))):
                invalid('process_observation_invalid')
            if 'rules_version' in observed and (type(observed['rules_version']) is not int or observed['rules_version']!=2):
                invalid('process_observation_invalid')
            self.rules_version = observed.get('rules_version',1)
        # Old evidence replays its original interpretation; fresh observations
        # pin the dated-passport guard so their future replay stays identical.
        if self.rules_version==2: self.observed['rules_version']=2

    def prefix(self, rows, stream, field='created_at'):
        if self.historical:
            ids = self.recorded['streams'].get(stream)
            if type(ids) is not list or any(type(i) is not int for i in ids) or len(set(ids)) != len(ids):
                invalid('process_observation_invalid')
            selected = [r for r in rows if r.id in ids]
            if [r.id for r in selected] != ids: invalid('process_observed_source_missing')
            # These journals serialize revisions under their parent lock. An
            # observation may end before today's head, but cannot skip a revision.
            if (stream in ('profiles','stay_history') or stream.startswith(('events:', 'packages:', 'issued:', 'documents:'))) and \
                    ids != [r.id for r in rows[:len(ids)]]:
                invalid('process_observed_prefix_invalid')
            if any(applications._utc(getattr(r,field)) > applications._utc(self.at) for r in selected):
                invalid('process_source_from_future')
            if self.state['catalog_digest']==WORK_CATALOG_SHA256 and stream in ('stay_history','profiles'):
                expected=[r.id for r in rows if applications._utc(getattr(r,field))<=applications._utc(self.at)]
                if ids!=expected:invalid('process_observed_head_omitted')
        else:
            if any(applications._utc(getattr(r,field)) > applications._utc(self.at) for r in rows):
                invalid('process_source_from_future')
            selected = list(rows)
        self.observed['streams'][stream] = [r.id for r in selected]
        return selected

    async def app(self, role):
        app_id = self.state['links'].get(role)
        if app_id is None: return None
        app = await self.sources.app(app_id, role)
        if not self.prefix([app], f'identity:{app.id}'): invalid('process_source_from_future')
        return app

    async def events(self, app):
        rows = self.prefix(await self.sources.application_events(app), f'events:{app.id}')
        if not rows: invalid('process_source_from_future')
        return rows

    async def usable(self, app):
        events = await self.events(app)
        if app.id not in self.sources.successors:
            self.sources.successors[app.id] = list((await self.sources.session.scalars(select(EntryApplication)
                .where(EntryApplication.previous_id == app.id).limit(2))).all())
        return events[-1].status not in ('refused', 'closed') and not self.prefix(self.sources.successors[app.id], f'successors:{app.id}')

    async def quarantined(self, fingerprints):
        values = {v for v in fingerprints if v}
        if not values: return False
        key = _hash(sorted(values))
        if self.historical:
            result = self.recorded['quarantine'].get(key)
            if type(result) is not bool: invalid('process_observation_invalid')
            self.observed['quarantine'][key] = result
            return result
        column = EntryDocumentPackageEvent.command['request']['operation']['data']['fingerprint'].as_string()
        query = select(EntryDocumentPackageEvent.id).where(
            EntryDocumentPackageEvent.request_key.like('quarantine.%'), EntryDocumentPackageEvent.action == 'receive',
            column.in_(values)).limit(1)
        result = bool(await self.sources.session.scalar(query))
        self.observed['quarantine'][key] = result
        return result

    async def manual(self, role, fact, app):
        record = self.state['attestations'].get(role + '.' + fact)
        if record is None: return packet()
        row = next((r for r in self.process_rows if r.revision == record['event_revision']), None)
        if row is None: invalid('process_attestation_missing')
        if row.snapshot['links'].get(role) != app.id: invalid('process_attestation_scope')
        pins = [pin('attestation', row, app)]
        allowed = dict(self.policy.manual_sources).get(fact, ()) if self.policy else ()
        if record['source'] not in allowed: return packet(None, 'attestation_source_not_authorized', pins)
        if not record['on'] <= self.day.isoformat() <= record['valid_through']:
            return packet(None, 'attestation_expired', pins)
        if record['profile_id'] is not None:
            rows = self.prefix(await self.sources.profile_history(), 'profiles')
            if not rows or rows[-1].id != record['profile_id']:
                return packet(None, 'attestation_profile_changed', pins)
            pins.append(pin('profile', rows[-1], app))
        if fact in OFFICIAL_ATTESTATIONS:
            events = await self.events(app)
            pins.append(pin('application_event', events[-1], app))
            if events[-1].status != 'approved': return packet(False, 'official_approval_missing', pins)
        if fact == 'resident_registration_basis_reviewed':
            if role != 'resident_registration': return packet(None,'registration_basis_role_mismatch',pins)
            resident = await self.app('resident')
            if resident is None: return packet(None,'process_dependency_missing',pins)
            basis = record['basis']
            if not basis['registration_from']<=self.day.isoformat()<=basis['registration_until']:
                return packet(None,'resident_registration_period_not_current',pins)
            pins.append(pin('application',resident,resident))
            events = await self.events(resident)
            approval = events[-1]
            pins.append(pin('application_event',approval,resident))
            if (basis['application_id']!=resident.id or basis['approval_id']!=approval.id or
                    approval.status!='approved' or not await self.usable(resident) or
                    record['reference']!=approval.reference or record['source'] not in ('official_document','portal')):
                return packet(None,'resident_basis_changed',pins)
            registration = (await self.events(app))[-1]
            pins.append(pin('application_event',registration,app))
            if (registration.status!='approved' or registration.source not in ('official_document','portal') or
                    registration.occurred_on<approval.occurred_on or
                    applications._utc(registration.created_at)<applications._utc(approval.created_at) or
                    applications._utc(row.created_at)<applications._utc(registration.created_at) or
                    record['on']<registration.occurred_on.isoformat() or
                    basis['valid_from']<approval.occurred_on.isoformat()):
                return packet(None,'resident_registration_not_confirmed',pins)
        return packet(record['value'], 'recorded_attestation', pins)

    async def presence(self, app):
        rows = self.prefix(await self.sources.stay_history(),'stay_history')
        profile_rows = self.prefix(await self.sources.profile_history(),'profiles')
        pins = ([pin('stay',rows[-1],app)] if rows else []) + ([pin('profile',profile_rows[-1],app)] if profile_rows else [])
        evidence = stays._evidence(rows,profile_rows,self.at)
        if evidence['status']!='recorded_inputs': return packet(None,'personal_stay_not_current',pins)
        profile = _plain(profile_rows[-1].input_snapshot)
        facts = profile['profile']
        if profile['as_of']!=self.day.isoformat() or facts.get('current_location')!='in_kg':
            return packet(None,'personal_location_not_current',pins)
        intervals = evidence['document']['intervals']
        current = [item for item in intervals if item['exit_date'] is None]
        if (len(current)!=1 or current[0]['entry_date']>self.day.isoformat() or
                current[0]['passport_country']!=facts.get('entry_passport_country') or
                current[0]['entry_date']!=facts.get('in_kg_since') or
                current[0]['basis']!=facts.get('current_basis_in_kg')):
            return packet(None,'personal_open_stay_unresolved',pins)
        ordered=sorted(intervals,key=lambda item:item['entry_date'])
        if any(b['entry_date']<=(a['exit_date'] or self.day.isoformat()) for a,b in zip(ordered,ordered[1:])):
            return packet(None,'personal_stay_overlaps',pins)
        # Recorded actual presence only. Neither basis legality nor permission
        # to remain/work is inferred from this observation.
        return packet(True,'recorded_personal_presence_only',pins)

    async def package(self, app, fact, *, edge=None):
        rows, states, definitions, _ = await self.sources.package_history(app)
        prefix = self.prefix(rows, f'packages:{app.id}')
        if not prefix: return packet()
        row = prefix[-1]
        index = next(i for i, source in enumerate(rows) if source.id == row.id)
        state, definition = states[index], definitions[index]
        pins = [pin('package', row, app)]
        if fact == 'consent_confirmed':
            return packet(bool(state['consent'] and state['consent']['status'] == 'granted'), 'package_consent', pins)
        if fact == 'product_defined': return packet(True, 'explicit_package_product', pins)
        passport_on = None
        if self.rules_version==2:
            legacy = self.prefix(await self.sources.document_history(app), f'documents:{app.id}')
            passport_on = packages._passport_date(prefix,states[:index+1],legacy)
        report = summarize(state, definition, passport_changed_on=passport_on)
        required = [r for r in report['rows'] if r['applicable'] is True and r['kind'] not in ('recommended', 'practice')]
        unknown = bool(report['counts']['applicability_unknown'])
        if fact in ('documents_received', 'resident_package_received'):
            received = bool(required) and all(r['status'] not in ('missing', 'withdrawn') and r['fingerprint'] for r in required)
            return packet(None if unknown else bool(received), 'package_receipts', pins)
        accepted = packages.effective_acceptance(state, definition, self.package_policy, day=self.day,
            passport_changed_on=passport_on)
        quarantined = await self.quarantined({item['fingerprint'] for item in state['items'].values() if item['status'] != 'withdrawn'})
        valid = accepted['accepted'] and not packages._legacy_passport_gap(prefix, states[:index+1]) and not quarantined
        reason = 'document_in_quarantine' if quarantined else accepted['reason']
        if fact == 'corrections_needed':
            problems = any(r['effective_status'] in ('recheck', 'correction') for r in required)
            value = True if problems or quarantined else False if valid else None
        else: value = bool(valid)
        if fact == 'corrections_completed' and edge and edge['proposed_effect'] == 'same_attempt_resubmission':
            returns = [r for r in await self.events(app) if r.status == 'revision_requested']
            approvals = [r for r in prefix if r.action == 'approve']
            if returns: pins.append(pin('application_event', returns[-1], app))
            value = bool(valid and returns and approvals and
                applications._utc(approvals[-1].created_at) > applications._utc(returns[-1].created_at))
            if not value: reason = 'corrections_reacceptance_required'
        return packet(value, reason, pins)

    async def issued_fact(self, app, fact):
        if app.procedure not in ('visa', 'exit_visa'): return packet(None, 'issued_adapter_unsupported')
        rows = self.prefix(await self.sources.issued_history(app), f'issued:{app.id}')
        if not rows: return packet()
        row = rows[-1]; view = issued._view(row,rules_version=self.rules_version); state = view['snapshot']; report = view['summary']
        pins = [pin('issued', row, app)]
        quarantined = await self.quarantined({state.get('fingerprint'), state.get('current_passport'), state.get('issued_passport')})
        if fact == 'issued_document_downloaded': value = state['version'] > 0
        elif fact in ('actual_entry_confirmed', 'actual_exit_or_end_confirmed', 'departure_confirmed'):
            direction = 'entry' if fact == 'actual_entry_confirmed' else 'exit'
            value = any(f['direction'] == direction for f in state['travel'])
        else:
            key = {'issued_document_checked':'verification_current', 'delivered_to_client':'delivery_complete',
                'receipt_confirmed':'receipt_current_and_checked', 'exit_visa_issued':'verification_current'}[fact]
            value = report[key] and not quarantined
            if fact == 'exit_visa_issued': value = value and app.procedure == 'exit_visa'
        return packet(bool(value), 'issued_journal', pins)

    async def payment(self, app):
        if self.policy is None or app.procedure not in self.policy.full_case_payment_procedures:
            return packet(None, 'case_payment_applicability_unapproved')
        all_money, all_contracts = await self.sources.ledger(self.recorded['streams'] if self.historical else None)
        money = self.prefix(all_money, 'payments', 'recorded_at'); contracts = self.prefix(all_contracts, 'contracts', 'recorded_at')
        # Corrective edges may record an unknown retained prerequisite. Preserve
        # a bounded 101-row witness so this overflow remains replayable later;
        # it proves only the limit, never a paid balance.
        if len(money) > 100 or len(contracts) > 100:
            return packet(None, 'process_money_evidence_limit')
        if not contracts: return packet(None, 'contract_evidence_missing')
        contract = contracts[-1]; payload = _plain(contract.payload)
        pins = [pin('contract', contract, app)] + [pin('payment', r, app) for r in money]
        try:
            amount = Decimal(payload['amount']) if payload.get('amount') is not None else None
            currency = payload.get('currency')
            if amount is not None and (not amount.is_finite() or amount <= 0): raise ValueError
            if type(currency) is not str or len(currency) != 3: raise ValueError
        except (InvalidOperation, ValueError, TypeError): return packet(None, 'contract_evidence_invalid', pins)
        if not self.historical and (amount != self.sources.case.agreed_amount or currency != self.sources.case.currency):
            return packet(None, 'contract_evidence_changed', pins)
        ids = {r.id for r in money}
        if any((r.corrects_id is not None and r.corrects_id not in ids) or
               (r.settles_id is not None and r.settles_id not in ids) for r in money):
            return packet(None, 'payment_evidence_scope', pins)
        balance = balance_from_rows(SimpleNamespace(agreed_amount=amount, currency=currency), money)
        ready = amount is not None and balance.outstanding == 0 and not balance.needs_attention
        return packet(bool(ready), 'full_case_reconciled_balance', pins)

    async def resolve(self, role, fact, *, edge=None):
        app = await self.app(role)
        if app is None: return packet(None, 'process_dependency_missing')
        base = [pin('application', app, app)]
        if fact == 'identity': return packet(True, 'scoped_application', base)
        events = await self.events(app)
        if fact != 'decision' and not await self.usable(app):
            return packet(None, 'application_attempt_terminal', base + [pin('application_event', events[-1], app)])
        if fact=='actual_presence_confirmed': result = await self.presence(app)
        elif fact in PACKAGE_FACTS: result = await self.package(app, fact, edge=edge)
        elif fact in ISSUED_FACTS: result = await self.issued_fact(app, fact)
        elif fact == 'service_payment_confirmed': result = await self.payment(app)
        elif fact == 'profile_complete': result = await self.manual(role, 'profile_review_complete', app)
        elif fact in ('decision', 'submission_recorded', 'application_reference_recorded'):
            selected = events[-1]
            if fact == 'decision': value = {'submitted':'pending'}.get(selected.status, selected.status)
            elif fact == 'application_reference_recorded': value = bool(selected.reference)
            else:
                submitted = [r for r in events if r.status == 'submitted']
                selected = submitted[-1] if submitted else events[-1]
                value = bool(submitted)
                if edge and edge['proposed_effect'] == 'same_attempt_resubmission':
                    returns = [r for r in events if r.status == 'revision_requested']
                    value = bool(submitted and returns and submitted[-1].revision > returns[-1].revision)
            result = packet(value, 'application_journal', [pin('application_event', selected, app)])
        elif fact in AUTHORITATIVE: result = packet(None, 'authoritative_adapter_unavailable')
        else: result = await self.manual(role, fact, app)
        result['pins'] = base + result['pins']
        return result

    async def transition(self, edge):
        required = {fact_role(self.state, edge, fact) + '.' + fact for fact in edge['requires']}
        required.update(self.state['retained'])
        result = {}
        for key in sorted(required):
            role, fact = key.split('.', 1)
            result[key] = await self.resolve(role, fact, edge=edge)
        return result
