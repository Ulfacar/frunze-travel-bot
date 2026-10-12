"""Projected cross-application passport scope must be checked before admission."""
import pytest

from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_anchors import setup,application,args,write,read


def test_thirty_third_passport_application_cannot_poison_existing_current_reads(env):
    prepared=setup(env)
    # The real bound is32 applications, including the original.
    for index in range(32):
        app=prepared[1] if index==0 else application(env,prepared[0],'PASSPORT-'+str(index),procedure='registration')
        subject=(prepared[0],app,prepared[2])
        request=args(env,subject,'passport_change','CHANGE')
        write(env,request)
    assert read(env,prepared)['observations'][0]['usable']
    extra=application(env,prepared[0],'PASSPORT-OVERFLOW',procedure='registration')
    request=args(env,(prepared[0],extra,prepared[2]),'passport_change','CHANGE')
    with pytest.raises(EntryStorageInvalid,match='passport_scope_limit'):
        write(env,request)
    assert read(env,prepared)['observations'][0]['usable']
