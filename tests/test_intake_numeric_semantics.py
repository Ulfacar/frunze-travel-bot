"""JSON Schema integers include integral JSON floats; semantics must agree."""
import asyncio

import pytest

from app.domain.qualification_storage import save_qualification, read_qualification
from app.knowledge.qualification import QualificationError
from tests.test_kg_qualification import bundle, review
from tests.test_kg_intake import intake_request
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_applicant_profiles import save, read
from tests.test_entry_applications import person


@pytest.mark.parametrize('count', [6, 6.0])
def test_validated_numeric_group_count_always_stops(review, count):
    request = intake_request(); request['profile']['applicants_count'] = count
    result = review.evaluate(request)
    assert 'large_group_review' in result['stop_reasons']
    assert result['next_questions'] == []


@pytest.mark.parametrize('count', [1, 1.0])
def test_validated_numeric_family_count_cannot_omit_the_applicant(review, count):
    request = intake_request(); request['profile'].update(applicants_count=count, family=[
        dict(relation='child', age=8, travels_together=True, both_parents_travel=True)])
    with pytest.raises(QualificationError, match='family_exceeds_applicants'):
        review.evaluate(request)


@pytest.mark.parametrize('count', [True, 6.5, 0, -1, '6'])
def test_invalid_numeric_representations_stay_invalid(review, count):
    request = intake_request(); request['profile']['applicants_count'] = count
    with pytest.raises(QualificationError): review.evaluate(request)


def test_float_count_is_retained_but_group_stop_is_persisted_for_contact_and_person(env):
    request = intake_request(); request['profile']['applicants_count'] = 6.0
    arguments = dict(actor=ADMIN, contact_id=env['contacts']['visa'], expected_revision=0,
        request_key='numeric-count', knowledge_version_id=env['version'], request=request)
    first = asyncio.run(save_qualification(env['engine'], **arguments))
    retried = asyncio.run(save_qualification(env['engine'], **arguments))
    assert retried['reused'] and retried['qualification_id'] == first['qualification_id']
    loaded = asyncio.run(read_qualification(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa']))
    assert loaded['input']['profile']['applicants_count'] == 6.0
    assert 'large_group_review' in loaded['result']['stop_reasons']
    applicant = person(env)
    profile = save(env, applicant, doc=request)
    assert 'large_group_review' in profile['result']['stop_reasons']
    assert read(env, applicant, replay=True)['saved'] == profile


@pytest.mark.parametrize('individual', [False, True])
def test_saved_integral_floats_roundtrip_through_signed_native_form(env, individual):
    from tests.test_admin_kg_entry import Form
    request = intake_request(); request['profile'].update(applicants_count=6.0, family=[
        dict(relation='child', age=8.0, travels_together=True, both_parents_travel=True)])
    if individual:
        applicant=person(env); first=save(env,applicant,doc=request)
        url=env['url']+f"/applicants/{applicant['id']}/qualification"
    else:
        first=asyncio.run(save_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],
            expected_revision=0,request_key='float-native',knowledge_version_id=env['version'],request=request))
        url=env['url']
    page=env['client'].get(url); assert page.status_code==200
    form=Form(page.text).data
    assert form['applicants_count']=='6' and form['family.0.age']=='8'
    submitted=env['client'].post(url,data=form,follow_redirects=False)
    assert submitted.status_code==303, submitted.text[-1000:]
    if individual:
        latest=read(env,applicant)['saved']
        old=read(env,applicant,qualification_id=first['qualification_id'])['saved']
    else:
        latest=asyncio.run(read_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa']))
        old=asyncio.run(read_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],
            qualification_id=first['qualification_id']))
    assert latest['revision']==2 and 'large_group_review' in latest['result']['stop_reasons']
    assert old==first


def test_integer_display_does_not_relax_strict_submitted_string_parser():
    from app.admin.kg_entry_form import values_from_request,request_from_values,FormInvalid
    request=intake_request(); values=values_from_request(request)
    values['applicants_count']='6.0'; values['applicants_count_state']='value'
    with pytest.raises(FormInvalid):request_from_values(values,as_of=request['as_of'],base_request=request)
