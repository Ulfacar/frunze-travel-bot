"""Full source checklist assessment. Approval and file acceptance are separate gates."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.knowledge.document_checklist import DocumentChecklistError, STATES

CATALOG_PATH = Path(__file__).resolve().parents[2]/'knowledge/kg_entry/complete_documents_v1_1/catalog.json'
CATALOG_SHA256 = '5014a02c362964d74f0c55915dd2045c040ea513f9d9488585f745c0a67401d0'


@dataclass(frozen=True)
class CompleteDocumentCatalog:
    _raw: bytes

    def __post_init__(self):
        if type(self._raw) is not bytes or len(self._raw)>524288:
            raise DocumentChecklistError('complete_document_catalog_invalid')
        normalized = self._raw.replace(b'\r\n',b'\n')
        if hashlib.sha256(normalized).hexdigest()!=CATALOG_SHA256:
            raise DocumentChecklistError('complete_document_catalog_invalid')
        object.__setattr__(self,'_raw',normalized)

    @property
    def digest(self): return CATALOG_SHA256

    def document(self): return json.loads(self._raw)


def load_complete_document_catalog(path=CATALOG_PATH):
    try:
        with Path(path).open('rb') as stream: return CompleteDocumentCatalog(stream.read(524289))
    except OSError: raise DocumentChecklistError('complete_document_catalog_unavailable') from None


def _evaluate(expression, facts, product):
    if type(expression) is bool: return expression, []
    if 'product' in expression: return product in expression['product'], []
    if 'eq' in expression:
        name, expected = expression['eq']; actual=facts.get(name)
        return (None,[name]) if actual is None else (actual==expected,[])
    operator = 'all' if 'all' in expression else 'any'
    children = [_evaluate(child,facts,product) for child in expression[operator]]
    if operator=='all' and any(value is False for value,_ in children): return False,[]
    if operator=='any' and any(value is True for value,_ in children): return True,[]
    unknown = sorted({name for value,names in children if value is None for name in names})
    if unknown: return None,unknown
    return operator=='all',[]


def _fields(expression):
    if type(expression) is bool or 'product' in expression: return set()
    if 'eq' in expression: return {expression['eq'][0]}
    return set().union(*(_fields(child) for child in expression.get('all',expression.get('any'))))


def complete_definition(catalog, product):
    document=catalog.document()
    if type(product) is not str or product not in document['products']:
        raise DocumentChecklistError('invalid_complete_document_product')
    rows=[]; facts={}
    for item in document['matrix'].get(product,[]):
        if item['kind']=='not_listed': continue
        identifier='matrix_'+item['id']; condition='matrix_'+item['id']+'_applies'
        when={'eq':[condition,True]} if item['kind']=='conditional' else True
        if item['kind']=='conditional': facts[condition]=dict(label=item['name']+': '+item['note'],values=[False,True])
        rows.append(dict(id=identifier,name=item['name'],text=item['source_cell'],section='5.2',page=item['page'],
            kind=item['kind'],marks=['verify'] if item['source_review'] else [],when=when,source=item))
    for item in document['clauses']:
        if product not in item['products']: continue
        rows.append(dict(id=item['id'],name=item['text'],text=item['source_fragment'],section=item['section'],page=item['page'],
            kind=item['kind'],marks=item['marks'],when=item['when'],source=item))
        for name in _fields(item['when']): facts[name]=document['facts'][name]
    return dict(product=product,title=document['products'][product],catalog_sha256=catalog.digest,version=document['version'],
                source_sha256=document['source_sha256'],rows=rows,facts=facts,
                matrix_present=product in document['matrix'],source_approved=False)


def assess_complete_checklist(catalog, *, product, states, facts, current_version, expected_digest):
    if expected_digest!=catalog.digest: raise DocumentChecklistError('stale_complete_document_catalog')
    definition=complete_definition(catalog,product)
    editable={row['id'] for row in definition['rows'] if row['kind']!='policy'}
    if (type(states) is not dict or type(facts) is not dict or not states.keys()<=editable or
        not facts.keys()<=definition['facts'].keys() or any(type(value) is not str or value not in STATES for value in states.values()) or
        current_version is not None and type(current_version) is not bool):
        raise DocumentChecklistError('invalid_complete_document_answers')
    for name,value in facts.items():
        expected=definition['facts'][name]['values']
        if value is not None and not any(type(value) is type(candidate) and value==candidate for candidate in expected):
            raise DocumentChecklistError('invalid_complete_document_fact')
    counts=dict(required_checked=0,required_pending=0,applicability_unknown=0,recommended_pending=0,
                practice_pending=0,source_review=0,policy_pending=0)
    rows=[]; missing=set()
    for row in definition['rows']:
        applies,unknown=_evaluate(row['when'],facts,product); missing.update(unknown)
        state=states.get(row['id'],'unknown'); outcome=state
        if row['kind']=='policy':
            outcome='policy_required'; counts['policy_pending']+=1
        elif applies is None:
            outcome='applicability_unknown'; counts['applicability_unknown']+=1
        elif applies is False: outcome='not_applicable'
        elif 'verify' in row['marks'] or 'decision' in row['marks']:
            outcome='source_review'; counts['source_review']+=1
        elif state=='checked' and current_version is not True: outcome='not_current'
        if row['kind']!='policy' and applies is True:
            if row['kind']=='recommended': counts['recommended_pending']+=int(outcome!='checked')
            elif row['kind']=='practice': counts['practice_pending']+=int(outcome!='checked')
            else: counts['required_checked' if outcome=='checked' else 'required_pending']+=1
        rows.append({**row,'applicable':applies,'missing_facts':unknown,'state':state,'outcome':outcome})
    payload=dict(product=product,states=states,facts=facts,current_version=current_version,catalog_sha256=catalog.digest)
    return dict(definition=definition,rows=rows,counts=counts,missing_facts=sorted(missing),
        input_sha256=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        assessments_complete=not any(counts[k] for k in ('required_pending','applicability_unknown','source_review')),
        supplementary_requirements_assessed=True,source_approved=False,package_accepted=False,submission_allowed=False,
        policy_approval_required=True,metadata_only=True)
