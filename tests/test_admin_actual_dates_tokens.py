"""Real signed-form token typing and scope errors, no large source fixture."""
import pytest
from tests import test_admin_actual_dates as native
from tests.test_admin_actual_dates import env,clock,enforce_sqlite_foreign_keys
from tests.test_admin_kg_entry import Form


def setup(env,monkeypatch):
    prepared=native.core.actual.setup(env)
    monkeypatch.setattr(native.ar.settings,'kg_actual_anchor_policy',native.core.actual.policy().document)
    env.update(ids=(prepared[1]['case_id'],prepared[0]['id'],prepared[1]['id']),rule='KG.DL.INTERNAL_EAEU_REG_REVIEW')
    page=env['client'].get(native.url(env,'en'));assert page.status_code==200
    values=Form(page.text,'actual-dates-record-1').data|{'confirmed':'yes'}
    assert values['signature']
    return prepared,values


@pytest.mark.parametrize('key',['csrf','signature'])
def test_nonascii_tokens_are_controlled_forbidden(env,monkeypatch,key):
    _,data=setup(env,monkeypatch)
    for value in ('я'*64,'','A'*64,'0'*63):
        response=native.post(env,data|{key:value},'en')
        assert response.status_code==403
        assert response.headers['cache-control']=='no-store'


def test_absent_and_foreign_subject_scope_returns_not_found(env,monkeypatch):
    prepared,_=setup(env,monkeypatch)
    other=native.core.actual.setup(env,key='OTHER')
    for ids in ((env['ids'][0],env['ids'][1],2147483647),
                (env['ids'][0],other[0]['id'],env['ids'][2]),
                (env['cases']['other'],env['ids'][1],env['ids'][2])):
        response=env['client'].get(native.ui.url(ids,'en',env['rule']))
        assert response.status_code==404
        assert response.headers['cache-control']=='no-store'
