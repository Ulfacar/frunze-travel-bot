"""Public wrapper keeps validation before opening a transaction."""
import asyncio

import pytest

from app.domain import work_deadlines
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied


@pytest.mark.parametrize('actor,case_id,error', [
    (Actor(manager_id='unapproved'), 1, PermissionDenied),
    (Actor(manager_id='admin', is_full_admin=True), 0, EntryStorageInvalid),
])
def test_existing_wrapper_rejects_before_engine(actor, case_id, error):
    with pytest.raises(error):
        asyncio.run(work_deadlines.evaluate(None, actor=actor, case_id=case_id, applicant_id=1))
