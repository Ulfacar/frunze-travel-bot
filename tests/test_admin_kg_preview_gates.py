"""New pilot pages stay OFF by default and retain explicit enabled-page coverage.

Legacy shell smoke checks expect200 for always-on routes. These named routes use
their existing OFF/ON contract instead; its negative expectations remain strict.
"""
import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env


@pytest.mark.parametrize('path',[
    '/admin/kg-entry/knowledge','/admin/kg-entry/processes',
    '/admin/kg-entry/documents','/admin/kg-entry/templates',
])
def test_each_registered_preview_obeys_enabled_and_disabled_gate(env,monkeypatch,path):
    assert env['client'].get(path).status_code==200
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(path).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    assert env['client'].get(path).status_code==200
