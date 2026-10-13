"""Pinned case/qualification read path: real synthetic DB, HTTP and domain guards."""
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

import app.admin.router as ar
import app.main as main
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.permissions import Actor
from app.domain.qualification_card import read_qualification_card
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, complete_data, count, env, form_data, post, saved
from tests.test_admin_workday import _login, _on


def card_url(env, qid=None, case=None):
    return f"/admin/case/{case or env['cases']['visa']}/kg-entry/review/{qid or saved(env)['qualification_id']}"


def seed(env, **changes):
    data = complete_data(env)
    data.update(changes)
    assert post(env, data).status_code == 303
    return saved(env)


def test_saved_card_is_readable_pinned_and_read_only(env):
    first = seed(env)
    url = card_url(env)
    assert url in env['client'].get(env['url']).text
    mutations = []
    def record(conn, cursor, statement, params, context, many):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}:
            mutations.append(statement)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', record)
    try:
        response = env['client'].get(url)
        repeated = env['client'].get(url)
    finally:
        event.remove(env['engine'].sync_engine, 'before_cursor_execute', record)
    assert response.status_code == repeated.status_code == 200
    assert response.text == repeated.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'Обычный паспорт' in response.text and 'Туризм' in response.text
    assert '2030-01-01' in response.text and '2026-11-10' in response.text
    assert f"Анкета №{first['qualification_id']}, версия 1" in response.text
    assert 'Передача в работу ещё не выполнена' in response.text
    assert 'KG.VF.TEST' in response.text and 'Synthetic fixture' in response.text
    assert '(F1)' not in response.text  # Tourism does not imply an inviter requirement.
    assert '(A5)' in response.text and '(G1)' in response.text
    assert not mutations and count(env) == 1


def test_old_card_keeps_its_answers_and_points_to_new_version(env):
    first = seed(env)
    second = seed(env, purpose='work_hire')
    old = env['client'].get(card_url(env, first['qualification_id']))
    new = env['client'].get(card_url(env, second['qualification_id']))
    assert old.status_code == new.status_code == 200
    assert 'Есть более новая версия анкеты' in old.text
    assert card_url(env, second['qualification_id']) in old.text
    assert '<dd>Туризм</dd>' in old.text and 'Цель связана с работой' not in old.text
    assert 'Есть более новая версия анкеты' not in new.text
    assert '<dd>Работа по найму</dd>' in new.text and 'Цель связана с работой' in new.text
    assert '(F1)' in new.text and 'kg-card-questions' not in new.text


def test_partial_english_questions_false_unknown_and_not_asked(env):
    data = form_data(env)
    data.update({'language': 'en', 'violations.overstay': 'false', 'violations.fines': 'unknown'})
    assert post(env, data).status_code == 303
    page = env['client'].get(card_url(env)).text
    assert 'What citizenships do you hold?' in page
    assert '<dd>Нет</dd>' in page and '<dd>Клиент не знает</dd>' in page and '<dd>Не спрашивали</dd>' in page
    assert '(F1)' in page and 'Неуточнённые ответы анкеты' in page
    assert 'Режим въезда, тип визы, стоимость и точный срок этой карточкой не утверждены' in page


def test_current_stay_and_refusal_details_remain_explicit_gaps(env):
    seed(env, current_location='in_kg', current_basis_in_kg='visa', current_visa_type='TS',
         in_kg_since='2026-10-01', in_kg_since_state='value', previous_refusals_kg='true')
    page = env['client'].get(card_url(env)).text
    assert 'Текущее пребывание в Кыргызстане' in page and '<dd>2026-10-01</dd>' in page
    assert 'Пункт фактического въезда в Кыргызстан (B8)' in page and '(D4)' in page
    seed(env, current_location='abroad')
    assert 'Текущее пребывание в Кыргызстане' not in env['client'].get(card_url(env)).text


@pytest.mark.parametrize('login', [None, 'ademi', 'medina'])
def test_http_non_admin_denied_before_domain(env, monkeypatch, login):
    def forbidden():
        raise AssertionError('domain was accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    client = _login(login) if login else TestClient(main.app, base_url='https://testserver')
    try:
        assert client.get(card_url(env, 1)).status_code == (401 if login is None else 403)
    finally:
        client.close()


@pytest.mark.parametrize('actor', [Actor('medina', False, frozenset({'visa'})), Actor('', True)])
def test_domain_non_admin_denied_even_without_http(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(read_qualification_card(None, actor=actor, case_id=1, qualification_id=1))


@pytest.mark.parametrize('field,value', [('case_id', True), ('case_id', 0), ('qualification_id', 0),
                                        ('qualification_id', 2**31), ('qualification_id', '1')])
def test_domain_identifiers_checked_before_db(field, value):
    args = {'case_id': 1, 'qualification_id': 1, field: value}
    with pytest.raises(EntryStorageInvalid):
        asyncio.run(read_qualification_card(None, actor=ADMIN, **args))


def test_foreign_contact_other_direction_and_absent_id_have_no_fallback(env):
    first = seed(env)
    for url in [card_url(env, first['qualification_id'], env['cases']['other']),
                card_url(env, first['qualification_id'], env['cases']['tours']),
                card_url(env, first['qualification_id'], 2147483647), card_url(env, 2147483647)]:
        response = env['client'].get(url)
        assert response.status_code == 404 and '2030-01-01' not in response.text
        assert response.headers['cache-control'] == 'no-store'
    for cid in [env['cases']['other'], env['cases']['tours']]:
        with pytest.raises(EntryStorageInvalid):
            asyncio.run(read_qualification_card(env['engine'], actor=ADMIN, case_id=cid,
                                                 qualification_id=first['qualification_id']))


def test_feature_and_workday_off_precede_domain_but_write_off_allows_read(env, monkeypatch):
    seed(env)
    url = card_url(env)
    _on(monkeypatch, write=False)
    assert env['client'].get(url).status_code == 200
    def forbidden():
        raise AssertionError('domain was accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', False)
    assert env['client'].get(url).status_code == 404
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', True)
    monkeypatch.setattr(ar.settings, 'admin_workday_enabled', False)
    assert env['client'].get(url).status_code == 404


@pytest.mark.parametrize('fault', ['snapshot', 'source', 'missing_import'])
def test_corrupted_or_missing_source_fails_without_partial_card(env, fault):
    seed(env)
    url = card_url(env)
    async def corrupt():
        statements = {'snapshot': 'UPDATE entry_qualifications SET snapshot_hash=:bad',
                      'source': 'UPDATE knowledge_versions SET bundle_hash=:bad',
                      'missing_import': 'DELETE FROM knowledge_imports'}
        async with env['engine'].begin() as conn:
            await conn.execute(text(statements[fault]), {'bad': '0' * 64})
    asyncio.run(corrupt())
    response = env['client'].get(url)
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert '2030-01-01' not in response.text and 'Туризм' not in response.text


def test_db_failure_is_generic_and_query_payload_is_never_used(env, monkeypatch, caplog):
    seed(env)
    url = card_url(env)
    response = env['client'].get(url + '?purpose=work_hire&contact_id=999&profile=PRIVATE-INJECT')
    assert response.status_code == 200 and '<dd>Туризм</dd>' in response.text
    assert 'PRIVATE-INJECT' not in response.text
    def unavailable():
        raise RuntimeError('PRIVATE-CONNECTION')
    monkeypatch.setattr(ar, '_domain_sessionmaker', unavailable)
    response = env['client'].get(url)
    assert response.status_code == 503 and 'PRIVATE-CONNECTION' not in response.text + caplog.text


def test_case_labels_are_html_escaped_and_owner_is_explicitly_current(env):
    seed(env)
    url = card_url(env)
    payload = '<script>window.syntheticAttack=1</script>'
    async def change():
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE products SET name=:name'), {'name': payload})
            await conn.execute(text('UPDATE service_cases SET owner_login=:name WHERE id=:id'),
                               {'name': payload, 'id': env['cases']['visa']})
    asyncio.run(change())
    page = env['client'].get(url)
    assert page.status_code == 200 and payload not in page.text
    assert '&lt;script&gt;' in page.text and 'Ответственный за услугу сейчас' in page.text


def test_card_has_no_write_endpoint(env):
    seed(env)
    assert env['client'].post(card_url(env), data={'action': 'handoff'}).status_code == 405
    assert count(env) == 1


def test_saved_report_is_not_recomputed_with_new_algorithm(env, monkeypatch):
    from app.knowledge.qualification import QualificationReview
    seed(env)
    url = card_url(env)
    def forbidden(*args, **kwargs):
        raise AssertionError('old report was recomputed')
    monkeypatch.setattr(QualificationReview, 'evaluate', forbidden)
    page = env['client'].get(url)
    assert page.status_code == 200 and 'Проверка на дату 2026-10-09' in page.text


def test_history_gaps_remain_visible_in_review_and_print(env):
    from app.domain.entry_storage import save_stay_history
    history = {'format': 'kg-stay-history/1', 'as_of': '2026-10-01', 'history_complete': None, 'intervals': []}
    asyncio.run(save_stay_history(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'],
        expected_revision=0, request_key='card-history', document=history))
    seed(env)
    page = env['client'].get(card_url(env))
    assert page.status_code == 200
    assert 'Полнота истории поездок не подтверждена' in page.text
    assert 'История поездок составлена на другую дату' in page.text


def test_conflicting_rule_is_shown_for_source_review(env):
    seed(env, citizenship=['MDA'], entry_passport_country='MDA')
    page = env['client'].get(card_url(env))
    assert page.status_code == 200 and 'В источниках есть противоречие' in page.text
    assert 'противоречие источников' in page.text


def test_attached_specialist_facts_are_visible_without_implied_approval(env):
    from app.domain.qualification_storage import save_qualification
    from app.knowledge.validation import load_document
    from tests.test_entry_storage import FIX
    request = load_document(FIX / 'synthetic_qualification_review.json')
    request['condition_facts'] = {
        'schema_version': 'kg-entry-condition-facts/1',
        'residence_documents': {'items': [{'country': 'RUS', 'kind': 'residence_permit', 'permanent': False}], 'complete': False},
        'foreign_visas': {'items': [{'issuer': 'SCHENGEN', 'over_three_years_verified': None}], 'complete': True},
        'tour_group': {'organized': False, 'participants_count': 5},
        'requested_visa_type': 'TS', 'stay_within_one_month_verified': None,
    }
    asyncio.run(save_qualification(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'],
        expected_revision=0, request_key='card-conditions', knowledge_version_id=env['version'], request=request))
    page = env['client'].get(card_url(env))
    assert page.status_code == 200
    for expected in ('Вид на жительство', 'Шенген', '<dd>5</dd>', '<dd>TS</dd>', '<dd>Нет</dd>',
                     '<dd>Неизвестно</dd>', '<dd>Не спрашивали</dd>'):
        assert expected in page.text
    assert 'не подтверждает применимость правила' in page.text


@pytest.mark.parametrize('value', ['0', '-1', '2147483648', 'not-an-id'])
def test_http_rejects_bad_snapshot_identifier(env, value):
    page = env['client'].get(env['url'] + '/review/' + value)
    assert page.status_code == 422 and count(env) == 0
