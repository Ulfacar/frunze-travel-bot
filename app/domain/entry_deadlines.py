"""Owned immutable deadline revisions and explicit manual evidence, without sending."""
from copy import deepcopy
import hashlib
from pathlib import Path

from sqlalchemy import select

from app.domain import entry_applications as applications, entry_deadline_sources as sources
from app.domain.entry_calculations import _bundle, _sources, _runtime as calculation_runtime
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key, _plain
from app.domain.models import EntryDeadlineRevision, KnowledgeImport, KnowledgeSet, KnowledgeVersion, WorkCalendar, _now
from app.knowledge.review import canonical

MAX_REVISIONS = 250
MAX_BYTES = 4 * 1024 * 1024
MAX_TRACKS = 64


def _runtime():
    return dict(calculation=calculation_runtime('deadline'), binding=_hash({name:hashlib.sha256(
        Path(path).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
        for name,path in (('sources',sources.__file__),('storage',__file__))}))


def _command(case_id, application_id, rule, revision, operation, actor):
    return dict(case_id=case_id, application_id=application_id, rule_unit_id=rule,
                expected_revision=revision, operation=operation, actor=actor)


def _payload(row):
    fields = ('case_id','application_id','rule_unit_id','knowledge_version_id','anchor_event_id','anchor_issued_id',
              'revision','previous_id','request_key','request_hash','command','snapshot','created_by')
    return {**{key:_plain(getattr(row,key)) for key in fields}, 'created_at':applications._utc(row.created_at)}


def _anchor_columns(snapshot):
    selected = snapshot['selection']['anchor']
    return (selected['id'] if selected and selected['kind']=='application_event' else None,
            selected['id'] if selected and selected['kind']=='travel' else None)


def _manual_change(snapshot, operation, actor):
    if snapshot is None:
        raise EntryStorageInvalid('deadline_source_required')
    result = deepcopy(snapshot)
    if operation['action']=='manual':
        if operation['data']['reason']=='corrected_date' and snapshot['manual'] is None:
            raise EntryStorageInvalid('deadline_previous_manual_required')
        result['manual'] = {**operation['data'], 'actor':actor}
    else:
        if snapshot['manual'] is None:
            raise EntryStorageInvalid('deadline_manual_missing')
        result['manual'] = None
    return result


async def _verify_sources(session, case, application, rule_id, snapshot):
    data = snapshot['selection']
    bundle, _, _, _, provenance = await _sources(session,case.contact_id,data['knowledge_version_id'],None,data['calendar_ids'])
    rule = next((r for r in bundle['units'] if r['unit_id']==rule_id and r['kind']=='deadline'),None)
    if (rule is None or snapshot['source']!=provenance or snapshot['rule_hash']!=_hash(rule) or
        snapshot['application_hash']!=application.snapshot_hash or snapshot['source_label']!=bundle['meta']['version_label'] or snapshot['publication_approved'] is not False or
        snapshot['may_quote'] is not False):
        raise EntryStorageInvalid('deadline_sources_changed')
    current = await sources.actual_anchor(session,application,data['anchor'])
    old = snapshot['anchor']
    if (current is None)!=(old is None) or current is not None and (
        {k:v for k,v in current.items() if k!='superseded'}!={k:v for k,v in old.items() if k!='superseded'}):
        raise EntryStorageInvalid('deadline_anchor_changed')
    return bool(current and current['superseded'])


async def _history(session, case, application, rule):
    rows = list((await session.scalars(select(EntryDeadlineRevision).where(
        EntryDeadlineRevision.application_id==application.id,EntryDeadlineRevision.rule_unit_id==rule)
        .order_by(EntryDeadlineRevision.revision).limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS:
        raise EntryStorageInvalid('deadline_history_limit')
    size=0
    previous=None
    stale={}
    verified={}
    for revision,row in enumerate(rows,1):
        snapshot=_plain(row.snapshot)
        operation=sources.normalize(_plain(row.command)['operation'],cutoff=applications._local_day(row.created_at))
        command=_command(case.id,application.id,rule,revision-1,operation,row.created_by)
        payload=_payload(row)
        size+=len(canonical(payload).encode())
        if size>MAX_BYTES:
            raise EntryStorageInvalid('deadline_history_limit')
        if (row.case_id!=case.id or row.revision!=revision or row.command!=command or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(payload) or
            row.knowledge_version_id!=snapshot['selection']['knowledge_version_id'] or
            (row.anchor_event_id,row.anchor_issued_id)!=_anchor_columns(snapshot)):
            raise EntryStorageInvalid('deadline_integrity_failed')
        if operation['action']=='recalculate':
            if snapshot['selection']!=operation['data'] or snapshot['manual'] is not None:
                raise EntryStorageInvalid('deadline_integrity_failed')
        elif snapshot!=_manual_change(_plain(previous.snapshot) if previous else None,operation,row.created_by):
            raise EntryStorageInvalid('deadline_integrity_failed')
        identity=_hash({k:v for k,v in snapshot.items() if k!='manual'})
        if identity not in verified:
            verified[identity]=await _verify_sources(session,case,application,rule,snapshot)
        stale[row.id]=verified[identity]
        previous=row
    return rows,size,stale


def _view(row, *, stale=False):
    snapshot=_plain(row.snapshot)
    summary=sources.summary(snapshot)
    if stale:
        summary.update(status='anchor_changed',operational_due_on=None,
                       blockers=list(dict.fromkeys([*summary['blockers'],'actual_anchor_superseded'])))
    return dict(id=row.id,revision=row.revision,created_by=row.created_by,created_at=applications._utc(row.created_at),
        snapshot_hash=row.snapshot_hash,snapshot=snapshot,operation=_plain(row.command)['operation'],summary=summary)


async def record_deadline_operation(engine, *, actor, case_id, application_id, rule_unit_id,
                                    expected_revision, request_key, operation):
    _authorize(actor)
    _id(case_id);_id(application_id);_key(request_key);sources.unit_id(rule_unit_id)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS:
        raise EntryStorageInvalid('invalid_deadline_revision')
    operation=sources.normalize(operation,cutoff=applications._today())
    command=_command(case_id,application_id,rule_unit_id,expected_revision,operation,actor.manager_id)
    async def write(session):
        case=await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id,lock=True)
        rows,size,stale=await _history(session,case,application,rule_unit_id)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('deadline_request_key_reused')
            return _view(old,stale=stale[old.id])
        if len(rows)!=expected_revision:raise EntryStorageConflict('deadline_revision_changed')
        previous=rows[-1] if rows else None
        if previous is None:
            tracks=(await session.scalars(select(EntryDeadlineRevision.rule_unit_id).where(
                EntryDeadlineRevision.application_id==application_id).distinct().limit(MAX_TRACKS))).all()
            if len(tracks)>=MAX_TRACKS:raise EntryStorageInvalid('deadline_track_limit')
        if operation['action']=='recalculate':
            snapshot=await sources.calculate_bound_deadline(session,case,application,rule_unit_id,operation['data'])
            snapshot['runtime']=_runtime()
        else:
            if previous and stale[previous.id] and operation['action']=='manual':
                raise EntryStorageInvalid('deadline_recalculation_required')
            snapshot=_manual_change(_plain(previous.snapshot) if previous else None,operation,actor.manager_id)
        event_id,issued_id=_anchor_columns(snapshot)
        row=EntryDeadlineRevision(case_id=case_id,application_id=application_id,rule_unit_id=rule_unit_id,
            knowledge_version_id=snapshot['selection']['knowledge_version_id'],anchor_event_id=event_id,anchor_issued_id=issued_id,
            revision=len(rows)+1,previous_id=previous.id if previous else None,request_key=request_key,
            request_hash=_hash(command),command=command,snapshot=snapshot,created_by=actor.manager_id,created_at=_now())
        payload=_payload(row)
        if size+len(canonical(payload).encode())>MAX_BYTES:raise EntryStorageInvalid('deadline_history_limit')
        row.snapshot_hash=_hash(payload);session.add(row);await session.flush()
        return _view(row,stale=bool(snapshot['anchor'] and snapshot['anchor']['superseded']))
    return await applications._run(engine,write)


async def read_deadline_history(engine, *, actor, case_id, application_id, rule_unit_id, revision=None, replay=False):
    _authorize(actor)
    _id(case_id);_id(application_id);sources.unit_id(rule_unit_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS):
        raise EntryStorageInvalid('invalid_deadline_revision')
    if type(replay) is not bool:raise EntryStorageInvalid('invalid_deadline_replay')
    async def read(session):
        case=await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        rows,_,stale=await _history(session,case,application,rule_unit_id)
        row=next((r for r in rows if r.revision==revision),None) if revision else rows[-1] if rows else None
        if revision and row is None:raise EntryStorageInvalid('deadline_revision_unavailable')
        if row and replay:
            snapshot=_plain(row.snapshot)
            if snapshot['runtime']!=_runtime():raise EntryStorageInvalid('deadline_replay_runtime_changed')
            data=snapshot['selection']
            bundle,calendars,_,_,provenance=await _sources(session,case.contact_id,data['knowledge_version_id'],None,data['calendar_ids'])
            rule=next(r for r in bundle['units'] if r['unit_id']==rule_unit_id)
            expected=sources.build_snapshot(bundle,calendars,provenance,application.snapshot_hash,rule,data,snapshot['anchor'])
            expected.update(runtime=snapshot['runtime'],manual=snapshot['manual'])
            if expected!=snapshot:raise EntryStorageInvalid('deadline_replay_result_changed')
        return dict(application=applications._application_view(application),rule_unit_id=rule_unit_id,
            current_revision=len(rows),selected=_view(row,stale=stale[row.id]) if row else None,
            history=[dict(revision=r.revision,created_by=r.created_by,created_at=applications._utc(r.created_at),
                          action=r.command['operation']['action']) for r in reversed(rows)])
    return await applications._run(engine,read)


async def read_deadline_options(engine, *, actor, case_id, application_id, knowledge_version_id=None, pinned_calendar_ids=None):
    """Bounded editor choices from the scoped registry; no source approval inferred."""
    _authorize(actor)
    _id(case_id);_id(application_id)
    if knowledge_version_id is not None:_id(knowledge_version_id)
    pinned_calendar_ids=[] if pinned_calendar_ids is None else pinned_calendar_ids
    if type(pinned_calendar_ids) is not list or len(pinned_calendar_ids)>10:raise EntryStorageInvalid('invalid_calendar_identifiers')
    for calendar_id in pinned_calendar_ids:_id(calendar_id)
    async def read(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        events=await applications._events(session,application)
        version_id=knowledge_version_id
        accepted=select(KnowledgeImport.id).where(KnowledgeImport.version_id==KnowledgeVersion.id,
            KnowledgeImport.result=='accepted').exists()
        versions=list((await session.scalars(select(KnowledgeVersion).join(KnowledgeSet,
            KnowledgeVersion.set_id==KnowledgeSet.id).where(KnowledgeSet.code=='kg_entry',
                KnowledgeSet.jurisdiction=='KG',KnowledgeSet.domain=='entry',accepted)
            .order_by(KnowledgeVersion.version.desc()).limit(20))).all())
        if version_id is None:version_id=versions[0].id if versions else None
        bundle=await _bundle(session,version_id) if version_id else None
        version=await session.get(KnowledgeVersion,version_id) if version_id else None
        if version and all(v.id!=version_id for v in versions):versions.append(version)
        rules=[{k:r[k] for k in ('unit_id','title','confirmation_status','section','page','source_ref')}
               for r in (bundle['units'] if bundle else []) if r['kind']=='deadline']
        anchors=[dict(value=f'application_event:{r.id}',kind='application_event',id=r.id,
            label=f"{applications.STATUSES[r.status]} · {r.occurred_on.isoformat()} · событие №{r.id}")
            for r in events if r.status in sources.EVENT_ANCHORS and r.source in ('portal','official_document')]
        if sources.issued._approval(application,events):
            rows,_=await sources.issued._history(session,application,sources.issued._approval(application,events))
            for row in rows:
                operation=row.command['operation']
                if operation['action']=='travel':
                    data=operation['data']
                    direction='Фактический въезд' if data['direction']=='entry' else 'Фактический выезд'
                    anchors.append(dict(value=f'travel:{row.id}',kind='travel',id=row.id,
                        label=f"{direction} · {data['on']} · запись №{row.id}"))
        calendars=list((await session.scalars(select(WorkCalendar).order_by(WorkCalendar.year.desc(),
                            WorkCalendar.version.desc()).limit(40))).all())
        extra=set(pinned_calendar_ids)-{c.id for c in calendars}
        if extra:
            calendars.extend((await session.scalars(select(WorkCalendar).where(WorkCalendar.id.in_(extra))
                .order_by(WorkCalendar.year.desc(),WorkCalendar.version.desc()))).all())
        return dict(application=applications._application_view(application),application_status=events[-1].status,
            knowledge_version_id=version_id,rules=rules,anchors=anchors,
            versions=[dict(id=v.id,version=v.version) for v in versions],
            calendars=[dict(id=c.id,year=c.year,version=c.version,status=c.status) for c in calendars])
    return await applications._run(engine,read)
