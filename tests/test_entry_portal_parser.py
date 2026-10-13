from dataclasses import replace
import hashlib

import pytest

from app.domain.entry_portal_parser import parse
from app.domain.entry_portal_policy import PortalPolicy, policy_from_document
from app.domain.entry_storage import EntryStorageInvalid


def policy(**changes):
    value = PortalPolicy(reference='SYN-POLICY-1', proof='a' * 64, source_namespace='SYN-PORTAL',
        source_reference='SYN-MAPPING', source_proof='b' * 64, privacy_reference='SYN-PRIVACY',
        privacy_proof='c' * 64, operators=('admin',), valid_from='2026-01-01', review_due_on='2027-12-31',
        allow_paste=True, manual_sources=('portal', 'official_document'), verification_sources=('portal', 'official_document'), reference_label='SYN Reference: ',
        date_label='SYN Date: ', status_label='SYN Status: ',
        status_labels=tuple((kind, kind.upper()) for kind in ('verification', 'payment', 'correction', 'approval', 'refusal')))
    return replace(value, **changes)


def message(kind='approval', reference='AB12CD34'):
    return f'SYN Reference: {reference}\nSYN Status: {kind.upper()}\nSYN Date: 2026-10-10'


@pytest.mark.parametrize('kind', ['verification', 'payment', 'correction', 'approval', 'refusal'])
def test_only_explicit_literal_mapping_produces_structured_observation(kind):
    text = message(kind)
    result = parse(text, policy())
    assert result['issues'] == []
    assert result['references'] == ['AB12CD34'] and result['kinds'] == [kind]
    assert result['raw_sha256'] == hashlib.sha256(text.encode()).hexdigest()
    assert result['raw_bytes'] == len(text.encode())
    assert result['dates'] == ['2026-10-10']
    assert 'text' not in result and 'status' not in result


@pytest.mark.parametrize('text', [
    message(reference='ab12cd34'), message(reference='АB12CD34'), message(reference='AB12CD3'),
    message(reference='AB12CD345'), message() + '\nSYN Reference: EF56GH78', message() + '\n> ' + message(),
    message() + '\nSYN Status: REFUSAL', message() + '\nSYN Status: UNVERIFIED',
    message(kind='approvalx'), message() + '\nSYN Date: 2026-10-09',
    message() + '\n<script>alert(1)</script>', 'Prefix ' + message(),
    message().replace('2026-10-10', '2026-02-31'),
])
def test_unknown_conflicting_quoted_or_confusable_text_cannot_be_ready(text):
    assert parse(text, policy())['issues']


@pytest.mark.parametrize('text', ['', 'x' * 16385, 'x' * 513, 'x\n' * 129,
    message() + '\x00', message() + '\u202e', message() + '\ud800'])
def test_rejected_input_is_bounded_and_never_normalized_into_a_reference(text):
    with pytest.raises(EntryStorageInvalid): parse(text, policy())


def test_roundtrip_policy_and_unconfigured_real_phrase():
    allowed = policy()
    assert policy_from_document(allowed.document()).document() == allowed.document()
    assert policy_from_document(allowed.document()).digest == allowed.digest
    result = parse('Reference: AB12CD34\nYour visa is approved\nhttps://example.invalid/private', allowed)
    assert result['references'] == [] and result['kinds'] == [] and result['issues']
    # A URL in an unlabelled body is never stored or fetched.
    assert 'https' not in str(result)


@pytest.mark.parametrize('change', [
    {'allow_paste': 1}, {'operators': ('bot',)}, {'manual_sources': ('crm',)},
    {'status_labels': (('approval', 'X'),)}, {'status_labels': (('approval', 'SAME'), ('refusal', 'SAME'))},
    {'date_label': 'SYN Reference: '}, {'privacy_proof': 'missing'}, {'review_due_on': '2025-01-01'},
])
def test_policy_does_not_infer_authority(change):
    with pytest.raises(EntryStorageInvalid): policy(**change)
