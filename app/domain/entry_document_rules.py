"""Pure document metadata reducer. It cannot approve a package or publish rules."""
from copy import deepcopy
from datetime import date
import re

from app.domain.entry_storage import EntryStorageInvalid

PRODUCTS={'visa':{'TS','B','RL','FF','S'},'unified_permit':{'EP'},
          'resident_card':{'RES'},'registration':{'REG'},'exit_visa':{'L'},'violation_protocol':set()}
SOURCES={'client_copy':'Копия от клиента','original_seen':'Оригинал просмотрен','portal_copy':'Копия с портала'}
REASONS={'unreadable':'Нечитаемый файл','incomplete':'Неполный документ','expired':'Истёк срок',
         'mismatch':'Данные не совпадают','translation':'Нужен перевод/заверение','other':'Другая причина'}
FIELDS={'initialize':{'product','catalog_digest'},'receive':{'item','fingerprint','on','source'},
        'review':{'item','version','fingerprint','on','outcome','reason'},
        'applicability':{'item','applicable'},'withdraw':{'item','version','fingerprint','on','reason'},
        'passport_change':{'on','reason'}}
MAX_REVISIONS=150
MAX_HISTORY_BYTES=4*1024*1024


def _invalid(code='invalid_document_operation'):raise EntryStorageInvalid(code)


def _fingerprint(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{64}',value):_invalid('invalid_document_fingerprint')


def normalize(operation,*,cutoff):
    if type(operation) is not dict or set(operation)!={'action','data','confirmed'}: _invalid()
    action=operation['action'];data=operation['data']
    if type(action) is not str or action not in FIELDS or type(data) is not dict or set(data)!=FIELDS[action]:_invalid()
    if operation['confirmed'] is not True:_invalid('document_confirmation_required')
    if 'item' in data and (type(data['item']) is not str or not re.fullmatch(r'd\d{2}_[01]',data['item'])):_invalid()
    if 'fingerprint' in data:_fingerprint(data['fingerprint'])
    if 'version' in data and (type(data['version']) is not int or not 1<=data['version']<=MAX_REVISIONS):_invalid()
    if 'on' in data:
        try:
            value=date.fromisoformat(data['on'])
            if data['on']!=value.isoformat() or value>cutoff:raise ValueError
        except (ValueError,TypeError):_invalid('invalid_document_date')
    if action=='initialize':
        if type(data['product']) is not str or data['product'] not in set().union(*PRODUCTS.values()):_invalid()
        _fingerprint(data['catalog_digest'])
    if action=='receive' and (type(data['source']) is not str or data['source'] not in SOURCES):_invalid()
    if action=='review':
        if data['outcome'] not in ('checked','correction'):_invalid()
        if not (type(data['reason']) is str and data['reason'] in REASONS) and not (data['outcome']=='checked' and data['reason'] is None):_invalid()
        if data['outcome']=='checked' and data['reason'] is not None:_invalid()
    if action=='withdraw' and (type(data['reason']) is not str or data['reason'] not in REASONS):_invalid()
    if action=='passport_change' and data['reason'] not in ('replacement','correction','expiry'):_invalid()
    if action=='applicability' and data['applicable'] is not None and type(data['applicable']) is not bool:_invalid()
    return deepcopy(operation)


def _definition(value,command):
    if type(value) is not dict or set(value)!={'product','catalog_digest','catalog_version','items'}:_invalid()
    if value['product']!=command['product'] or value['catalog_digest']!=command['catalog_digest']:_invalid()
    if type(value['catalog_version']) is not str or not 1<=len(value['catalog_version'])<=80:_invalid()
    items=value['items']
    if type(items) is not list or not 1<=len(items)<=80:_invalid()
    ids=set()
    for item in items:
        if type(item) is not dict or set(item)!={'id','name','kind','note','source_cell','page','number','source_review'}:_invalid()
        if type(item['id']) is not str or not re.fullmatch(r'd\d{2}_[01]',item['id']) or item['id'] in ids:_invalid()
        ids.add(item['id'])
        if item['kind'] not in ('required','conditional','recommended','not_listed'):_invalid()
        if type(item['source_review']) is not bool or type(item['page']) is not int or item['page'] not in (36,37):_invalid()
        for key in ('name','note','source_cell','number'):
            if type(item[key]) is not str or len(item[key])>2048:_invalid()
    return deepcopy(value)


def apply_operation(snapshot,operation,*,actor,definition=None):
    action=operation['action'];data=operation['data']
    if snapshot is None:
        if action!='initialize':_invalid('document_inventory_missing')
        source=_definition(definition,data)
        return dict(format='entry-document-inventory/1',definition=source,passport_revision=1,
            items={row['id']:dict(applicable=None if row['kind']=='conditional' else True,version=0,
                fingerprint=None,status='missing',received_on=None,source=None,reviewed_on=None,
                reviewed_by=None,reviewed_version=None,reviewed_passport_revision=None,reason=None)
                for row in source['items'] if row['kind']!='not_listed'})
    if action=='initialize':_invalid('document_inventory_already_exists')
    result=deepcopy(snapshot)
    if action=='passport_change':
        result['passport_revision']+=1
        return result
    key=data['item']
    if key not in result['items']:_invalid('document_item_unavailable')
    item=result['items'][key]
    source=next(row for row in result['definition']['items'] if row['id']==key)
    if action=='applicability':
        if source['kind']!='conditional':_invalid('document_applicability_fixed')
        item['applicable']=data['applicable']
        return result
    if action=='receive':
        if item['fingerprint']==data['fingerprint']:_invalid('document_content_unchanged')
        if item['received_on'] and data['on']<item['received_on']:_invalid('invalid_document_date')
        item.update(version=item['version']+1,fingerprint=data['fingerprint'],status='received',
            received_on=data['on'],source=data['source'],reviewed_on=None,reviewed_by=None,
            reviewed_version=None,reviewed_passport_revision=None,reason=None)
        if key.startswith(('d01_','d02_')):result['passport_revision']+=1
        return result
    if (not item['version'] or item['version']!=data['version'] or item['fingerprint']!=data['fingerprint']):
        _invalid('document_version_changed')
    if data['on']<item['received_on'] or item['reviewed_on'] and data['on']<item['reviewed_on']:_invalid('invalid_document_date')
    if item['status']=='withdrawn':_invalid('document_withdrawn')
    if action=='withdraw':item.update(status='withdrawn',reason=data['reason']);return result
    if source['source_review'] and data['outcome']=='checked':_invalid('document_source_unverified')
    item.update(status=data['outcome'],reviewed_on=data['on'],reviewed_by=actor,reviewed_version=item['version'],
        reviewed_passport_revision=result['passport_revision'],reason=data['reason'])
    return result


def summarize(snapshot):
    counts=dict(required_checked=0,required_pending=0,applicability_unknown=0,recommended_pending=0)
    rows=[]
    for definition in snapshot['definition']['items']:
        if definition['kind']=='not_listed':continue
        current=snapshot['items'][definition['id']]
        status=current['status']
        if status=='checked' and (current['reviewed_version']!=current['version'] or
                                 current['reviewed_passport_revision']!=snapshot['passport_revision']):status='recheck'
        if current['applicable'] is None:counts['applicability_unknown']+=1
        elif current['applicable']:
            if definition['kind']=='recommended':counts['recommended_pending']+=int(status!='checked')
            else:counts['required_checked' if status=='checked' else 'required_pending']+=1
        rows.append({**definition,**current,'effective_status':status})
    return dict(items=rows,counts=counts,passport_revision=snapshot['passport_revision'],
                package_accepted=False,submission_allowed=False,supplements_assessed=False)
