from copy import deepcopy
import json

import pytest

from app.knowledge import dialogue_questions as q, interview_catalog as catalog, interview_rules as rules
from tests.test_kg_dialogue_interrupts import EXAMPLES
from tests.test_kg_interview_rules import changed, put, result


def prompt(paths=('document_type', 'passport_expiry', 'passport_two_blank_pages'), language='ru', batch=24):
    return q.render(batch=batch, paths=list(paths), language=language, catalog_document=catalog.document())


def parse(p, text, **kw):
    return q.parse(p, text, catalog_document=catalog.document(), **kw)


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_enum_bool_date_exact_displayed_batch_and_reloaded_values(language):
    values = changed({}, 'consent.given', True)
    values = put(values, **{'consent.on': '2026-10-11', 'consent.evidence_ref': 'SYN-CONSENT', 'consent.evidence_sha256': 'a'*64})
    for path, value in {'citizenships': ['RUS'], 'location': 'abroad', 'current_country': 'RUS',
                        'purpose': 'tourism', 'entry_on': '2026-11-10', 'exit_on': '2026-11-20',
                        'party_type': 'individual', 'applicants_count': 1,
                        'contact_name': 'Synthetic', 'language': language, 'contact_phone': 'Synthetic',
                        'contact_messenger': 'Synthetic', 'contact_role': 'applicant', 'contact_email': 'synthetic@example.invalid',
                        'terms.accepted': False}.items():
        values = changed(values, path, value)
    for batch, path, literal, expected in [(1, 'document_type', '1', 'ordinary'),
            (2, 'passport_two_blank_pages', 'да' if language == 'ru' else 'yes', True),
            (3, 'passport_expiry', '2030-12-31', '2030-12-31')]:
        state = result(values, language)
        paths = [f['path'] for f in state['questions']]
        assert path in paths, paths
        p = json.loads(json.dumps(prompt(paths, language, batch)))
        answer = parse(p, f'{batch}.{paths.index(path)+1}: {literal}')
        assert answer['action'] == 'answer' and answer['displayed'] == paths
        assert answer['changes'] == {path: expected}
        values = rules.apply_answers(values, answer['changes'], revision=30+batch, on='2026-10-11',
                                     pre_consent=('consent.given',))
        values = json.loads(json.dumps(values))
        assert rules.Answers(values).get(path) == expected
    assert result(values, language)['consent_complete']


@pytest.mark.parametrize('text', ['yes', '1: yes', '23.3: yes', '024.3: yes', '24.4: yes', '24.3: yes please',
    '24.3: yes\n24.2: 2030-12-31', '24.3: yes\x00', '24.3:\tyes', '24.3: yes ',
    '24.2: 20301231', '24.2: 2030-02-30', '24.1: 0', '24.1: 01', '24.1: ordinary',
    '24.1: 11', '24.3: unknown', '24.3: not_applicable', '24.3: yes'+' '*2048])
def test_ambiguous_stale_partial_and_unsupported_answers_never_become_facts(text):
    assert parse(prompt(), text)['action'] == 'interrupt'


@pytest.mark.parametrize('kw', [{'voice': True}, {'voice': 1}, {'kind': 'image'}, {'kind': 'voice'}])
def test_envelope_gate_cannot_be_bypassed_by_plain_transcript(kw):
    assert parse(prompt(), '24.3: yes', **kw)['action'] == 'interrupt'


@pytest.mark.parametrize('examples', EXAMPLES)
def test_all_source_exception_families_take_precedence_over_labelled_answer(examples):
    for text in examples:
        r = parse(prompt(), '24.3: yes, '+text)
        assert r['action'] == 'interrupt'


@pytest.mark.parametrize('kw', [{}, {'voice': True}, {'kind': 'image'}])
def test_privacy_precedes_even_bad_prompt_and_oversize(kw):
    r = parse(None, '24.3: yes\x00 '+'x'*2100+' Delete my data', **kw)
    assert r['action'] == 'interrupt' and r['triage']['reason'] == 'consent_withdrawn'


def test_greeting_no_facts_and_special_document_is_typed_stop():
    assert parse(prompt(), 'hello') == {'action': 'acknowledgement'}
    a = parse(prompt(), '24.1: 2')
    values = changed({}, 'document_type', a['changes']['document_type'])
    assert result(values)['stops'] == ['special_document']


@pytest.mark.parametrize('paths', [['consent.given'], ['consent.evidence_sha256'], ['terms.accepted'],
                                 ['contact_name'], ['history.1.entry'], ['document_type']*2, []])
def test_internal_or_unsupported_questions_are_not_client_prompts(paths):
    with pytest.raises(q.QuestionInvalid): prompt(paths)


@pytest.mark.parametrize('mutate', ['wording', 'path', 'label', 'option', 'language', 'hash'])
def test_stored_prompt_tampering_rejected(mutate):
    p = prompt()
    if mutate == 'wording': p['body'] += 'other'
    elif mutate == 'path': p['displayed'][0]['path'] = 'location'
    elif mutate == 'label': p['displayed'][0]['label'] = '24.3'
    elif mutate == 'option': p['displayed'][0]['options'][0] = 'diplomatic'
    elif mutate == 'language': p['language'] = 'en'
    else: p['map_hash'] = '0'*64
    with pytest.raises(q.QuestionInvalid): parse(p, '24.1: 1')


def test_changed_catalog_cannot_silently_change_choices_or_semantics():
    document = deepcopy(catalog.document()); document['fields'][0]['depends'] = ['location']
    with pytest.raises(q.QuestionInvalid):
        q.render(batch=1, paths=['document_type'], language='ru', catalog_document=document)


@pytest.mark.parametrize('path,literal,value', [('applicants_count', '3', 3), ('residence_country', 'RUS', 'RUS'),
    ('citizenships', 'RUS, KAZ', ['KAZ', 'RUS'])])
def test_bounded_integer_and_country_values(path, literal, value):
    a = parse(prompt([path]), '24.1: '+literal)
    assert a['action'] == 'answer' and a['changes'] == {path: value}


@pytest.mark.parametrize('path,literal', [('applicants_count', '0'), ('applicants_count', '201'),
    ('applicants_count', '1.0'), ('residence_country', 'XXX'), ('citizenships', 'RUS, RUS'),
    ('citizenships', 'RUS,KAZ'), ('residence_country', 'unknown')])
def test_country_integer_validation_is_not_coerced(path, literal):
    assert parse(prompt([path]), '24.1: '+literal)['action'] == 'interrupt'
