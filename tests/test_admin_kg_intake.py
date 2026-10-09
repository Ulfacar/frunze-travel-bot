"""Extended interview -> real immutable storage -> card; v1 survives v2 saves."""
import asyncio

import pytest

from app.domain.qualification_storage import save_qualification
from app.knowledge.validation import load_document
from tests.test_entry_storage import FIX
from tests.test_admin_kg_entry import ADMIN, Form, complete_data, count, env, form_data, post, saved
from tests.test_qualification_card import card_url


def extended_data(env):
    data = complete_data(env)
    data.update({'client_type': 'b2c', 'applicants_count_state': 'value', 'applicants_count': '2',
        'family_state': 'value', 'family.0.relation': 'child', 'family.0.age_state': 'value', 'family.0.age': '0',
        'family.0.travels_together': 'true', 'family.0.both_parents_travel': 'false',
        'purpose_details': 'Синтетический семейный визит', 'entry_point': 'manas',
        'multiple_entries_needed': 'false', 'tickets_bought': 'false', 'violations.fines': 'false'})
    return data


def test_nested_fields_family_zero_and_false_survive_save_reload_and_print_card(env):
    assert post(env, extended_data(env)).status_code == 303
    stored = saved(env)
    assert stored['input']['format'] == 'kg-qualification-review-input/2'
    profile = stored['input']['profile']
    assert profile['applicants_count'] == 2
    assert profile['family'] == [{'relation': 'child', 'age': 0, 'travels_together': True, 'both_parents_travel': False}]
    data = form_data(env)
    assert data['family.0.age'] == '0' and data['family.0.both_parents_travel'] == 'false'
    assert data['purpose_details'] == profile['purpose_details']
    card = env['client'].get(card_url(env))
    assert card.status_code == 200 and '<dd>0</dd>' in card.text and 'Ребёнок' in card.text
    assert 'Синтетический семейный визит' in card.text
    assert '(A5)' not in card.text and '(G1)' not in card.text


def test_none_family_removes_only_new_revision_and_historic_card_keeps_members(env):
    assert post(env, extended_data(env)).status_code == 303
    first = saved(env)
    data = form_data(env); data['family_state'] = 'none'
    assert post(env, data).status_code == 303
    assert saved(env)['input']['profile']['family'] == []
    old = env['client'].get(card_url(env, first['qualification_id']))
    new = env['client'].get(card_url(env))
    assert 'Ребёнок' in old.text and 'Члены семьи не едут' in new.text
    assert saved(env, qid=first['qualification_id']) == first


@pytest.mark.parametrize('state,expected', [('unknown', 'unknown'), ('not_applicable', 'not_applicable'), ('', None)])
def test_family_unknown_and_unasked_are_not_an_empty_confirmed_list(env, state, expected):
    data = complete_data(env); data['family_state'] = state
    assert post(env, data).status_code == 303
    assert saved(env)['input']['profile'].get('family') == expected


def test_inviter_false_clears_stale_details_and_actual_abroad_clears_border_facts(env):
    data = extended_data(env)
    data.update({'purpose': 'study', 'inviting_party.exists': 'true', 'inviting_party.type': 'university',
        'inviting_party.can_issue_letter': 'false', 'inviting_party.has_portal_cabinet': 'unknown',
        'current_location': 'in_kg', 'in_kg_entry_point': 'manas', 'purpose_declared_at_border': 'Учёба',
        'in_kg_since_state': 'value', 'in_kg_since': '2026-10-01'})
    assert post(env, data).status_code == 303
    assert saved(env)['input']['profile']['inviting_party']['can_issue_letter'] is False
    data = form_data(env); data.update({'inviting_party.exists': 'false', 'current_location': 'abroad'})
    assert post(env, data).status_code == 303
    profile = saved(env)['input']['profile']
    assert profile['inviting_party'] == {'exists': False}
    assert 'in_kg_entry_point' not in profile and 'purpose_declared_at_border' not in profile


def test_v1_snapshot_unchanged_when_saved_through_v2_form(env):
    legacy = load_document(FIX / 'synthetic_qualification_review.json')
    asyncio.run(save_qualification(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'],
        expected_revision=0, request_key='v1-before-upgrade', knowledge_version_id=env['version'], request=legacy))
    before = saved(env)
    data = extended_data(env)
    assert post(env, data).status_code == 303
    assert saved(env)['revision'] == 2 and saved(env)['input']['format'].endswith('/2')
    assert saved(env, qid=before['qualification_id']) == before
    old_page = env['client'].get(env['url'] + f"?qualification_id={before['qualification_id']}")
    assert old_page.status_code == 200 and Form(old_page.text).data['family_state'] == ''


@pytest.mark.parametrize('changes', [
    {'applicants_count': '1'}, {'applicants_count': '-1'}, {'applicants_count': '1.2'},
    {'applicants_count': '201'}, {'family.0.age': '-1'}, {'family.0.age': 'NaN'},
    {'family.0.relation': ''}, {'family.0.arrives_later': 'true'},
    {'event_dates.from_state': 'value', 'event_dates.from': '2026-11-10',
     'event_dates.to_state': 'value', 'event_dates.to': '2026-11-01'},
])
def test_bad_counts_family_and_dates_keep_values_without_writes(env, changes):
    data = extended_data(env); data.update(changes)
    response = post(env, data)
    assert response.status_code == 422 and count(env) == 0
    echo = Form(response.text).data
    assert echo['_kg_key'] == data['_kg_key'] and echo['family_state'] == 'value'
    for name, value in changes.items():
        assert echo[name] == value


def test_sparse_family_rows_compact_without_losing_an_applicant(env):
    data = extended_data(env)
    data.update({'applicants_count': '3', 'family.19.relation': 'parent', 'family.19.age_state': 'unknown',
                 'family.19.travels_together': 'false'})
    assert post(env, data).status_code == 303
    members = saved(env)['input']['profile']['family']
    assert len(members) == 2 and members[1]['relation'] == 'parent' and members[1]['age'] == 'unknown'
    assert form_data(env)['family.1.relation'] == 'parent'


def test_twenty_family_rows_fit_native_form_limit(env):
    data = extended_data(env); data['applicants_count'] = '21'
    for i in range(20):
        data[f'family.{i}.relation'] = 'child'
        data[f'family.{i}.age_state'] = 'value'; data[f'family.{i}.age'] = str(i)
    response = post(env, data)
    assert response.status_code == 303 and len(saved(env)['input']['profile']['family']) == 20
    assert 'large_group_review' in saved(env)['result']['stop_reasons']


def test_full_family_and_unicode_text_bounds_fit_urlencoded_body(env):
    from urllib.parse import urlencode
    from app.admin.kg_entry_form import FIELDS
    data = extended_data(env)
    for f in FIELDS:
        path, kind = f['path'], f['kind']
        if kind == 'text': data[path] = '😀' * f['max_length']
        elif kind == 'integer': data[path] = str(f['maximum']); data[path + '_state'] = 'value'
        elif kind == 'date': data[path] = '2026-10-01'; data[path + '_state'] = 'value'
        elif f['options']: data[path] = max((pair[0] for pair in f['options']), key=len)
    data.update({'applicants_count': '21', 'family_state': 'value', 'current_location': 'in_kg',
                 'previous_refusals_kg': 'true', 'entry_point': 'other_land'})
    assert len(urlencode(data, doseq=True).encode()) > 32_768
    assert post(env, data).status_code == 303
    profile = saved(env)['input']['profile']
    assert len(profile['family']) == 20 and profile['purpose_details'] == '😀' * 1000


def test_text_is_escaped_and_instruction_like_content_does_not_become_a_decision(env):
    data = extended_data(env); payload = '</textarea><script>window.syntheticAttack=1</script>'
    data['purpose_details'] = payload
    assert post(env, data).status_code == 303
    assert saved(env)['input']['profile']['purpose_details'] == payload
    for url in (env['url'], card_url(env)):
        page = env['client'].get(url)
        assert page.status_code == 200 and payload not in page.text and '&lt;script&gt;' in page.text
    assert saved(env)['result']['may_quote'] is False


def test_operator_flags_and_group_size_are_review_reasons_not_completed_handoff(env):
    data = extended_data(env)
    data.update({'applicants_count': '6', 'escalation.refund_question': 'true', 'violations.fines': 'true'})
    assert post(env, data).status_code == 303
    result = saved(env)['result']
    assert {'large_group_review', 'reported_fines', 'reported_refund_question'} <= set(result['stop_reasons'])
    assert result['next_questions'] == []
    page = env['client'].get(card_url(env))
    assert 'Вопрос о возврате денег' in page.text and 'Передача в работу ещё не выполнена' in page.text
