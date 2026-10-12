"""Own bounded HTTP check of five labels and empty-authority selection."""
import asyncio
from html.parser import HTMLParser

from sqlalchemy import func,select
from app.domain.models import EntryDeadlineRevision,CalendarTask,EntryAnchorEvent
from tests import test_admin_actual_dates as native
from tests.test_admin_actual_dates import env,clock,enforce_sqlite_foreign_keys

NEW=('KG.DL.INTERNAL_TS_EXIT_REVIEW','KG.DL.INTERNAL_B_RENEWAL_PREPARATION',
     'KG.DL.INTERNAL_RL_RES_PREPARATION','KG.DL.INTERNAL_RL_RES_REVIEW','KG.DL.INTERNAL_S_RES_REVIEW')

class Selected(HTMLParser):
    def __init__(self,text):
        super().__init__();self.values=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='option' and 'selected' in values:self.values.append(values.get('value'))

def test_new_visa_rule_choices_are_localized_unknown_and_write_free_without_authority(env,monkeypatch):
    person,application,_=native.core.actual.setup(env,'visa_period')
    ids=(application['case_id'],person['id'],application['id'])
    monkeypatch.setattr(native.ar.settings,'kg_actual_anchor_policy',None)
    monkeypatch.setattr(native.ar.settings,'kg_conditional_deadline_authorities',[])
    async def counts():
        async with env['sm']() as session:
            return [await session.scalar(select(func.count()).select_from(table))
                    for table in (EntryDeadlineRevision,CalendarTask,EntryAnchorEvent)]
    before=asyncio.run(counts())
    for rule in NEW:
        for language in ('ru','en'):
            response=env['client'].get(native.ui.url(ids,language,rule))
            assert response.status_code==200 and response.headers['cache-control']=='no-store'
            assert Selected(response.text).values==[rule]
            assert native.ui.RULES[rule][language=='en'] in response.text
            assert native.ui.TEXT[language]['unknown'] in response.text
            assert 'id="actual-dates-conditional_review"' not in response.text
            assert 'id="actual-dates-reconcile"' not in response.text
            assert 'id="actual-dates-record-' not in response.text
    assert asyncio.run(counts())==before
    assert env['client'].get(native.ui.url(ids,'en',NEW[0]+'_EXTRA')).status_code==422
    assert env['client'].get(native.ui.url(ids,'en',NEW[0])+'&rule='+NEW[1]).status_code==422
