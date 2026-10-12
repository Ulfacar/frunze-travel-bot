"""Independent boundary controls for preliminary opening/signature evidence."""
import asyncio

from sqlalchemy import select, text

from app.domain import live_assign
from app.domain.models import ServiceCase, ServiceEvent
from tests.test_admin_precontract import env, contract_env, open_data, signed_data
from tests.test_admin_contracts import snapshot


def test_exact_open_retry_after_assignment_disagreement_is_historical_not_fresh(env):
    data = open_data(env)
    first = env['client'].post(env['url'], data=data, follow_redirects=False)
    assert first.status_code == 303
    assert env['client'].post(env['url'], data=data, follow_redirects=False).status_code == 303
    case_id = int(first.headers['location'].rsplit('/', 1)[1])
    async def reassign_contact():
        async with env['sm']() as session:
            case = await session.get(ServiceCase, case_id)
            await live_assign.assign_locked(session, case.contact_id, 'visa', 'aisina',
                assigned_by='admin', reason='Synthetic later assignment', allow_emergency=True)
            await session.commit()
    asyncio.run(reassign_contact())
    before = snapshot(env['sm'])
    # A fresh operation must still refuse the inconsistent current assignment.
    assert env['client'].get(env['url']).status_code == 422
    repeated = env['client'].post(env['url'], data=data, follow_redirects=False)
    assert repeated.status_code == 303, repeated.text
    assert repeated.headers['location'] == first.headers['location']
    assert snapshot(env['sm']) == before


def test_malformed_signed_event_yields_controlled_failure_and_preserves_form(env):
    opened = env['client'].post(env['url'], data=open_data(env), follow_redirects=False)
    assert opened.status_code == 303
    case_id = int(opened.headers['location'].rsplit('/', 1)[1])
    url = opened.headers['location'] + '/contract'
    data = signed_data(env, url)
    assert env['client'].post(url, data=data, follow_redirects=False).status_code == 303
    async def corrupt():
        async with env['sm']() as session:
            event = await session.scalar(select(ServiceEvent).where(ServiceEvent.case_id == case_id,
                ServiceEvent.event_type == 'contract_signed'))
            await session.execute(text('UPDATE service_events SET payload = :payload WHERE id = :id'),
                {'payload': '[]', 'id': event.id})
            await session.commit()
    asyncio.run(corrupt())
    response = env['client'].post(url, data=data, follow_redirects=False)
    assert response.status_code in (409, 422, 503)
    assert data['request_key'] in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_altered_signed_event_stage_cannot_be_replayed_as_valid_evidence(env):
    opened = env['client'].post(env['url'], data=open_data(env), follow_redirects=False)
    case_id = int(opened.headers['location'].rsplit('/', 1)[1])
    url = opened.headers['location'] + '/contract'
    data = signed_data(env, url)
    assert env['client'].post(url, data=data, follow_redirects=False).status_code == 303
    async def corrupt():
        async with env['sm']() as session:
            await session.execute(text("UPDATE service_events SET to_stage = :stage WHERE case_id = :id AND event_type = 'contract_signed'"),
                {'stage': 'SYN-FORGED-STAGE', 'id': case_id})
            await session.commit()
    asyncio.run(corrupt())
    response = env['client'].post(url, data=data, follow_redirects=False)
    assert response.status_code in (409, 422, 503), response.status_code
