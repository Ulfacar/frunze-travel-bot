"""Immutable review evidence for imported knowledge; no source edits or publication."""
from datetime import date
import re

from sqlalchemy import select

from app.domain import entry_applications as transactions
from app.domain.entry_calculations import _bundle
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key, _plain
from app.domain.models import KnowledgeDecision, KnowledgeImport, KnowledgeSet, KnowledgeVersion, _now
from app.knowledge.review import canonical

MAX_REVISIONS = 250
MAX_BYTES = 2 * 1024 * 1024
FIELDS = {'verdict','reason','evidence_kind','evidence_ref','proof','verified_on','review_due_on','confirmed'}


def _unit_id(value):
    if not isinstance(value, str) or len(value)>120 or not re.fullmatch(r'KG\.[A-Z0-9_]+(?:\.[A-Z0-9_]+)*',value):
        raise EntryStorageInvalid('invalid_knowledge_unit')


def normalize(data, *, cutoff):
    if type(data) is not dict or data.keys()!=FIELDS or data['confirmed'] is not True:
        raise EntryStorageInvalid('invalid_knowledge_decision')
    if (data['verdict'] not in ('confirmed','rejected','needs_changes') or
        data['evidence_kind'] not in ('official_source','owner_decision','technical_check') or
        not isinstance(data['evidence_ref'],str) or not re.fullmatch(r'[A-Z][A-Z0-9._/-]{0,79}',data['evidence_ref']) or
        not isinstance(data['proof'],str) or not re.fullmatch('[a-f0-9]{64}',data['proof'])):
        raise EntryStorageInvalid('invalid_knowledge_evidence')
    reasons = ('source_matches',) if data['verdict']=='confirmed' else ('source_conflict','insufficient_evidence','outdated','withdrawn')
    if data['reason'] not in reasons:
        raise EntryStorageInvalid('invalid_knowledge_reason')
    try:
        verified=date.fromisoformat(data['verified_on'])
        if verified.isoformat()!=data['verified_on'] or verified>cutoff:raise ValueError
        if data['verdict']=='confirmed':
            due=date.fromisoformat(data['review_due_on'])
            if due.isoformat()!=data['review_due_on'] or due<verified:raise ValueError
        elif data['review_due_on'] is not None:raise ValueError
    except (ValueError,TypeError):
        raise EntryStorageInvalid('invalid_knowledge_review_date') from None
    return dict(data)


async def _version(session, version_id, *, lock=False):
    version=await session.get(KnowledgeVersion,version_id)
    if version is None:raise EntryStorageInvalid('knowledge_version_unavailable')
    query=select(KnowledgeSet).where(KnowledgeSet.id==version.set_id)
    target=await session.scalar(query.with_for_update(read=not lock,of=KnowledgeSet))
    if target is None or (target.code,target.jurisdiction,target.domain)!=('kg_entry','KG','entry'):
        raise EntryStorageInvalid('knowledge_version_unavailable')
    version=await session.scalar(select(KnowledgeVersion).where(KnowledgeVersion.id==version_id)
        .with_for_update(read=not lock,of=KnowledgeVersion).execution_options(populate_existing=True))
    return version,await _bundle(session,version_id)


def _unit(bundle, identifier):
    unit=next((u for u in bundle['units'] if u['unit_id']==identifier),None)
    if unit is None:raise EntryStorageInvalid('knowledge_unit_unavailable')
    return unit


def _command(version_id, identifier, revision, decision, actor):
    return dict(version_id=version_id,unit_id=identifier,expected_revision=revision,decision=decision,actor=actor)


def _payload(row):
    return {**{k:_plain(getattr(row,k)) for k in ('version_id','unit_id','revision','previous_id','unit_hash','bundle_hash',
                'request_key','request_hash','command','created_by')},'created_at':transactions._utc(row.created_at)}


async def _history(session, version, unit):
    rows=list((await session.scalars(select(KnowledgeDecision).where(KnowledgeDecision.version_id==version.id,
        KnowledgeDecision.unit_id==unit['unit_id']).order_by(KnowledgeDecision.revision).limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS:raise EntryStorageInvalid('knowledge_decision_history_limit')
    previous=None;size=0
    for i,row in enumerate(rows,1):
        decision=normalize(_plain(row.command)['decision'],cutoff=transactions._local_day(row.created_at))
        command=_command(version.id,unit['unit_id'],i-1,decision,row.created_by)
        payload=_payload(row);size+=len(canonical(payload).encode())
        if size>MAX_BYTES:raise EntryStorageInvalid('knowledge_decision_history_limit')
        if (row.revision!=i or row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            row.unit_hash!=_hash(unit) or row.bundle_hash!=version.bundle_hash or row.command!=command or
            row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(payload)):
            raise EntryStorageInvalid('knowledge_decision_integrity_failed')
        previous=row
    return rows,size


def _view(row):
    decision=_plain(row.command)['decision']
    expired=bool(decision['review_due_on'] and date.fromisoformat(decision['review_due_on'])<transactions._today())
    return dict(id=row.id,revision=row.revision,decision=decision,expired=expired,
        created_by=row.created_by,created_at=transactions._utc(row.created_at),unit_hash=row.unit_hash,
        bundle_hash=row.bundle_hash,snapshot_hash=row.snapshot_hash,may_quote=False,publication_approved=False)


async def record_knowledge_decision(engine, *, actor, version_id, unit_id: str, expected_revision, request_key, decision):
    _authorize(actor);_id(version_id);_unit_id(unit_id);_key(request_key)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS:
        raise EntryStorageInvalid('invalid_knowledge_decision_revision')
    decision=normalize(decision,cutoff=transactions._today())
    command=_command(version_id,unit_id,expected_revision,decision,actor.manager_id)
    async def write(session):
        version,bundle=await _version(session,version_id,lock=True);unit=_unit(bundle,unit_id)
        rows,size=await _history(session,version,unit)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('knowledge_decision_request_reused')
            return _view(old)
        if len(rows)!=expected_revision:raise EntryStorageConflict('knowledge_decision_revision_changed')
        row=KnowledgeDecision(version_id=version_id,unit_id=unit_id,revision=len(rows)+1,
            previous_id=rows[-1].id if rows else None,unit_hash=_hash(unit),bundle_hash=version.bundle_hash,
            request_key=request_key,request_hash=_hash(command),command=command,created_by=actor.manager_id,created_at=_now())
        payload=_payload(row)
        if size+len(canonical(payload).encode())>MAX_BYTES:raise EntryStorageInvalid('knowledge_decision_history_limit')
        row.snapshot_hash=_hash(payload);session.add(row);await session.flush()
        return _view(row)
    return await transactions._run(engine,write)


async def read_knowledge_decisions(engine, *, actor, version_id, unit_id: str, revision=None):
    _authorize(actor);_id(version_id);_unit_id(unit_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS):
        raise EntryStorageInvalid('invalid_knowledge_decision_revision')
    async def read(session):
        version,bundle=await _version(session,version_id);unit=_unit(bundle,unit_id)
        rows,_=await _history(session,version,unit)
        selected=next((r for r in rows if r.revision==revision),None) if revision else rows[-1] if rows else None
        if revision and selected is None:raise EntryStorageInvalid('knowledge_decision_unavailable')
        return dict(version=dict(id=version.id,number=version.version,status=version.status,bundle_hash=version.bundle_hash,
            source_hash=version.source_hash),unit=unit,current_revision=len(rows),selected=_view(selected) if selected else None,
            history=[_view(r) for r in reversed(rows)],may_quote=False,publication_approved=False)
    return await transactions._run(engine,read)


async def review_catalog(engine, *, actor, version_id=None, page=1, query=''):
    _authorize(actor)
    if version_id is not None:_id(version_id)
    if type(page) is not int or not 1<=page<=250 or not isinstance(query,str) or len(query)>80 or any(ord(c)<32 for c in query):
        raise EntryStorageInvalid('invalid_knowledge_catalog_query')
    async def read(session):
        accepted=select(KnowledgeImport.id).where(KnowledgeImport.version_id==KnowledgeVersion.id,KnowledgeImport.result=='accepted').exists()
        versions=list((await session.scalars(select(KnowledgeVersion).join(KnowledgeSet,KnowledgeVersion.set_id==KnowledgeSet.id)
            .where(KnowledgeSet.code=='kg_entry',KnowledgeSet.jurisdiction=='KG',KnowledgeSet.domain=='entry',accepted)
            .order_by(KnowledgeVersion.version.desc()).limit(20))).all())
        selected=version_id or (versions[0].id if versions else None)
        if selected:
            version,bundle=await _version(session,selected)
            if version not in versions:versions.append(version)
            units=[r for r in sorted(bundle['units'],key=lambda r:r['unit_id']) if query.casefold() in (r['unit_id']+' '+r['title']).casefold()]
        else:units=[]
        return dict(version_id=selected,versions=[dict(id=v.id,number=v.version,status=v.status) for v in versions],
            units=[{k:r[k] for k in ('unit_id','title','kind','label','confirmation_status','page','section')} for r in units[(page-1)*20:page*20]],
            page=page,has_next=len(units)>page*20,total=len(units),query=query)
    return await transactions._run(engine,read)
