"""Isolate evidence validation from the stronger immutable projection audit."""
import asyncio
from copy import deepcopy

import pytest

from app.domain import work_review_tasks as service
from app.domain.work_review_evidence import verify_report
from app.domain.work_review_policy import from_document
from app.domain.entry_storage import EntryStorageInvalid, _hash, _plain
from app.domain.models import EntryWorkReviewEvent
from tests import test_work_review_tasks as baseline
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins,
    enforce_sqlite_foreign_keys,
)


def test_direct_historical_verifier_rejects_rehashed_calendar_and_boolean_scope(env, tmp_path):
    baseline.setup(env, tmp_path)
    saved = baseline.record(env, baseline.command(env))
    async def run():
        async with env['sm']() as session:
            case, person, application = await service._scope(
                session, saved['case_id'], saved['applicant_id'], saved['application_id'])
            row = await session.get(EntryWorkReviewEvent, saved['id'])
            snapshot = _plain(row.snapshot)
            authority = from_document(snapshot['authority'])
            await verify_report(session, case, person, application, row,
                                snapshot['report'], authority, snapshot['application_event'])
            for field in ('nested_calendar', 'typed_person_scope'):
                report = deepcopy(snapshot['report'])
                current = report['current_stay']
                if field == 'nested_calendar':
                    current['calendar']['hash'] = '1' * 64
                else:
                    assert current['case_id'] == 1
                    current['case_id'] = True
                current['evidence_hash'] = _hash({k: v for k, v in current.items() if k != 'evidence_hash'})
                report['evidence_hash'] = _hash({k: v for k, v in report.items() if k != 'evidence_hash'})
                with pytest.raises(EntryStorageInvalid, match='work_review_evidence_integrity_failed'):
                    await verify_report(session, case, person, application, row,
                                        report, authority, snapshot['application_event'])
    asyncio.run(run())
