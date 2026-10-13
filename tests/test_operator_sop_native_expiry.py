"""Real signed HTTP preserves history/recovery after nested process authority expiry."""
import asyncio
from datetime import datetime,timedelta,timezone
from pathlib import Path
from sqlalchemy import select,func
from app.domain.models import EntryDeadlineRevision,CalendarTask
from tests import test_admin_operator_sop as native
from tests.test_admin_operator_sop import env,enforce_sqlite_foreign_keys

def test_nested_process_expiry_has_localized_unknown_and_retained_native_recovery(env,tmp_path,monkeypatch):
    original=native.core.processes.policy
    on=native.core.processes.today()
    def short_policy(**changes):return original(review_due_on=on,**changes)
    monkeypatch.setattr(native.core.processes,'policy',short_policy)
    native.setup(env,tmp_path,monkeypatch)
    async def counts():
        async with env['sm']() as session:
            return [await session.scalar(select(func.count()).select_from(t)) for t in (EntryDeadlineRevision,CalendarTask)]
    # The shared fixture already has an unrelated ordinary CRM task.
    before=asyncio.run(counts())
    data=native.schedule(env,'en')
    assert native.post(env,data,'en').status_code==303
    assert native.post(env,native.form(env,'reconcile','en'),'en').status_code==303
    fresh=native.schedule(env,'en')
    future=datetime.now(timezone.utc)+timedelta(days=2)
    assert future.date().isoformat()<env['prepared'][-1].policy.document['review_due_on']
    monkeypatch.setattr(native.ui.service,'_now',lambda:future)
    monkeypatch.setattr(native.ui.service.sources,'_now',lambda:future)
    folder=Path('runs/reviewer-expiry');folder.mkdir(parents=True,exist_ok=True)
    for language in ('ru','en'):
        page=env['client'].get(native.url(env,language))
        (folder/(language+'.html')).write_text(page.text,encoding='utf-8')
        assert page.status_code==200 and page.headers['cache-control']=='no-store'
        assert native.ui.TEXT[language]['authority_changed'] in page.text
        assert native.ui.TEXT[language]['unknown_status'] in page.text
        assert '2026-11-02' in page.text and '00:30' in page.text
        assert 'id="sop-operator_review"' not in page.text
        assert 'id="sop-operator_review_clear"' in page.text
    assert native.post(env,fresh,'en').status_code==422
    assert native.post(env,data,'en').status_code==303
    clear=native.form(env,'operator_review_clear','en')
    assert native.post(env,clear,'en').status_code==303
    assert native.post(env,clear,'en').status_code==303
    assert native.post(env,data,'en').status_code==303
    page=env['client'].get(native.url(env,'en'))
    assert page.status_code==200 and 'Cancelled' in page.text
    assert asyncio.run(counts())==[before[0]+2,before[1]+1]
