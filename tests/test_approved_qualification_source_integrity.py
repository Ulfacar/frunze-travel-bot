"""Original independent E6-22 source-semantics negative probes, retained as regressions."""
import json
from copy import deepcopy

import pytest
import yaml

from app.domain.qualification_policy import QualificationPolicy
from app.knowledge.bundle import preflight_bundle
from tests import test_approved_qualification as t
from tests.test_approved_qualification import clock, env


@pytest.mark.parametrize('fault', ['country_guard', 'outcome'])
def test_catalog_cannot_erase_source_restrictions(env, tmp_path, monkeypatch, fault):
    original = t.import_bundle
    recorded = {}
    async def imported(engine, **kwargs):
        report = preflight_bundle(kwargs['directory'], kwargs['source'])
        unit = next(u for u in report.normalized_bundle['units'] if u['unit_id'] == 'KG.VF.TEST')
        clauses = [dict(type='document_type_is', value='ordinary')]
        if fault == 'outcome':
            clauses.insert(0, dict(type='passport_country_in', countries=unit['value']['countries']))
        catalog = dict(format='kg-entry-conditions/1', status='draft',
            source_hash=report.normalized_bundle['meta']['source_hash'], bundle_hash=report.bundle_hash,
            source_capture_sha256='1'*64, source_date='2026-10-02', date_basis='source_claim',
            publication_approved=False, rules=[dict(unit_id='KG.VF.TEST',
                source_locations=[dict(page=1, section='Synthetic')], all=clauses,
                source_outcome={'visa_type':'TS'} if fault == 'outcome' else {'stay_days':10, 'window_days':30},
                unresolved=[])])
        path = tmp_path / 'reviewer-catalog.json'
        path.write_text(json.dumps(catalog), encoding='utf-8')
        recorded['clauses'] = clauses
        return await original(engine, **kwargs, catalog=path)
    monkeypatch.setattr(t, 'import_bundle', imported)
    ready = t.setup(env, tmp_path)
    document = ready['policy'].document
    document['rules'][0]['all'] = recorded['clauses']
    ready['policy'] = QualificationPolicy(document)
    if fault == 'country_guard':
        request = t.profile()
        request['profile'].update(citizenship=['CHN'], entry_passport_country='CHN')
        t.save(ready, ready['person'], revision=1, key='wrong-country', doc=request)
    result = t.propose(ready)
    assert result['candidate'] is None, result


def test_country_only_policy_cannot_erase_gcc_residence_requirement(env, tmp_path):
    units = yaml.safe_load((t.FIX/'synthetic_bundle/units.yaml').read_text('utf-8'))
    extra = deepcopy(next(u for u in units if u['kind'] == 'visa_required_regime'))
    extra.update(unit_id='KG.VR.GCC_TEST', value=dict(procedure='simplified',
        scope='tourist_gcc_resident', gknb_approval=False, countries=['CHN']))
    ready = t.setup(env, tmp_path, extra=extra)
    t.publish(ready, 'withdraw')
    ids = ['KG.DL.TEST', 'KG.VF.TEST', 'KG.VR.GCC_TEST']
    for action in ('review', 'approve', 'activate'):
        t.publish(ready, action, ids=ids)
    document = ready['policy'].document
    document['rules'].append(dict(unit_id='KG.VR.GCC_TEST', all=[
        dict(type='passport_country_in', countries=['CHN']), dict(type='document_type_is', value='ordinary')],
        routes=[dict(purpose='tourism', product='TS')]))
    ready['policy'] = QualificationPolicy(document)
    request = t.profile()
    request['profile'].update(citizenship=['CHN'], entry_passport_country='CHN')
    t.save(ready, ready['person'], revision=1, key='unknown-residence', doc=request)
    result = t.propose(ready)
    assert result['candidate'] is None, result
