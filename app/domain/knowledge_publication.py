"""Evidence-bound publication and per-rule runtime reads; no implicit authority."""
from datetime import timezone

from sqlalchemy import select, update, union

from app.domain import entry_applications as transactions, knowledge_decisions as decisions
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key, _plain
from app.domain.knowledge_projection import verify_projection
from app.domain.knowledge_publication_rules import PublicationPolicy, authorize_publisher, unavailable_reasons
from app.domain.models import (EntryApplicantProfile, EntryCalculation, EntryDeadlineRevision, EntryQualification,
    KnowledgeProjection, KnowledgePublicationEvent, KnowledgePublicationUnit, KnowledgeSet, KnowledgeVersion,
    Product, ServiceCase, _now)
from app.knowledge.projection import build_projection
from app.knowledge.review import canonical, compare_snapshots

MAX_REVISIONS = 250
MAX_BYTES = 16 * 1024 * 1024
ACTIONS = ('review', 'approve', 'activate', 'rollback', 'withdraw')


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _identifiers(values, maximum=5000):
    if type(values) is not list or not 1 <= len(values) <= maximum:
        raise EntryStorageInvalid('invalid_publication_selection')
    for identifier in values:
        decisions._unit_id(identifier)
    if len(set(values)) != len(values):
        raise EntryStorageInvalid('invalid_publication_selection')
    return sorted(values)


def _policy(policy):
    return dict(reference=policy.reference, fingerprint=policy.fingerprint, publishers=list(policy.publishers))


def _payload(row):
    return {**{key: _plain(getattr(row, key)) for key in ('set_id', 'version_id', 'revision', 'previous_id',
        'action', 'request_key', 'request_hash', 'command', 'snapshot', 'created_by')},
        'created_at': transactions._utc(row.created_at)}


def _view(row):
    return dict(id=row.id, revision=row.revision, version_id=row.version_id, action=row.action,
                snapshot_hash=row.snapshot_hash, manifest_hash=_hash(_plain(row.snapshot)),
                created_by=row.created_by, created_at=transactions._utc(row.created_at))


class _Context:
    def __init__(self, session, target):
        self.session = session
        self.target = target
        self.versions = {}
        self.decisions = {}

    async def source(self, version_id):
        if version_id not in self.versions:
            version, bundle = await decisions._version(self.session, version_id)
            if version.set_id != self.target.id:
                raise EntryStorageInvalid('publication_version_scope')
            projection = await self.session.get(KnowledgeProjection, version_id)
            if projection is None:
                raise EntryStorageInvalid('publication_projection_missing')
            expected = build_projection(bundle, _plain(projection.condition_catalog))
            await verify_projection(self.session, version_id, expected)
            self.versions[version_id] = (version, bundle, expected)
        return self.versions[version_id]

    async def reviews(self, version_id, unit):
        key = (version_id, unit['unit_id'])
        if key not in self.decisions:
            version, _, _ = await self.source(version_id)
            self.decisions[key] = (await decisions._history(self.session, version, unit))[0]
        return self.decisions[key]

    async def manifest(self, version_id, unit_ids, *, at=None):
        version, bundle, projection = await self.source(version_id)
        entries = []
        for identifier in unit_ids:
            unit = decisions._unit(bundle, identifier)
            rows = await self.reviews(version_id, unit)
            if at is not None:
                rows = [row for row in rows if _utc(row.created_at) <= _utc(at)]
            review = rows[-1] if rows else None
            entries.append(dict(unit_id=identifier, unit_hash=_hash(unit), decision_id=review.id if review else None,
                                decision_hash=review.snapshot_hash if review else None))
        return dict(bundle_hash=version.bundle_hash, projection_hash=projection['projection_hash'],
                    catalog_hash=projection['catalog_hash'], units=entries)

    async def availability(self, version_id, manifest, *, at):
        _, bundle, _ = await self.source(version_id)
        result = []
        for entry in manifest['units']:
            unit = decisions._unit(bundle, entry['unit_id'])
            rows = await self.reviews(version_id, unit)
            relevant = [row for row in rows if _utc(row.created_at) <= _utc(at)]
            latest = relevant[-1] if relevant else None
            reasons = unavailable_reasons(unit, decisions._view(latest) if latest else None,
                                          day=transactions._local_day(at), now=_utc(at))
            if (latest.id if latest else None) != entry['decision_id']:
                reasons.append('review_changed_since_approval')
            result.append(dict(unit_id=entry['unit_id'], reasons=reasons))
        return result


def _transition(states, manifests, releases, active, action, version_id, manifest):
    state = states.get(version_id, 'draft')
    if action == 'review':
        if state == 'active':
            raise EntryStorageConflict('active_version_requires_new_import')
        states[version_id] = 'review'
        manifests[version_id] = manifest
    else:
        if manifests.get(version_id) != manifest:
            raise EntryStorageConflict('publication_manifest_changed')
        if action == 'approve':
            if state != 'review':
                raise EntryStorageConflict('publication_requires_review')
            states[version_id] = 'approved'
        elif action in ('activate', 'rollback'):
            if (action == 'activate' and state != 'approved' or
                action == 'rollback' and (state != 'retired' or version_id not in releases)):
                raise EntryStorageConflict('publication_requires_approval')
            if active is not None:
                states[active] = 'retired'
            states[version_id] = 'active'
            active = version_id
            releases.add(version_id)
        elif action == 'withdraw':
            if state != 'active' or active != version_id:
                raise EntryStorageConflict('publication_requires_active_version')
            states[version_id] = 'retired'
            active = None
    return active


async def _history(context):
    session, target = context.session, context.target
    rows = list((await session.scalars(select(KnowledgePublicationEvent).where(
        KnowledgePublicationEvent.set_id == target.id).order_by(KnowledgePublicationEvent.revision)
        .limit(MAX_REVISIONS + 1))).all())
    if len(rows) > MAX_REVISIONS:
        raise EntryStorageInvalid('publication_history_limit')
    states = {}; manifests = {}; releases = set(); policies = {}; active = None; previous = None; size = 0
    for revision, row in enumerate(rows, 1):
        command = _plain(row.command); manifest = _plain(row.snapshot)
        try:
            policy = PublicationPolicy(command['policy']['reference'], command['policy']['fingerprint'],
                                       tuple(command['policy']['publishers']))
            ids = _identifiers(command['unit_ids'])
            expected = dict(version_id=row.version_id, action=row.action, expected_revision=revision-1,
                unit_ids=ids, manifest_hash=_hash(manifest), actor=row.created_by, policy=_policy(policy))
            if (row.action not in ACTIONS or row.created_by not in policy.publishers or row.command != expected or
                row.revision != revision or row.previous_id != (previous.id if previous else None) or
                previous and (row.id <= previous.id or _utc(row.created_at) < _utc(previous.created_at)) or row.request_hash != _hash(expected) or
                row.snapshot_hash != _hash(_payload(row))):
                raise ValueError
            # Preserve historical evidence even after later expiry or rejection.
            historical = await context.manifest(row.version_id, ids, at=row.created_at)
            if row.action != 'withdraw' and historical != manifest:
                raise ValueError
            if row.action in ('approve', 'activate', 'rollback'):
                availability = await context.availability(row.version_id, manifest, at=row.created_at)
                if any(item['reasons'] for item in availability):
                    raise ValueError
            if row.action in ('approve', 'activate', 'rollback') and policies.get(row.version_id) != _policy(policy):
                raise ValueError
            if row.action == 'review':
                policies[row.version_id] = _policy(policy)
            active = _transition(states, manifests, releases, active, row.action, row.version_id, manifest)
            links = list((await session.scalars(select(KnowledgePublicationUnit).where(
                KnowledgePublicationUnit.event_id == row.id).order_by(KnowledgePublicationUnit.unit_id).limit(5001))).all())
            actual = [{key: getattr(link, key) for key in ('unit_id', 'unit_hash', 'decision_id', 'decision_hash')} for link in links]
            if actual != manifest['units'] or any(link.version_id != row.version_id for link in links):
                raise ValueError
        except (KeyError, TypeError, ValueError, EntryStorageConflict):
            raise EntryStorageInvalid('publication_history_integrity_failed') from None
        size += len(canonical(_payload(row)).encode())
        if size > MAX_BYTES:
            raise EntryStorageInvalid('publication_history_limit')
        previous = row
    versions = list((await session.scalars(select(KnowledgeVersion).where(KnowledgeVersion.set_id == target.id))).all())
    if target.active_version_id != active or any(v.status != states.get(v.id, 'draft') for v in versions):
        raise EntryStorageInvalid('publication_projection_integrity_failed')
    return dict(rows=rows, size=size, states=states, manifests=manifests, releases=releases, policies=policies, active=active)


async def _context(session, version_id, *, write=False):
    version, _ = await decisions._version(session, version_id, lock=write)
    target = await session.get(KnowledgeSet, version.set_id)
    return _Context(session, target)


async def publication_preview(engine, *, actor, version_id, unit_ids):
    _authorize(actor); _id(version_id); ids = _identifiers(unit_ids)
    async def read(session):
        context = await _context(session, version_id)
        history = await _history(context)
        version, bundle, _ = await context.source(version_id)
        manifest = await context.manifest(version_id, ids)
        availability = await context.availability(version_id, manifest, at=_now())
        active_availability = (await context.availability(version_id, history['manifests'][version_id], at=_now())
                               if history['active'] == version_id else None)
        baseline = (await context.source(history['active']))[1] if history['active'] else None
        diff = compare_snapshots(baseline, bundle)
        compared_versions = {version_id, history['active']} - {None}
        queries = [select(EntryDeadlineRevision.case_id).where(EntryDeadlineRevision.knowledge_version_id.in_(compared_versions)),
                   select(EntryApplicantProfile.case_id).where(EntryApplicantProfile.knowledge_version_id.in_(compared_versions))]
        for model in (EntryQualification, EntryCalculation):
            queries.append(select(ServiceCase.id).join(Product, Product.id == ServiceCase.product_id)
                .join(model, model.contact_id == ServiceCase.contact_id).where(model.knowledge_version_id.in_(compared_versions),
                    Product.direction == 'visa', ServiceCase.outcome.is_(None)))
        affected = list((await session.scalars(union(*queries).order_by('case_id').limit(51))).all())
        return dict(version=dict(id=version.id, number=version.version, status=version.status),
            current_revision=len(history['rows']), active_version_id=history['active'], manifest=manifest,
            manifest_hash=_hash(manifest), availability=availability, selected_count=len(ids),
            excluded_count=len(bundle['units'])-len(ids), affected_case_ids=affected[:50], affected_has_more=len(affected)>50,
            lifecycle_manifest=history['manifests'].get(version_id),
            lifecycle_manifest_hash=_hash(history['manifests'][version_id]) if version_id in history['manifests'] else None,
            active_availability=active_availability,
            diff=diff,
            history=[_view(row) for row in reversed(history['rows'])])
    return await transactions._run(engine, read)


async def publish_knowledge(engine, *, actor, policy, version_id, action, expected_revision, request_key,
                            unit_ids, manifest_hash):
    authorize_publisher(actor, policy); _id(version_id); _key(request_key); ids = _identifiers(unit_ids)
    if (action not in ACTIONS or type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISIONS or
        not isinstance(manifest_hash, str) or len(manifest_hash) != 64):
        raise EntryStorageInvalid('invalid_publication_command')
    command = dict(version_id=version_id, action=action, expected_revision=expected_revision, unit_ids=ids,
                   manifest_hash=manifest_hash, actor=actor.manager_id, policy=_policy(policy))
    async def write(session):
        context = await _context(session, version_id, write=True)
        history = await _history(context)
        old = next((row for row in history['rows'] if row.request_key == request_key), None)
        if old:
            if old.request_hash != _hash(command):
                raise EntryStorageConflict('publication_request_reused')
            return _view(old)
        if len(history['rows']) != expected_revision:
            raise EntryStorageConflict('publication_revision_changed')
        manifest = (history['manifests'].get(version_id) if action == 'withdraw' else
                    await context.manifest(version_id, ids))
        if manifest is None or _hash(manifest) != manifest_hash or [u['unit_id'] for u in manifest['units']] != ids:
            raise EntryStorageConflict('publication_manifest_changed')
        occurred_at = _now()
        if history['rows'] and _utc(occurred_at) < _utc(history['rows'][-1].created_at):
            raise EntryStorageInvalid('publication_clock_before_history')
        if action in ('approve', 'activate', 'rollback'):
            if history['policies'].get(version_id) != _policy(policy):
                raise EntryStorageConflict('publication_policy_changed')
            if any(item['reasons'] for item in await context.availability(version_id, manifest, at=occurred_at)):
                raise EntryStorageInvalid('publication_rules_unavailable')
        active = _transition(history['states'], history['manifests'], history['releases'], history['active'],
                             action, version_id, manifest)
        row = KnowledgePublicationEvent(set_id=context.target.id, version_id=version_id, revision=expected_revision+1,
            previous_id=history['rows'][-1].id if history['rows'] else None, action=action, request_key=request_key,
            request_hash=_hash(command), command=command, snapshot=manifest, created_by=actor.manager_id, created_at=occurred_at)
        if history['size'] + len(canonical(_payload(row)).encode()) > MAX_BYTES:
            raise EntryStorageInvalid('publication_history_limit')
        row.snapshot_hash = _hash(_payload(row)); session.add(row); await session.flush()
        session.add_all(KnowledgePublicationUnit(event_id=row.id, version_id=version_id, **unit) for unit in manifest['units'])
        # Lifecycle projection only, deliberately separate from immutable source bodies.
        old_active = history['active']
        if old_active is not None and old_active != active:
            await session.execute(update(KnowledgeVersion.__table__).where(KnowledgeVersion.id == old_active).values(status='retired'))
        await session.execute(update(KnowledgeVersion.__table__).where(KnowledgeVersion.id == version_id)
                              .values(status=history['states'][version_id]))
        await session.execute(update(KnowledgeSet.__table__).where(KnowledgeSet.id == context.target.id)
                              .values(active_version_id=active))
        await session.flush()
        return _view(row)
    return await transactions._run(engine, write)


async def runtime_knowledge(engine, *, actor, policy, unit_ids):
    """Trusted internal adapter. Every caller still needs its existing admin authorization."""
    _authorize(actor); ids = _identifiers(unit_ids, maximum=100)
    async def read(session):
        target = await session.scalar(select(KnowledgeSet).where(KnowledgeSet.code == 'kg_entry')
            .with_for_update(read=True, of=KnowledgeSet))
        if target is None or (target.jurisdiction, target.domain) != ('KG', 'entry'):
            raise EntryStorageInvalid('knowledge_set_unavailable')
        context = _Context(session, target); history = await _history(context)
        active = history['active']
        if active is None:
            return dict(version_id=None, available=[], unavailable=[dict(unit_id=i, reasons=['no_active_publication']) for i in ids])
        manifest = history['manifests'][active]
        version, bundle, _ = await context.source(active)
        availability = {item['unit_id']: item['reasons'] for item in await context.availability(active, manifest, at=_now())}
        available = []; unavailable = []
        policy_matches = isinstance(policy, PublicationPolicy) and history['policies'][active] == _policy(policy)
        for identifier in ids:
            reasons = list(availability.get(identifier, ['unit_not_published']))
            if not policy_matches:
                reasons.append('publication_policy_unavailable_or_changed')
            if reasons:
                unavailable.append(dict(unit_id=identifier, reasons=reasons))
            else:
                unit = decisions._unit(bundle, identifier)
                available.append(dict(unit_id=identifier, value=unit['value'], title=unit['title'], source_ref=unit['source_ref'],
                    page=unit['page'], section=unit['section'], unit_hash=_hash(unit), bundle_hash=version.bundle_hash,
                    manifest_hash=_hash(manifest), version_id=active))
        return dict(version_id=active, available=available, unavailable=unavailable)
    return await transactions._run(engine, read)
