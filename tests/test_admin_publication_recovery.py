import asyncio
from copy import deepcopy
import shutil

import pytest
import yaml

from app.domain import knowledge_publication as service
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from tests.test_admin_kg_entry import ADMIN, FIX, Form, env
from tests.test_admin_kg_knowledge_publication import publisher, form, post, url
from tests.test_knowledge_decisions import write
from tests.test_knowledge_publication import IDS, activate, publish, release, runtime
from tests.test_publication_recovery import journal_size


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_native_withdrawal_at_capacity_and_exact_retry(publisher, monkeypatch, bound):
    activate(publisher)
    if bound == 'count': monkeypatch.setattr(service, 'MAX_REVISIONS', 3)
    else: monkeypatch.setattr(service, 'MAX_BYTES', journal_size(publisher))
    values = form(publisher, 'withdraw')
    assert post(publisher, values).status_code == 303
    assert post(publisher, values).status_code == 303
    assert runtime(publisher)['version_id'] is None
    page = publisher['client'].get(url(publisher))
    assert page.status_code == 200
    assert not Form(page.text, 'kg-publication-review').data
    assert not Form(page.text, 'kg-publication-rollback').data


def large_source(env, tmp_path):
    folder = tmp_path/'large-source'; shutil.copytree(FIX/'synthetic_bundle', folder)
    original = yaml.safe_load((folder/'units.yaml').read_text('utf-8'))
    base = next(u for u in original if u['unit_id'] == IDS[0])
    units = []
    for index in range(101):
        unit = deepcopy(base)
        unit.update(unit_id=f'KG.DL.LARGE{index}', effective_from='2026-01-01',
            verified_at='2026-09-01T00:00:00Z', verified_by='synthetic-reviewer',
            review_due_at='2026-12-01T00:00:00Z', owner='synthetic-owner', source_ref='SYNTHETIC LARGE PUBLICATION')
        units.append(unit)
    (folder/'units.yaml').write_text(yaml.safe_dump(units), 'utf-8')
    async def load():
        set_id = await create_kg_entry_set(env['engine'], actor=ADMIN)
        return await import_bundle(env['engine'], actor=ADMIN, set_id=set_id, directory=folder, source=FIX/'synthetic_source.txt')
    result = asyncio.run(load()); assert result.accepted
    env['release'] = result.version_id
    ids = [u['unit_id'] for u in units]
    for uid in ids: write(env, unit=uid, version=result.version_id, key='large-'+uid)
    for action in ('review', 'approve', 'activate'): publish(env, action, ids=ids, key='large-'+action)
    return ids


def test_native_withdraws_full_101_unit_manifest_using_bounded_selection(publisher, tmp_path):
    import app.admin.kg_knowledge_publication as ui
    ids = large_source(publisher, tmp_path)
    page = publisher['client'].get(ui.URL, params={'version':publisher['release'], 'units':ids[0]})
    assert page.status_code == 200
    assert 'отзыв всей активной публикации: 101 правил' in page.text
    values = Form(page.text, 'kg-publication-withdraw').data
    assert values['_kp_units'] == ids[0]
    values['confirmed'] = 'yes'
    assert post(publisher, values).status_code == 303
    assert runtime(publisher, ids[:100])['version_id'] is None
    assert post(publisher, values).status_code == 303


def test_original_native_withdrawal_retry_after_manifest_replacement(publisher):
    activate(publisher)
    values = form(publisher, 'withdraw')
    assert post(publisher, values).status_code == 303
    for action in ('review', 'approve', 'activate'):
        publish(publisher, action, ids=[IDS[0]], key='replacement-'+action)
    before = runtime(publisher)
    assert post(publisher, values).status_code == 303
    after = runtime(publisher)
    assert before['version_id'] == after['version_id']
    assert [u['unit_id'] for u in after['available']] == [IDS[0]]
