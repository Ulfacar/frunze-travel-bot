"""Small process adapter: exact source edges, explicit focus and typed operations."""
from copy import deepcopy
from datetime import date
import re

from app.domain.entry_process_policy import ROOTS,ROOT_ROLES,ROLES,REFERENCE,HASH,AUTHORITATIVE,ATTESTATION_SOURCES,edge_id
from app.domain.entry_storage import EntryStorageInvalid,_id
from app.knowledge.process_preview import load_process_catalog

MAX_EVENTS=250
MAX_BYTES=8*1024*1024
MAX_PINS=160
FIELDS={
    'initialize':{'catalog_digest','on','employer_reference'},
    'link':{'role','application_id','on'},
    'attest':{'role','fact','value','on','valid_through','source','reference','proof','profile_id'},
    'withdraw':{'role','fact','on','reference','proof'},
    'transition':{'edge_id','on','evidence_digest'},
    'stop':{'on','reference','proof'},
}
# Readiness retains safety premises across short later edges. Phase observations
# (e.g. the need for corrections) are evaluated only at the exact edge they guard.
LIVE_FACTS={'consent_confirmed','documents_accepted','documents_current',
    'receiving_party_docs_accepted','issued_document_checked','exit_visa_issued','delivered_to_client','receipt_confirmed',
    'service_payment_confirmed','profile_complete','eligibility','product_defined',
    'employer_qualified','employer_authorization_confirmed','quota_approved','regularization_route'}
CORRECTIVE_TARGETS={'V13','V18','W13','X01','X08','WX2','RX1','UX2'}


def invalid(code='invalid_process_operation'):raise EntryStorageInvalid(code)


def catalog():return load_process_catalog().document()


def value_for(fact,value):
    spec={'type':'boolean'} if fact=='profile_review_complete' else catalog()['facts'].get(fact)
    if spec is None:invalid()
    if value is None:return
    if spec['type']=='boolean':
        if type(value) is not bool:invalid()
    elif type(value) is not str or value not in spec['values']:invalid()


def normalize(operation,*,cutoff):
    if type(operation) is not dict or operation.keys()!={'action','data','confirmed'} or operation['confirmed'] is not True:invalid()
    action=operation['action'];data=operation['data']
    if type(action) is not str or action not in FIELDS or type(data) is not dict or data.keys()!=FIELDS[action]:invalid()
    for key in ('on','valid_through'):
        if key not in data:continue
        try:
            day=date.fromisoformat(data[key])
            if day.isoformat()!=data[key] or key=='on' and day>cutoff:raise ValueError
        except (ValueError,TypeError):invalid('invalid_process_date')
    if 'valid_through' in data and data['valid_through']<data['on']:invalid('invalid_process_date')
    for key in ('proof','catalog_digest','edge_id','evidence_digest'):
        if key in data and (type(data[key]) is not str or not re.fullmatch(HASH,data[key])):invalid()
    for key in ('reference','employer_reference'):
        if key in data and not (key=='employer_reference' and data[key] is None):
            if type(data[key]) is not str or not re.fullmatch(REFERENCE,data[key]):invalid()
    if 'role' in data and (type(data['role']) is not str or data['role'] not in ROLES):invalid()
    if 'fact' in data:
        if type(data['fact']) is not str or data['fact'] in AUTHORITATIVE:invalid('process_authoritative_fact')
        value_for(data['fact'],data.get('value'))
    if action=='attest':
        value_for(data['fact'],data['value'])
        if type(data['source']) is not str or data['source'] not in ATTESTATION_SOURCES:invalid()
        if data['profile_id'] is not None:_id(data['profile_id'])
        if (data['fact'] in ('profile_review_complete','eligibility','visa_required'))!=(data['profile_id'] is not None):
            invalid('process_profile_pin_required')
    if action=='link':_id(data['application_id'])
    return deepcopy(operation)


def initial_state(root,data):
    if root.procedure not in ROOTS:invalid('process_root_procedure_unsupported')
    process,start=ROOTS[root.procedure]
    if (process=='work')!=(data['employer_reference'] is not None):invalid('process_employer_scope_required')
    return dict(format='entry-process/1',process=process,stage=start,root_id=root.id,applicant_id=root.applicant_id,
        active_role=ROOT_ROLES[root.procedure],active_application_id=root.id,branch=None,
        catalog_digest=data['catalog_digest'],employer_reference=data['employer_reference'],
        links={ROOT_ROLES[root.procedure]:root.id},used_roles=[ROOT_ROLES[root.procedure]],
        attestations={},retained={},stopped=False,on=data['on'])


def edge_for(state,digest):
    edge=next((edge for edge in catalog()['edges'] if edge_id(edge)==digest),None)
    if not edge or edge['from']!=state['stage']:invalid('process_edge_unavailable')
    stages={s['code']:s for s in catalog()['stages']}
    if stages[edge['to']]['kind']=='flag' or stages[edge['to']]['process']!=state['process']:invalid('process_edge_unavailable')
    return edge


def focus(state,edge):
    target=edge['to'];role=state['active_role'];branch=state['branch']
    if state['process']=='work' and target.startswith('W') and target[1:].isdigit():
        number=int(target[1:]);role='registration' if number>=20 else 'resident' if number>=16 else 'permit'
    if state['process']=='regularization' and edge['from']=='U05' and target=='U06':
        branch=edge['requires']['regularization_route'];role='exit_visa' if branch=='exit_visa' else 'registration'
    if state['process']=='regularization' and edge['from']=='U06' and branch!='exit_visa':
        invalid('process_branch_mismatch')
    if role not in state['links']:invalid('process_dependency_missing')
    return role,branch


def fact_role(state,edge,fact):
    role,_=focus(state,edge)
    if fact in {'permit_issued','employer_qualified','employer_authorization_confirmed','account_activated','quota_applied','quota_approved'}:return 'permit'
    if fact in {'resident_package_received','resident_issued_and_collected'}:return 'resident'
    if fact in {'registration_confirmed','registration_certificate_received'}:return 'registration'
    if fact in {'protocol_received','police_letter_received','fine_payment_confirmed','overstay_assessed','regularization_route'}:return 'protocol'
    if fact=='decision':return state['active_role']
    if fact in ('actual_entry_confirmed','actual_exit_or_end_confirmed','departure_confirmed') and state['process']=='work':return 'visa'
    return role


def apply(state,operation,*,root,revision,resolved=None):
    action=operation['action'];data=operation['data']
    if state is None:
        if action!='initialize':invalid('process_not_initialized')
        return initial_state(root,data)
    if action=='initialize':invalid('process_already_initialized')
    if state['stopped']:invalid('process_stopped')
    if action in ('transition','stop') and data['on']<state['on']:invalid('invalid_process_date')
    result=deepcopy(state);result['on']=max(state['on'],data['on'])
    if action=='stop':result['stopped']=True;return result
    if action=='link':
        role=data['role']
        if role in result['used_roles'] or data['application_id'] in result['links'].values():invalid('process_dependency_in_use')
        result['links'][role]=data['application_id']
    elif action in ('attest','withdraw'):
        if data['role'] not in result['links']:invalid('process_dependency_missing')
        key=data['role']+'.'+data['fact']
        if key in result['attestations'] and data['on']<result['attestations'][key]['on']:invalid('invalid_process_date')
        if action=='withdraw':
            if key not in result['attestations']:invalid('process_evidence_missing')
            result['attestations'].pop(key)
        else:
            result['attestations'][key]=dict(data,event_revision=revision)
            result['used_roles']=sorted(set(result['used_roles'])|{data['role']})
    elif action=='transition':
        edge=edge_for(state,data['edge_id']);role,branch=focus(state,edge)
        if resolved is None:invalid('process_evidence_missing')
        for fact,expected in edge['requires'].items():
            key=fact_role(state,edge,fact)+'.'+fact
            actual=resolved[key]['value']
            if type(actual) is not type(expected) or actual!=expected:invalid('process_prerequisites_missing')
            # Operator evidence can be corrected or explicitly withdrawn. Once
            # used, it remains a prerequisite until an explicit source edge
            # replaces its expected value; silently forgetting it would make a
            # withdrawn approval/receipt/payment attestation ineffective.
            if fact in LIVE_FACTS or fact not in AUTHORITATIVE:result['retained'][key]=expected
        if edge['to'] not in CORRECTIVE_TARGETS:
            for key,expected in result['retained'].items():
                actual=resolved.get(key,{}).get('value')
                if type(actual) is not type(expected) or actual!=expected:invalid('process_prerequisites_changed')
        result.update(stage=edge['to'],active_role=role,active_application_id=result['links'][role],branch=branch)
        result['used_roles']=sorted(set(result['used_roles'])|{key.split('.')[0] for key in resolved}|{role})
    return result
