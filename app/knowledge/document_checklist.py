"""Draft matrix scenarios only: no document acceptance, storage or submission."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

CATALOG_SHA256='81ebf0f41aec18ebe8ada37d3d709fd73114eea250718fc4b66abb63e22b1c6f'
CATALOG_PATH=Path(__file__).resolve().parents[2]/'knowledge/kg_entry/documents_v1_1/catalog.json'
KINDS={'required':'Обязательно в матрице','conditional':'В отдельных случаях',
       'recommended':'Желательно','not_listed':'В матрице отмечено «—»'}
STATES={'unknown':'Неизвестно','missing':'Нет документа','received':'Получен, ещё не проверен',
        'correction':'Нужна доработка','checked':'Проверен в условном сценарии'}
OUTCOMES={'unknown':'Нет сведений','missing':'Нужен документ','received':'Нужна проверка',
          'correction':'Нужна доработка','checked':'Отмечено проверенным в сценарии',
          'not_current':'Нужно заново проверить актуальную версию',
          'applicability_unknown':'Нужно уточнить применимость',
          'not_applicable':'Условие отмечено неприменимым в сценарии',
          'source_review':'Требование источника ещё требует подтверждения'}


class DocumentChecklistError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentCatalog:
    _raw:bytes

    def __post_init__(self):
        if type(self._raw) is not bytes or len(self._raw)>524288:
            raise DocumentChecklistError('document_catalog_invalid')
        object.__setattr__(self,'_raw',self._raw.replace(b'\r\n',b'\n'))
        if hashlib.sha256(self._raw).hexdigest()!=CATALOG_SHA256:
            raise DocumentChecklistError('document_catalog_invalid')

    @property
    def digest(self):return hashlib.sha256(self._raw).hexdigest()

    def document(self):return json.loads(self._raw)


def load_document_catalog(path=CATALOG_PATH):
    try:
        with Path(path).open('rb') as stream:return DocumentCatalog(stream.read(524289))
    except OSError:raise DocumentChecklistError('document_catalog_unavailable') from None


def checklist(catalog,product):
    data=catalog.document()
    if not isinstance(product,str) or product not in data['products']:
        raise DocumentChecklistError('invalid_document_product')
    items=[]
    for row in data['rows']:
        cell=row['cells'][product]
        if cell.startswith('—'):
            parts=[('—',cell[1:])]
        else:
            parts=re.findall(r'([●◐★])([^●◐★]*)',cell)
        if not parts:raise DocumentChecklistError('document_catalog_invalid')
        for i,(symbol,note) in enumerate(parts):
            kind={'●':'required','◐':'conditional','★':'recommended','—':'not_listed'}[symbol]
            items.append(dict(id=f'{row["id"]}_{i}',name=row['name'],number=row['number'],
                kind=kind,note=note.strip(' ;'),source_cell=cell,page=row['page'],
                source_review='[ПРОВЕРИТЬ' in cell))
    return items


def review_checklist(catalog,*,product,states,conditions,current_version,expected_digest):
    if expected_digest!=catalog.digest:raise DocumentChecklistError('stale_document_catalog')
    items=checklist(catalog,product)
    editable={item['id'] for item in items if item['kind']!='not_listed'}
    conditional={item['id'] for item in items if item['kind']=='conditional'}
    if (type(states) is not dict or type(conditions) is not dict or
        not states.keys()<=editable or not conditions.keys()<=conditional or
        any(type(v) is not str or v not in STATES for v in states.values()) or
        any(v is not None and type(v) is not bool for v in conditions.values()) or
        current_version is not None and type(current_version) is not bool):
        raise DocumentChecklistError('invalid_document_answers')
    rows=[];counts=dict(required_checked=0,required_pending=0,applicability_unknown=0,recommended_pending=0,source_review=0)
    for item in items:
        if item['kind']=='not_listed':continue
        state=states.get(item['id'],'unknown')
        applies=conditions.get(item['id']) if item['kind']=='conditional' else True
        outcome=state
        if applies is None:outcome='applicability_unknown';counts['applicability_unknown']+=1
        elif applies is False:outcome='not_applicable'
        elif item['source_review']:outcome='source_review';counts['source_review']+=1
        elif state=='checked' and current_version is not True:outcome='not_current'
        if applies is True:
            if item['kind']=='recommended':counts['recommended_pending']+=int(outcome!='checked')
            else:counts['required_checked' if outcome=='checked' else 'required_pending']+=1
        rows.append({**item,'state':state,'applicable':applies,'outcome':outcome})
    canonical=dict(product=product,states=states,conditions=conditions,current_version=current_version,catalog=catalog.digest)
    digest=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
    return dict(product=product,rows=rows,counts=counts,current_version=current_version,
        status='needs_attention' if counts['required_pending'] or counts['applicability_unknown'] or counts['source_review'] else 'draft_rows_checked',
        input_sha256=digest,catalog_sha256=catalog.digest,version=catalog.document()['version'],
        package_accepted=False,submission_allowed=False,publication_approved=False,
        supplementary_requirements_assessed=False,facts_hypothetical=True)
