"""Real native history editor, snapshot binding and qualification/print integration."""
import asyncio
from copy import deepcopy
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session

import app.admin.kg_history as ui
import app.admin.router as ar
import app.main as main
from app.admin.kg_history_form import DEFAULTS, countries, document_from_values, values_from_history
from app.domain.entry_storage import read_stay_history, save_stay_history
from app.domain.models import EntryQualification, StayHistory
from tests.test_admin_kg_entry import ADMIN, Form, complete_data, env, post, saved
from tests.test_admin_workday import _login
from tests.test_qualification_card import card_url


def url(env): return env['url'] + '/history'


def data(env, *, response=None):
    page = response if response is not None else env['client'].get(url(env))
    assert page.status_code in (200, 409, 422, 503), page.text[:1000]
    return {**Form(page.text, 'kg-history-form').data, 'history_action': 'save'}


def trip(values, i=0, **changes):
    defaults = {**DEFAULTS, 'entry_date': '2026-09-01', 'exit_state': 'date', 'exit_date': '2026-09-10',
                'basis': 'visa_free', 'passport_country': 'RUS'}
    defaults.update(changes)
    values.update({f'trip.{i}.{key}': value for key, value in defaults.items()})
    return values


def submit(env, values, *, path=None, client=None):
    return (client or env['client']).post(path or url(env), data=values, follow_redirects=False)


def latest(env, *, contact='visa', history_id=None):
    async def run():
        async with env['sm']() as s:
            row = (await s.execute(select(StayHistory.id, StayHistory.previous_id).where(
                StayHistory.contact_id == env['contacts'][contact]).order_by(StayHistory.revision.desc()).limit(1))).first()
        if not row: return None
        return await read_stay_history(env['engine'], actor=ADMIN, contact_id=env['contacts'][contact], history_id=history_id or row.id)
    return asyncio.run(run())


def count(env):
    async def run():
        async with env['sm']() as s: return await s.scalar(select(func.count()).select_from(StayHistory))
    return asyncio.run(run())


def test_get_has_labels_and_no_writes(env):
    writes = []
    def record(conn, cursor, statement, params, context, many):
        if statement.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE'}: writes.append(statement)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', record)
    try: response = env['client'].get(url(env))
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', record)
    assert response.status_code == 200 and not writes
    assert response.headers['cache-control'] == 'no-store' and response.headers['referrer-policy'] == 'no-referrer'
    form = Form(response.text, 'kg-history-form')
    labels = {a['for'] for tag, a in form.nodes if tag == 'label' and 'for' in a}
    controls = [a for tag, a in form.nodes if tag in ('input', 'select') and a.get('type') not in ('hidden', 'checkbox')]
    assert all(a['id'] in labels for a in controls)
    assert url(env) in env['client'].get(env['url']).text


def test_native_save_repeat_edit_old_version_and_explicit_removal(env):
    original = trip(data(env)); original['history_complete'] = 'false'
    response = submit(env, original)
    assert response.status_code == 303 and response.headers['x-action-outcome'] == 'history_saved'
    first = latest(env)
    assert first['document']['intervals'][0]['confirmed'] is False and count(env) == 1
    assert submit(env, original).headers['location'] == response.headers['location'] and count(env) == 1
    changed = data(env); changed['trip.0.exit_date'] = '2026-09-11'
    assert submit(env, changed).status_code == 303 and latest(env)['revision'] == 2
    old = env['client'].get(response.headers['location'])
    assert 'Предыдущая версия' not in old.text or 'Открыта предыдущая версия' in old.text
    assert 'Открыта предыдущая версия' in old.text and 'name="history_action"' not in old.text
    assert latest(env, history_id=first['history_id']) == first
    remove = data(env); remove['trip.0.remove'] = 'yes'
    assert submit(env, remove).status_code == 303
    assert latest(env)['document']['intervals'] == [] and latest(env, history_id=first['history_id']) == first


def test_add_row_keeps_unsaved_values_and_nonce_without_storage(env):
    values = trip(data(env)); values['history_action'] = 'add'
    response = submit(env, values)
    assert response.status_code == 200 and count(env) == 0
    echoed = data(env, response=response)
    assert echoed['trip.0.entry_date'] == '2026-09-01' and echoed['rows_count'] == '2'
    assert echoed['_sh_key'] == values['_sh_key'] and echoed['_sh_signature'] == values['_sh_signature']
    trip(echoed, 1, entry_date='2026-09-20', exit_state='ongoing', exit_date='')
    assert submit(env, echoed).status_code == 303 and len(latest(env)['document']['intervals']) == 2


@pytest.mark.parametrize('state, expected', [('unknown', None), ('false', False), ('true', True)])
def test_empty_history_completeness_is_explicit(env, state, expected):
    values = data(env); values['history_complete'] = state
    if expected is True:
        assert submit(env, values).status_code == 422
        values['no_trips'] = 'yes'
    assert submit(env, values).status_code == 303
    assert latest(env)['document']['history_complete'] is expected


@pytest.mark.parametrize('changes', [
    {'trip.0.exit_state': 'unknown'}, {'trip.0.exit_state': ''},
    {'trip.0.entry_date': ''}, {'trip.0.entry_date': '2026-10-10'},
    {'trip.0.exit_date': '2026-08-30'}, {'trip.0.exit_date': '2026-10-10'},
    {'trip.0.confirmed': 'true'}, {'trip.0.passport_country': 'ZZZ'},
    {'trip.0.basis': 'made_up'}, {'no_trips': 'yes'},
])
def test_invalid_facts_are_retryable_without_history(env, changes):
    values = trip(data(env)); values.update(changes)
    response = submit(env, values)
    assert response.status_code == 422 and count(env) == 0
    echoed = data(env, response=response)
    assert echoed['_sh_key'] == values['_sh_key']
    for key, value in changes.items():
        # Unknown select values get a fixed error rather than an invented option.
        if key != 'trip.0.basis': assert echoed[key] == value


def test_two_open_intervals_rejected_and_closed_overlap_is_visible(env):
    values = trip(data(env), exit_state='ongoing', exit_date=''); values['history_action'] = 'add'
    values = data(env, response=submit(env, values))
    trip(values, 1, entry_date='2026-09-20', exit_state='ongoing', exit_date='')
    assert submit(env, values).status_code == 422 and count(env) == 0
    trip(values, 0); trip(values, 1, entry_date='2026-09-09', exit_date='2026-09-12')
    response = submit(env, values)
    assert response.status_code == 303
    assert 'Даты некоторых поездок пересекаются' in env['client'].get(response.headers['location']).text


def test_explicit_history_attachment_creates_new_qualification_only(env):
    assert post(env, complete_data(env)).status_code == 303
    old_qualification = saved(env)
    values = trip(data(env), evidence='passport_stamp', confirmed='true'); values['history_complete'] = 'true'
    assert submit(env, values).status_code == 303
    history = latest(env)
    assert saved(env) == old_qualification
    assert Form(env['client'].get(env['url']).text).data['_kg_history'] == '0'
    page = env['client'].get(env['url'], params={'history_id': history['history_id']})
    assert page.status_code == 200 and 'Для новой проверки выбрана история' in page.text
    assert Form(page.text).data['_kg_history'] == str(history['history_id'])
    invalid = Form(page.text).data
    invalid['passport_expiry'] = 'not-a-date'
    failure = post(env, invalid)
    assert failure.status_code == 422 and f"Для новой проверки выбрана история №{history['history_id']}" in failure.text
    assert Form(failure.text).data['_kg_history'] == str(history['history_id'])
    assert Form(failure.text).data['_kg_key'] == invalid['_kg_key'] and saved(env) == old_qualification
    assert post(env, Form(page.text).data).status_code == 303
    second = saved(env)
    assert second['result']['history']['history_id'] == history['history_id']
    assert saved(env, qid=old_qualification['qualification_id']) == old_qualification
    card = env['client'].get(card_url(env)).text
    assert 'Фактические поездки из этой проверки' in card and '2026-09-10' in card and 'Отметка в паспорте' in card
    old_card = env['client'].get(card_url(env, old_qualification['qualification_id'])).text
    assert 'Фактические поездки из этой проверки' not in old_card
    revised = data(env); revised['trip.0.exit_date'] = '2026-09-12'
    assert submit(env, revised).status_code == 303
    assert '2026-09-12' not in env['client'].get(card_url(env)).text
    both = env['client'].get(env['url'], params={'qualification_id': second['qualification_id'], 'history_id': history['history_id']})
    assert both.status_code == 422


def test_foreign_history_and_tour_case_are_unavailable(env):
    assert submit(env, trip(data(env))).status_code == 303
    hid = latest(env)['history_id']
    other = f"/admin/case/{env['cases']['other']}/kg-entry"
    assert env['client'].get(other + '/history', params={'history_id': hid}).status_code == 404
    assert env['client'].get(other, params={'history_id': hid}).status_code == 503
    assert env['client'].get(f"/admin/case/{env['cases']['tours']}/kg-entry/history").status_code == 404


@pytest.mark.parametrize('login', [None, 'medina', 'ademi'])
def test_permissions_precede_domain(env, monkeypatch, login):
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    client = _login(login) if login else TestClient(main.app, base_url='https://testserver')
    try:
        assert client.get(url(env)).status_code == (401 if login is None else 403)
        assert submit(env, {}, client=client).status_code == (401 if login is None else 403)
    finally: client.close()


@pytest.mark.parametrize('flag', ['admin_kg_entry_enabled', 'admin_workday_enabled'])
def test_off_gate_precedes_storage(env, monkeypatch, flag):
    monkeypatch.setattr(ar.settings, flag, False)
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    assert env['client'].get(url(env)).status_code == 404 and submit(env, {}).status_code == 404


def test_write_off_allows_only_read(env, monkeypatch):
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', False)
    assert env['client'].get(url(env)).status_code == 200
    assert submit(env, {}).status_code == 403


@pytest.mark.parametrize('key', ['_sh_key', '_sh_contact', '_sh_base', '_sh_revision', '_sh_asof', '_sh_csrf', '_sh_signature'])
def test_forged_envelope_is_rejected(env, key):
    values = trip(data(env)); values[key] = 'forged'
    assert submit(env, values).status_code == 403 and count(env) == 0


def test_case_session_and_cross_form_tokens_do_not_authorize_history(env):
    values = trip(data(env))
    assert submit(env, values, path=f"/admin/case/{env['cases']['other']}/kg-entry/history").status_code == 403
    other_session = _login('admin')
    try: assert submit(env, values, client=other_session).status_code == 403
    finally: other_session.close()
    qualification = complete_data(env)
    values['_sh_csrf'] = qualification['_kg_csrf']; values['_sh_signature'] = qualification['_kg_signature']
    assert submit(env, values).status_code == 403 and count(env) == 0


def test_stale_form_and_changed_retry_do_not_duplicate(env):
    first = trip(data(env)); stale = trip(data(env))
    assert submit(env, first).status_code == 303
    assert submit(env, stale).status_code == 409
    first['trip.0.exit_date'] = '2026-09-11'
    assert submit(env, first).status_code == 409 and count(env) == 1


def test_lost_acknowledgement_retries_same_request(env):
    values = trip(data(env)); fired = False
    def fail(session):
        nonlocal fired
        if not fired: fired = True; raise RuntimeError('PRIVATE-SYNTHETIC-ACK')
    event.listen(Session, 'after_commit', fail)
    try: response = submit(env, values)
    finally: event.remove(Session, 'after_commit', fail)
    assert fired and response.status_code == 503 and 'PRIVATE' not in response.text
    assert count(env) == 1
    retry = data(env, response=response)
    assert retry['_sh_key'] == values['_sh_key'] and submit(env, retry).status_code == 303 and count(env) == 1


def test_saved_rows_cannot_disappear_by_omission(env):
    assert submit(env, trip(data(env))).status_code == 303
    values = data(env); del values['trip.0.entry_date']
    assert submit(env, values).status_code == 422 and count(env) == 1


def test_corrupt_history_is_not_editable_or_silently_replaced(env):
    assert submit(env, trip(data(env))).status_code == 303
    values = data(env)
    async def corrupt():
        async with env['engine'].begin() as c: await c.execute(text("UPDATE stay_histories SET snapshot_hash=:h"), {'h': '0' * 64})
    asyncio.run(corrupt())
    page = env['client'].get(url(env))
    assert page.status_code == 503 and 'id="kg-history-form"' not in page.text
    assert submit(env, values).status_code == 503 and count(env) == 1


def test_unavailable_registry_keeps_verified_retry_form(env, monkeypatch):
    values = trip(data(env))
    async def fail(*args, **kwargs): raise RuntimeError('PRIVATE')
    with monkeypatch.context() as patch:
        patch.setattr(ui, 'save_stay_history', fail); patch.setattr(ui, '_context', fail)
        response = submit(env, values)
    assert response.status_code == 503 and 'PRIVATE' not in response.text
    retry = data(env, response=response)
    assert retry['trip.0.entry_date'] == values['trip.0.entry_date'] and submit(env, retry).status_code == 303


@pytest.mark.parametrize('fault,expected', [('duplicate', 422), ('extra', 422), ('bad_utf8', 422), ('large', 413), ('json', 415), ('outside_count', 422)])
def test_bounded_form_rejects_invalid_wire(env, fault, expected):
    values = trip(data(env)); body = urlencode(values).encode(); content_type = 'application/x-www-form-urlencoded'
    if fault == 'duplicate': body += b'&history_complete=false'
    if fault == 'extra': body += b'&trip.0.passport_number=PRIVATE'
    if fault == 'outside_count': body += b'&trip.999.entry_date=2026-09-01'
    if fault == 'bad_utf8': body = b'q=%FF'
    if fault == 'large': body = b'x' * (ui.BODY_LIMIT + 1)
    if fault == 'json': content_type = 'application/json'; body = b'{}'
    response = env['client'].post(url(env), content=body, headers={'content-type': content_type})
    assert response.status_code == expected and count(env) == 0


@pytest.mark.parametrize('change', [{'trip.0.clear_passport': 'yes'}, {'trip.0.passport_country': 'KGZ'}])
def test_opaque_passport_binding_is_preserved_without_exposure_then_cleared(env, change):
    document = {'format': 'kg-stay-history/1', 'as_of': '2026-10-01', 'history_complete': True, 'intervals': [
        {'ref': 'opaque-trip', 'entry_date': '2026-09-01', 'exit_date': '2026-09-10', 'basis': 'visa_free',
         'passport_country': 'RUS', 'passport_ref': 'a' * 32, 'confirmed': True, 'evidence': 'passport_stamp'}]}
    asyncio.run(save_stay_history(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'], expected_revision=0,
                                 request_key='seed-opaque', document=document))
    page = env['client'].get(url(env))
    assert 'a' * 32 not in page.text and 'opaque-trip' not in page.text
    values = data(env, response=page)
    assert submit(env, values).status_code == 303 and latest(env)['document']['intervals'][0]['passport_ref'] == 'a' * 32
    values = data(env); values.update(change)
    assert submit(env, values).status_code == 303 and latest(env)['document']['intervals'][0]['passport_ref'] is None


def test_adapter_preserves_all_one_thousand_trips_and_rejects_silent_truncation():
    row = {'ref': 'r', 'entry_date': '2026-09-01', 'exit_date': '2026-09-10', 'basis': 'visa_free',
           'passport_country': 'RUS', 'passport_ref': None, 'confirmed': False, 'evidence': 'client_statement'}
    base = {'format': 'kg-stay-history/1', 'as_of': '2026-10-01', 'history_complete': False,
            'intervals': [{**row, 'ref': f'r-{i:04d}'} for i in range(1000)]}
    values = values_from_history(base)
    result = document_from_values(values, base=base, as_of=base['as_of'], request_key='k', country_codes=countries())
    assert result == base
    values['rows_count'] = '999'
    with pytest.raises(ValueError, match='неполная'):
        document_from_values(values, base=base, as_of=base['as_of'], request_key='k', country_codes=countries())
