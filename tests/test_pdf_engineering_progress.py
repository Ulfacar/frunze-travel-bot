"""Progress must not improve through criteria drift or missing evidence."""
import copy
import json

import pytest

from scripts.check_pdf_engineering_progress import ROOT, evaluate


@pytest.fixture
def criteria():
    return json.loads((ROOT/'docs/pdf-engineering-criteria.json').read_text(encoding='utf-8'))


def test_unknown_gets_no_credit(criteria):
    for row in criteria['criteria']:
        row['status'] = 'UNKNOWN'
    assert evaluate(criteria)['engineering_points'] == 0


@pytest.mark.parametrize('field,value', [('weight', 20), ('acceptance', 'Show a mockup')])
def test_definition_drift_refused(criteria, field, value):
    criteria['criteria'][0][field] = value
    with pytest.raises(ValueError, match='definitions changed'):
        evaluate(criteria)


def test_missing_or_fabricated_evidence_cannot_score(criteria):
    row = criteria['criteria'][0]
    row['status'] = 'PASS'
    evidence = copy.deepcopy(row['evidence'])
    row['evidence'] = []
    with pytest.raises(ValueError, match='Missing evidence'):
        evaluate(criteria)
    row['evidence'] = evidence
    row['evidence'][0]['revision'] = 'uncommitted'
    with pytest.raises(ValueError, match='exact passing revision'):
        evaluate(criteria)
    row['evidence'][0]['revision'] = '0'*40
    row['evidence'][0]['artifact'] = '../outside-evidence.md'
    with pytest.raises(ValueError, match='Missing local evidence artifact'):
        evaluate(criteria)


def test_pass_does_not_certify_independent_review(criteria):
    result = evaluate(criteria)
    assert result['engineering_points'] > 0
    assert result['independently_reviewed'] is False
    assert result['production_readiness'] == 'UNKNOWN'
