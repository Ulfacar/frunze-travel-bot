"""Regression probes adopted from independent E6-22 final audit; synthetic only."""
import json
from copy import deepcopy

import pytest
import yaml

from app.domain.qualification_policy import QualificationPolicy
from app.knowledge.bundle import preflight_bundle
from tests import test_approved_qualification as cases
from tests.test_approved_qualification import clock, env


@pytest.mark.parametrize('condition_type', ['B', 'TS', 'unchecked_month'])
def test_conditional_visa_type_must_agree_with_candidate_product(env, tmp_path, monkeypatch, condition_type):
    identifier = 'KG.VR.CONDITIONAL'
    original_import = cases.import_bundle
    clauses = [dict(type='passport_country_in', countries=['CHN']),
               dict(type='document_type_is', value='ordinary'),
               (dict(type='stay_within_months', maximum=1) if condition_type=='unchecked_month'
                else dict(type='visa_type_is', value=condition_type))]
    async def import_with_catalog(engine, **kwargs):
        report = preflight_bundle(kwargs['directory'], kwargs['source'])
        catalog = dict(format='kg-entry-conditions/1', status='draft',
            source_hash=report.normalized_bundle['meta']['source_hash'], bundle_hash=report.bundle_hash,
            source_capture_sha256='1'*64, source_date='2026-10-02', date_basis='source_claim',
            publication_approved=False, rules=[dict(unit_id=identifier,
                source_locations=[dict(page=1, section='Synthetic condition')], all=clauses,
                source_outcome=dict(gknb_approval=False), unresolved=[])])
        path = tmp_path/'auditor-condition-catalog.json'
        path.write_text(json.dumps(catalog), encoding='utf-8')
        return await original_import(engine, **kwargs, catalog=path)
    monkeypatch.setattr(cases, 'import_bundle', import_with_catalog)
    units = yaml.safe_load((cases.FIX/'synthetic_bundle/units.yaml').read_text('utf-8'))
    extra = deepcopy(next(unit for unit in units if unit['kind']=='visa_required_regime'))
    extra.update(unit_id=identifier, value=dict(procedure='simplified', scope='all_types',
        gknb_approval=False, countries=['CHN']))
    ready = cases.setup(env, tmp_path, extra=extra)
    cases.publish(ready, 'withdraw')
    for action in ('review', 'approve', 'activate'):
        cases.publish(ready, action, ids=['KG.DL.TEST','KG.VF.TEST',identifier])
    document = ready['policy'].document
    document['rules'].append(dict(unit_id=identifier, all=clauses,
        routes=[dict(purpose='tourism', product='TS')]))
    ready['policy'] = QualificationPolicy(document)
    request = cases.profile()
    request['profile'].update(citizenship=['CHN'], entry_passport_country='CHN')
    request['condition_facts'] = dict(schema_version='kg-entry-condition-facts/1',
        **(dict(stay_within_one_month_verified=True) if condition_type=='unchecked_month'
           else dict(requested_visa_type=condition_type)))
    cases.save(ready, ready['person'], revision=1, key='conditional-visa', doc=request)
    result = cases.propose(ready)
    if condition_type != 'TS':
        assert result['candidate'] is None, result
    else:
        assert result['candidate'] and result['candidate']['product'] == 'TS', result
