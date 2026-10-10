"""Typed full-package state reducer; no file bytes, source publication or portal submission."""
from copy import deepcopy
from datetime import date
import re

from app.domain.entry_document_rules import REASONS, SOURCES
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.knowledge.complete_document_checklist import _evaluate

MAX_REVISIONS=500
MAX_BYTES=8*1024*1024
VISA_TYPES={'TS','B','TR','RL','FF','S','SW1','SW2','DN','J','M','I','R','T','A'}
PRODUCTS={'visa':VISA_TYPES,'unified_permit':{'EP'},'resident_card':{'RES'},'exit_visa':{'L'},'registration':{'REG'},'violation_protocol':set()}
FIELDS={'initialize':{'product','catalog_digest','legacy_revision'},'facts':{'values'},
    'receive':{'item','fingerprint','on','source'},'review':{'item','version','fingerprint','on','outcome','reason','alternative'},
    'withdraw_document':{'item','version','fingerprint','on','reason'},'passport_change':{'on','reason'},
    'consent':{'status','on','reference','proof'},'approve':{'expected_state_hash','expected_policy_hash','on','reference','proof'},
    'revoke':{'on','reason'},'upgrade_definition':{'catalog_digest'}}
PASSPORT_IDS={'matrix_d01_0','matrix_d02_0','g02_01','work04','t28_02',
    *(f't{n:02}_01' for n in (1,4,8,9,11,13,15,16,17,19,20,21,22,23,24,25,26))}


def invalid(code='invalid_document_package_operation'): raise EntryStorageInvalid(code)


def normalize(operation, *, cutoff):
    if type(operation) is not dict or operation.keys()!={'action','data','confirmed'} or operation['confirmed'] is not True:
        invalid()
    action=operation['action']; data=operation['data']
    if type(action) is not str or action not in FIELDS or type(data) is not dict or data.keys()!=FIELDS[action]: invalid()
    for key in ('catalog_digest','fingerprint','proof','expected_state_hash','expected_policy_hash'):
        if key in data and (type(data[key]) is not str or not re.fullmatch('[a-f0-9]{64}',data[key])): invalid()
    if 'item' in data and (type(data['item']) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{1,40}',data['item'])): invalid()
    if 'reference' in data and (type(data['reference']) is not str or not re.fullmatch(r'[A-Z][A-Z0-9._/-]{0,79}',data['reference'])): invalid()
    if 'on' in data:
        try:
            parsed=date.fromisoformat(data['on'])
            if parsed.isoformat()!=data['on'] or parsed>cutoff: raise ValueError
        except (TypeError,ValueError): invalid('invalid_document_package_date')
    if action=='initialize':
        if type(data['product']) is not str or data['product'] not in set().union(*PRODUCTS.values()) or type(data['legacy_revision']) is not int or not 0<=data['legacy_revision']<=150: invalid()
    if action=='facts' and (type(data['values']) is not dict or not 1<=len(data['values'])<=128): invalid()
    if action=='receive' and (type(data['source']) is not str or data['source'] not in {*SOURCES,'manager_check'}): invalid()
    if action in ('review','withdraw_document'):
        if type(data['version']) is not int or not 1<=data['version']<=MAX_REVISIONS: invalid()
        if action=='review' and data['outcome'] not in ('checked','correction'): invalid()
        if action=='review' and data['outcome']=='checked':
            if data['reason'] is not None: invalid()
        elif type(data['reason']) is not str or data['reason'] not in REASONS: invalid()
        if action=='review' and data['alternative'] is not None and (type(data['alternative']) is not str or not re.fullmatch('[a-z_]{1,40}',data['alternative'])): invalid()
    if action=='passport_change' and data['reason'] not in ('replacement','correction','expiry'): invalid()
    if action=='consent' and data['status'] not in ('granted','withdrawn'): invalid()
    if action=='revoke' and data['reason'] not in ('document_changed','facts_changed','source_changed','consent_withdrawn','review_error','policy_changed'): invalid()
    return deepcopy(operation)


def _validate_facts(definition,values):
    if not values.keys()<=definition['facts'].keys(): invalid('invalid_document_package_fact')
    for name,value in values.items():
        if value is not None and not any(type(value) is type(candidate) and value==candidate for candidate in definition['facts'][name]['values']):
            invalid('invalid_document_package_fact')


def _empty_item():
    return dict(version=0,fingerprint=None,status='missing',received_on=None,source=None,reviewed_on=None,reviewed_by=None,
        reviewed_version=None,reviewed_passport_revision=None,reviewed_facts_revision=None,reason=None,legacy_origin=None,alternative=None)


def _passports(state, rules_version=2):
    items={key:(item['version'],item['fingerprint']) for key,item in state['items'].items()
           if key in PASSPORT_IDS and item['fingerprint'] and item['status']!='withdrawn'}
    # The original reducer is retained only for exact historical replay.
    return {value[1] for value in items.values()} if rules_version==1 else items


def apply_operation(state,operation,*,actor,definition,legacy=None,policy=None,rules_version=2):
    action=operation['action'];data=operation['data']
    if state is None:
        if action!='initialize': invalid('document_package_missing')
        if definition['product']!=data['product'] or definition['catalog_sha256']!=data['catalog_digest']: invalid('package_definition_changed')
        result=dict(format='entry-document-package/1',product=definition['product'],catalog_digest=definition['catalog_sha256'],
            definition_hash=_hash(definition),passport_revision=1,facts_revision=1,
            facts={key:None for key in definition['facts']},items={r['id']:_empty_item() for r in definition['rows'] if r['kind']!='policy'},
            consent=None,approval=None,last_invalidation=None)
        if legacy:
            if legacy['definition']['product']!=result['product']: invalid('package_legacy_product_changed')
            result['passport_revision']=legacy['passport_revision']
            for key,item in legacy['items'].items():
                target='matrix_'+key
                if target in result['items']:
                    copied={k:deepcopy(item[k]) for k in ('version','fingerprint','received_on','source','reason')}
                    copied.update(status='received' if item['status']=='checked' else item['status'],legacy_origin=key)
                    result['items'][target].update(copied)
        return result
    if action=='initialize': invalid('document_package_already_exists')
    if state['product']!=definition['product']: invalid('package_definition_changed')
    result=deepcopy(state)
    if action=='upgrade_definition':
        if data['catalog_digest']==state['catalog_digest'] or definition['catalog_sha256']!=data['catalog_digest']: invalid('package_definition_unchanged')
        # The service supplies only registered definitions. Existing evidence remains in history.
        result.update(catalog_digest=definition['catalog_sha256'],definition_hash=_hash(definition),
            facts={key:None for key in definition['facts']},facts_revision=state['facts_revision']+1,
            items={r['id']:_empty_item() for r in definition['rows'] if r['kind']!='policy'},approval=None,last_invalidation='definition_changed')
        return result
    if state['definition_hash']!=_hash(definition): invalid('package_definition_changed')
    if action=='approve':
        if data['expected_state_hash']!=_hash(state): invalid('package_state_changed')
        if policy is None: invalid('package_policy_required')
        if data['expected_policy_hash']!=policy.digest: invalid('package_policy_changed')
        assert_acceptable(state,definition,policy)
        result['approval']=dict(reference=data['reference'],proof=data['proof'],on=data['on'],actor=actor,policy=policy.document(),
            policy_hash=policy.digest,basis_hash=_hash({k:v for k,v in state.items() if k not in ('approval','last_invalidation')}))
        result['last_invalidation']=None
        return result
    if action=='revoke' and state['approval'] is None: invalid('package_approval_missing')
    result['approval']=None;result['last_invalidation']=action
    if action=='revoke': result['last_invalidation']=data['reason'];return result
    if action=='facts':
        _validate_facts(definition,data['values']); merged={**state['facts'],**data['values']}
        if merged==state['facts']: invalid('package_facts_unchanged')
        result['facts']=merged;result['facts_revision']+=1;return result
    if action=='consent':
        if state['consent'] and data['on']<state['consent']['on']: invalid('invalid_document_package_date')
        result['consent']={**data,'recorded_by':actor};return result
    if action=='passport_change': result['passport_revision']+=1;return result
    identifier=data['item']
    if identifier not in result['items']: invalid('package_item_unavailable')
    item=result['items'][identifier]; previous_passports=_passports(result,rules_version)
    if action=='receive':
        if item['fingerprint']==data['fingerprint']: invalid('document_content_unchanged')
        if item['received_on'] and data['on']<item['received_on']: invalid('invalid_document_package_date')
        item.update(_empty_item()|dict(version=item['version']+1,fingerprint=data['fingerprint'],received_on=data['on'],
            source=data['source'],status='received'))
    else:
        if not item['version'] or item['version']!=data['version'] or item['fingerprint']!=data['fingerprint']:
            invalid('document_version_changed')
        if item['status']=='withdrawn': invalid('document_withdrawn')
        if data['on']<item['received_on'] or item['reviewed_on'] and data['on']<item['reviewed_on']: invalid('invalid_document_package_date')
        if action=='withdraw_document': item.update(status='withdrawn',reason=data['reason'])
        else:
            choices=next(r['alternatives'] for r in definition['rows'] if r['id']==identifier)
            if data['alternative'] is not None and data['alternative'] not in choices: invalid('package_alternative_invalid')
            if data['outcome']=='checked' and choices and data['alternative'] is None: invalid('package_alternative_required')
            item.update(status=data['outcome'],reason=data['reason'],reviewed_on=data['on'],reviewed_by=actor,
                reviewed_version=item['version'],reviewed_passport_revision=state['passport_revision'],reviewed_facts_revision=state['facts_revision'],alternative=data['alternative'])
    if _passports(result,rules_version)!=previous_passports: result['passport_revision']+=1
    return result


def summarize(state,definition):
    rows=[]; counts=dict(required_pending=0,applicability_unknown=0,recommended_pending=0,practice_pending=0,source_review=0)
    for source in definition['rows']:
        if source['kind']=='policy': continue
        item=state['items'][source['id']]; status=item['status']
        if status=='checked' and (item['reviewed_version']!=item['version'] or item['reviewed_passport_revision']!=state['passport_revision'] or
                                 item['reviewed_facts_revision']!=state['facts_revision']): status='recheck'
        applies,missing=_evaluate(source['when'],state['facts'],state['product'])
        if applies is None: counts['applicability_unknown']+=1
        if applies is True:
            if source['kind']=='recommended': counts['recommended_pending']+=int(status!='checked')
            elif source['kind']=='practice': counts['practice_pending']+=int(status!='checked')
            else: counts['required_pending']+=int(status!='checked')
            counts['source_review']+=int('verify' in source['marks'] or 'decision' in source['marks'])
        rows.append({**source,**item,'effective_status':status,'applicable':applies,'missing_facts':missing})
    return dict(rows=rows,policies=[r for r in definition['rows'] if r['kind']=='policy'],counts=counts,
                consent=state['consent'],approval=state['approval'],state_hash=_hash(state),
                package_accepted=False,submission_allowed=False,metadata_only=True)


def assert_acceptable(state,definition,policy):
    report=summarize(state,definition)
    # An explicitly selected tourist-organisation letter entails its contents;
    # a contradictory optional-applicability answer cannot hide those checks.
    tourist=state['items'].get('t01_03')
    if tourist and tourist['alternative']=='tour_operator' and any(
        r['id'].startswith('letter') and r['applicable'] is not True for r in report['rows']):
        invalid('document_package_invitation_conflict')
    if report['counts']['required_pending'] or report['counts']['applicability_unknown']: invalid('document_package_incomplete')
    if policy.practice_checks_required and report['counts']['practice_pending']: invalid('document_package_practice_pending')
    if any(r['applicable'] and ('verify' in r['marks'] or 'decision' in r['marks']) and r['id'] not in policy.reviewed_source_items for r in report['rows']):
        invalid('document_package_source_unverified')
    if policy.consent_required and (state['consent'] is None or state['consent']['status']!='granted'):
        invalid('document_package_consent_required')
