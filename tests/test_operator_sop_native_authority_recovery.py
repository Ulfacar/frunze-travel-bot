"""Native saved retries and signed retained clear do not need fresh authority."""
from pathlib import Path
from tests import test_admin_operator_sop as native
from tests.test_admin_operator_sop import env,enforce_sqlite_foreign_keys
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_operator_sop_native_http import counts
from tests.test_admin_kg_entry import Form

def test_retained_signed_retry_and_clear_survive_unavailable_current_registry(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch);data=native.schedule(env,'en')
    assert native.post(env,data,'en').status_code==303
    assert native.post(env,native.form(env,'reconcile','en'),'en').status_code==303
    clear=native.form(env,'operator_review_clear','en')
    fresh=native.schedule(env,'en');before=counts(env)
    original=native.ui.policies.configured
    folder=Path('runs/reviewer-http');folder.mkdir(parents=True,exist_ok=True)
    # A structurally invalid configured registry and a storage-unavailable loader
    # are distinct from intentional empty delegation. Neither may grant a write.
    monkeypatch.setattr(native.ar.settings,'kg_operator_sop_authorities',[{}])
    for registry_kind in ('invalid','unavailable'):
        if registry_kind=='unavailable':
            def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-policy-registry-unavailable')
            monkeypatch.setattr(native.ui.policies,'configured',unavailable)
        page=env['client'].get(native.url(env,'en'))
        assert page.status_code==200 and page.headers['cache-control']=='no-store'
        assert 'id="sop-operator_review"' not in page.text
        assert 'id="sop-operator_review_clear"' in page.text and 'Needs reconciliation' in page.text
        (folder/('authority-'+registry_kind+'-retained.html')).write_text(page.text,encoding='utf-8')
        blocked=native.post(env,fresh,'en')
        assert blocked.status_code==503 and Form(blocked.text,'sop-retry').data==fresh
        assert counts(env)==before
        assert native.post(env,data,'en').status_code==303
        assert counts(env)==before
    def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-policy-registry-unavailable')
    monkeypatch.setattr(native.ui.policies,'configured',unavailable)
    retry=native.post(env,data,'en');withdraw=native.post(env,clear,'en')
    (folder/'authority-registry-retry.html').write_text(retry.text,encoding='utf-8')
    (folder/'authority-registry-clear.html').write_text(withdraw.text,encoding='utf-8')
    assert (retry.status_code,withdraw.status_code)==(303,303)
    assert native.post(env,clear,'en').status_code==303
    assert native.post(env,data,'en').status_code==303
    assert counts(env)==[before[0]+1,before[1]]
    assert 'Cancelled' in env['client'].get(native.url(env,'en')).text
    monkeypatch.setattr(native.ui.policies,'configured',original)
