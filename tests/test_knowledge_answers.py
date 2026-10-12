"""Synthetic approved publications -> real read-only answer API, without network."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import shutil

import pytest
import yaml
from sqlalchemy import event

from app.domain import entry_applications, knowledge_answers as answers, knowledge_decisions, knowledge_publication
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, FIX, env
from tests.test_knowledge_decisions import data, sql, write as review
from tests.test_knowledge_publication import IDS, POLICY, activate, load_source, preview, publish, release


@pytest.fixture(autouse=True)
def source_clock(monkeypatch):
    current = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
    def now():
        nonlocal current
        current += timedelta(microseconds=1)
        return current
    for module in (entry_applications, knowledge_decisions, knowledge_publication):
        monkeypatch.setattr(module, '_now', now)


def answer(env, ids=IDS, language='ru', policy=POLICY):
    return asyncio.run(answers.answer_knowledge(env['engine'], actor=ADMIN, policy=policy,
                                               unit_ids=ids, language=language))


def test_literal_answer_retains_deadline_and_window_without_writes(release):
    activate(release)
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(release['engine'].sync_engine, 'before_cursor_execute', capture)
    try:
        for language in ('ru', 'en'):
            result = answer(release, language=language)
            assert result['status'] == 'answered' and not result['requires_specialist']
            assert result['personal_eligibility'] == 'not_evaluated' and result['delivery'] == 'not_sent'
            deadline, window = result['answers']
            assert len(deadline['facts']) == 7
            assert 'Asia/Bishkek' in deadline['text'] and 'entry_date' in deadline['text']
            assert ('до' if language == 'ru' else 'before') in deadline['text']
            assert 'RUS' in window['text'] and 'CHL' in window['text']
            for item in result['answers']:
                assert item['source']['version_id'] == release['release']
                assert item['source']['source_ref'].startswith('Synthetic official-source')
                assert all(len(item['source'][key]) == 64 for key in ('source_hash', 'unit_hash', 'manifest_hash'))
                assert item['unit_id'] in item['text'] and item['source']['version_label'] in item['text']
    finally:
        event.remove(release['engine'].sync_engine, 'before_cursor_execute', capture)
    assert statements and not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER'}


def test_mixed_unpublished_rejected_withdrawn_and_revoked_policy(release):
    before = answer(release)
    assert not before['answers'] and before['requires_specialist']
    activate(release)
    manifest = preview(release)['manifest_hash']
    result = answer(release, IDS + ['KG.FEE.SERVICE.TEST'])
    assert result['status'] == 'partial' and len(result['answers']) == 2
    assert result['unavailable'] == [dict(unit_id='KG.FEE.SERVICE.TEST', reasons=['unit_not_published'])]
    review(release, {**data(), 'verdict': 'rejected', 'reason': 'source_conflict', 'review_due_on': None},
           unit=IDS[0], version=release['release'], key='reject-answer')
    result = answer(release)
    assert result['status'] == 'partial' and [item['unit_id'] for item in result['answers']] == [IDS[1]]
    assert 'review_changed_since_approval' in result['unavailable'][0]['reasons']
    assert not answer(release, policy=None)['answers']
    assert not answer(release, policy=replace(POLICY, fingerprint='b'*64))['answers']
    publish(release, 'withdraw', manifest=manifest)
    assert not answer(release)['answers']


def test_current_version_and_exact_expiry_boundary(release, tmp_path, monkeypatch):
    activate(release)
    original = answer(release)
    second = load_source(release, tmp_path, changes={IDS[0]: {'value': dict(value=9, unit='working_days',
        anchor='entry_date', direction='before', timezone='Asia/Bishkek', boundary_inclusive=True,
        shift_from_nonworking='none')}}, tag='answer-second')
    activate(release, version=second)
    current = answer(release)
    assert current['version_id'] == second != original['version_id']
    assert next(f['value'] for f in current['answers'][0]['facts'] if f['label'] == 'Значение') == '9'
    assert next(f['value'] for f in original['answers'][0]['facts'] if f['label'] == 'Значение') == '3'
    monkeypatch.setattr(knowledge_publication, '_now', lambda: datetime(2026, 12, 1, tzinfo=timezone.utc))
    expired = answer(release)
    assert not expired['answers'] and all('source_review_expired' in row['reasons'] for row in expired['unavailable'])


def test_corruption_and_clock_regression_never_resurrect_source(release, monkeypatch):
    activate(release)
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_publication, '_now', lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
        assert not answer(release)['answers']
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_decisions, '_now', lambda: datetime(2026, 11, 1, tzinfo=timezone.utc))
        review(release, {**data(), 'verdict': 'rejected', 'reason': 'withdrawn', 'review_due_on': None},
               unit=IDS[0], version=release['release'], key='future-reject')
    result = answer(release)
    assert [item['unit_id'] for item in result['answers']] == [IDS[1]]
    assert 'review_record_in_future' in result['unavailable'][0]['reasons']
    sql(release, 'UPDATE knowledge_publication_units SET unit_hash=:hash WHERE unit_id=:unit', hash='0'*64, unit=IDS[1])
    assert not answer(release)['answers']


def test_projection_corruption_and_storage_outage_fall_back(release, monkeypatch):
    from app.domain.entry_storage import EntryStorageUnavailable
    activate(release)
    with monkeypatch.context() as patch:
        async def unavailable(*args, **kwargs):
            raise EntryStorageUnavailable('synthetic private storage diagnostic')
        patch.setattr(knowledge_publication, 'runtime_knowledge', unavailable)
        result = answer(release)
        assert not result['answers'] and 'private storage diagnostic' not in json.dumps(result)
    sql(release, 'UPDATE knowledge_projections SET projection_hash=:hash WHERE version_id=:version',
        hash='0'*64, version=release['release'])
    result = answer(release)
    assert not result['answers'] and result['status'] == 'specialist_required'


@pytest.mark.parametrize('actor', [None, Actor('admin'), Actor('system', True)])
def test_denied_before_storage(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(answers.answer_knowledge(None, actor=actor, policy=POLICY, unit_ids=IDS))


@pytest.mark.parametrize('ids,language', [([], 'ru'), (IDS * 2, 'ru'), ([IDS[0]] * 2, 'ru'),
    (['not a rule'], 'ru'), (IDS, 'xx'), (IDS, None), ('KG.DL.TEST', 'en')])
def test_invalid_input_before_storage(ids, language):
    with pytest.raises(EntryStorageInvalid):
        asyncio.run(answers.answer_knowledge(None, actor=ADMIN, policy=POLICY, unit_ids=ids, language=language))


def load_all_families(env, tmp_path, *, with_catalog=False, with_gaps=False):
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    folder = tmp_path / 'all-answer-kinds'
    shutil.copytree(FIX / 'synthetic_bundle', folder)
    units = yaml.safe_load((folder / 'units.yaml').read_text('utf-8'))
    tariff = next(unit for unit in units if unit['kind'] == 'tariff')
    tariff.update(label='none', confirmation_status='confirmed', blocked_value=None,
                  value=dict(amount=0, currency='KGS', per='application', component='bank'))
    for unit in units:
        if unit['kind'] == 'special_regime':
            unit['value'].update(reentry_after_days=0, visa_inside_kg=False, requires='SYNTHETIC CONDITION')
        if unit['kind'] == 'visa_required_regime':
            unit['value']['scope'] = 'business_tourist'
            if not with_gaps:
                unit['value']['countries'] = ['CHN']
        if unit['kind'] == 'processing_time':
            unit['value'].update(urgent_wd=2, urgent_multiplier=1.5)
        if unit['kind'] == 'rule_param':
            if with_gaps:
                unit['value'] = dict(value=11, unit='calendar_days')
            else:
                unit['value'].update(anchor='SYNTHETIC ANCHOR', inclusive=False)
        if unit['kind'] == 'template':
            if not with_gaps:
                unit['value'].update(text='Обратитесь к специалисту.', placeholders=[])
        if unit['confirmation_status'] == 'confirmed':
            unit.update(effective_from='2026-01-01', verified_at='2026-09-01T00:00:00Z',
                verified_by='synthetic-reviewer', review_due_at='2026-12-01T00:00:00Z', owner='synthetic-owner',
                source_ref='SYNTHETIC official source', source_text='SYNTHETIC source qualification.')
    (folder / 'units.yaml').write_text(yaml.safe_dump(units, allow_unicode=True), 'utf-8')
    catalog = None
    if with_catalog:
        from app.knowledge.bundle import preflight_bundle
        checked = preflight_bundle(folder, FIX / 'synthetic_source.txt')
        catalog = tmp_path / 'answer-conditions.json'
        catalog.write_text(json.dumps(dict(format='kg-entry-conditions/1', status='draft',
            source_hash=checked.normalized_bundle['meta']['source_hash'], bundle_hash=checked.bundle_hash,
            source_capture_sha256='1'*64, source_date='2026-10-02', date_basis='source_claim',
            publication_approved=False, rules=[dict(unit_id='KG.SP.TEST',
                source_locations=[dict(page=1, section='Synthetic')],
                all=[dict(type='document_type_is', value='un_lp')],
                source_outcome=dict(stay_days=8), unresolved=['synthetic_unapproved'])])), 'utf-8')
    async def load():
        sid = await create_kg_entry_set(env['engine'], actor=ADMIN)
        return await import_bundle(env['engine'], actor=ADMIN, set_id=sid, directory=folder,
                                   source=FIX/'synthetic_source.txt', catalog=catalog)
    imported = asyncio.run(load())
    assert imported.accepted, imported.report
    env['release'] = imported.version_id
    ids = [unit['unit_id'] for unit in units if unit['confirmation_status'] == 'confirmed']
    for identifier in ids:
        review(env, unit=identifier, version=imported.version_id, key='review-' + identifier)
    for action in ('review', 'approve', 'activate'):
        publish(env, action, ids=ids)
    return units, ids


def test_every_supported_family_is_read_from_actual_publication(env, tmp_path):
    units, ids = load_all_families(env, tmp_path)
    for identifier in ids:
        result = answer(env, [identifier])
        assert result['status'] == 'answered', (identifier, result)
        item = result['answers'][0]
        assert item['source_text'] in item['text'] and item['source']['version_id'] == env['release']
        source = next(unit for unit in units if unit['unit_id'] == identifier)
        # All leaf fields, including optional qualifiers, must survive formatting.
        leaves = sum(len(v) if type(v) is dict else 1 for v in source['value'].values())
        assert len(item['facts']) == leaves
    assert answer(env, ['KG.TPL.TEST'], language='en')['unavailable'][0]['reasons'] == ['approved_translation_unavailable']
    fee = answer(env, ['KG.FEE.SERVICE.TEST'])['answers'][0]['text']
    assert '0' in fee and 'KGS' in fee and 'банк' in fee and 'заявление' in fee
    exemption = answer(env, ['KG.REG.EXEMPT.GRC'])['answers'][0]['text']
    assert 'Освобождение от регистрации' in exemption and 'Страна (ISO): GRC' in exemption


def test_imported_draft_condition_catalog_cannot_be_quoted(env, tmp_path):
    load_all_families(env, tmp_path, with_catalog=True)
    result = answer(env, ['KG.SP.TEST', 'KG.DL.TEST'])
    assert result['status'] == 'partial'
    assert [item['unit_id'] for item in result['answers']] == ['KG.DL.TEST']
    assert result['unavailable'] == [dict(unit_id='KG.SP.TEST', reasons=['condition_catalog_requires_specialist'])]
    assert 'SYNTHETIC CONDITION' not in json.dumps(result)


def test_approved_incomplete_scope_anchor_and_template_fall_back(env, tmp_path):
    load_all_families(env, tmp_path, with_gaps=True)
    result = answer(env, ['KG.VR.GENERAL', 'KG.RULE.TEST', 'KG.TPL.TEST'])
    assert not result['answers'] and result['status'] == 'specialist_required'
    assert {reason for item in result['unavailable'] for reason in item['reasons']} == {
        'catchall_scope_requires_specialist', 'counting_basis_requires_specialist', 'template_requires_personal_facts'}


@pytest.mark.parametrize('change,reason', [
    ({'condition_rule': {'unresolved': ['draft']}}, 'condition_catalog_requires_specialist'),
    ({'kind': 'new-kind'}, 'unsupported_answer_kind'),
    ({'value': {'scope': None}}, 'answer_value_incomplete_or_unsupported'),
    ({'value': {'unrecognised': 'secret'}}, 'answer_value_incomplete_or_unsupported'),
    ({'kind': 'template', 'value': {'lang': 'ru', 'text': 'Stay {days}', 'placeholders': ['days']}}, 'template_requires_personal_facts'),
    ({'source_text': 'x' * 40000}, 'answer_size_limit'),
])
def test_unsupported_semantics_withheld(change, reason):
    unit = dict(unit_id='KG.DL.TEST', kind='deadline', condition_rule=None, value={'value': 3},
                title='Synthetic', source_text=None, **{key:'x' for key in ('version_id', 'version_number',
                'version_label', 'source_document', 'source_hash', 'source_ref', 'page', 'section', 'unit_hash',
                'bundle_hash', 'manifest_hash', 'effective_from', 'effective_to', 'checked_at')})
    unit.update(deepcopy(change))
    with pytest.raises(answers._Unrenderable, match=reason):
        answers._answer(unit, 'ru')
