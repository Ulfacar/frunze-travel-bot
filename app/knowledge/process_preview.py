"""Deterministic, non-executable review of the versioned PDF process draft."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

CATALOG_SHA256 = 'cc17f508dee484534b9667a0235402630db8848618450109f9bcd746b2d78a6c'
CATALOG_PATH = Path(__file__).resolve().parents[2] / 'knowledge/kg_entry/processes_v1_1/catalog.json'
EFFECTS = {'same_process': 'Следующий этап того же процесса',
           'same_attempt_resubmission': 'Доработка и повторная отправка в той же попытке',
           'separate_resident_application': 'Отдельная заявка на резидент-карту',
           'separate_registration_application': 'Отдельная заявка на регистрацию'}
RESULTS = {'draft_conditions_met': 'Условия чернового перехода выполнены в сценарии',
           'missing_facts': 'Для проверки не хватает сведений',
           'conditions_not_met': 'Условия чернового перехода не выполнены',
           'not_in_draft': 'Такой переход в черновике не описан'}


class ProcessPreviewError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _validate(data):
    # The byte pin additionally rejects missing/extra fields and any unreviewed
    # modification, including flipping publication_approved or dropping guards.
    if data['format'] != 'kg-entry-process-draft/1' or data['publication_approved'] is not False:
        raise ProcessPreviewError('invalid_process_catalog')
    stages = {row['code']: row for row in data['stages']}
    expected = ({f'V{i:02}' for i in range(1,26)} | {f'X{i:02}' for i in range(1,16)} |
                {f'W{i:02}' for i in range(1,23)} | {f'WX{i}' for i in range(1,5)} |
                {f'R{i:02}' for i in range(1,9)} | {'RX1','RX2'} |
                {f'U{i:02}' for i in range(1,10)} | {'UX1','UX2'})
    if set(stages) != expected or len(data['stages']) != len(stages):
        raise ProcessPreviewError('invalid_process_catalog')
    seen = set()
    for edge in data['edges']:
        a, b = stages[edge['from']], stages[edge['to']]
        if (a['process'] != b['process'] or a['kind']=='flag' or b['kind']=='flag' or
            edge['proposed_effect'] not in EFFECTS or not edge['requires']):
            raise ProcessPreviewError('invalid_process_catalog')
        key = _canonical(edge)
        if key in seen: raise ProcessPreviewError('invalid_process_catalog')
        seen.add(key)
        for fact, expected_value in edge['requires'].items():
            definition = data['facts'][fact]
            if (definition['type']=='boolean' and type(expected_value) is not bool or
                definition['type']=='enum' and expected_value not in definition['values']):
                raise ProcessPreviewError('invalid_process_catalog')


@dataclass(frozen=True)
class ProcessCatalog:
    _raw: bytes

    def __post_init__(self):
        if type(self._raw) is not bytes or len(self._raw)>524288:
            raise ProcessPreviewError('process_catalog_integrity_failed')
        # Git may check text out as CRLF on Windows. Pin LF on both platforms.
        object.__setattr__(self,'_raw',self._raw.replace(b'\r\n',b'\n'))
        if hashlib.sha256(self._raw).hexdigest()!=CATALOG_SHA256:
            raise ProcessPreviewError('process_catalog_integrity_failed')
        try: _validate(json.loads(self._raw))
        except (KeyError, TypeError, ValueError): raise ProcessPreviewError('invalid_process_catalog') from None

    @property
    def digest(self):
        return hashlib.sha256(self._raw).hexdigest()

    def document(self):
        # Always detached: a caller cannot mutate the shared catalog or guards.
        return json.loads(self._raw)


def load_process_catalog(path=CATALOG_PATH):
    try:
        with Path(path).open('rb') as source: raw=source.read(524289)
        return ProcessCatalog(raw)
    except OSError: raise ProcessPreviewError('process_catalog_unavailable') from None


def evaluate_transition(catalog, *, process, current, target, facts, expected_digest):
    if not isinstance(catalog, ProcessCatalog): raise ProcessPreviewError('invalid_process_catalog')
    if expected_digest != catalog.digest: raise ProcessPreviewError('stale_process_catalog')
    data = catalog.document()
    if not isinstance(process,str) or process not in data['processes']:
        raise ProcessPreviewError('invalid_process')
    stages = {row['code']:row for row in data['stages'] if row['process']==process}
    if (not isinstance(current,str) or not isinstance(target,str) or current not in stages or target not in stages):
        raise ProcessPreviewError('invalid_process_stage')
    if type(facts) is not dict or len(facts)>len(data['facts']): raise ProcessPreviewError('invalid_process_facts')
    for key,value in facts.items():
        if not isinstance(key,str) or key not in data['facts']: raise ProcessPreviewError('invalid_process_facts')
        spec=data['facts'][key]
        if value is None: continue
        if spec['type']=='boolean' and type(value) is not bool:
            raise ProcessPreviewError('invalid_process_facts')
        if spec['type']=='enum' and (not isinstance(value,str) or value not in spec['values']):
            raise ProcessPreviewError('invalid_process_facts')
    edges = [row for row in data['edges'] if row['from']==current and row['to']==target]
    alternatives = []
    for edge in edges:
        checks=[]
        for key,expected in edge['requires'].items():
            actual=facts.get(key)
            state='unknown' if actual is None else 'met' if type(actual) is type(expected) and actual==expected else 'not_met'
            checks.append({'fact':key,'label':data['facts'][key]['label'],'expected':expected,'actual':actual,'state':state})
        status=('conditions_not_met' if any(row['state']=='not_met' for row in checks) else
                'missing_facts' if any(row['state']=='unknown' for row in checks) else 'draft_conditions_met')
        alternatives.append({'status':status,'checks':checks,'basis':edge['basis'],'proposed_effect':edge['proposed_effect']})
    statuses = {row['status'] for row in alternatives}
    status=('not_in_draft' if not alternatives else 'draft_conditions_met' if 'draft_conditions_met' in statuses else
            'missing_facts' if 'missing_facts' in statuses else 'conditions_not_met')
    request={'process':process,'current':current,'target':target,'facts':facts,'catalog_sha256':catalog.digest}
    return {**{k:request[k] for k in ('process','current','target','catalog_sha256')},
        'version':data['version'],'status':status,'alternatives':alternatives,
        'execution_allowed':False,'publication_approved':False,'facts_hypothetical':True,
        'current_stage_unchanged':current,'input_sha256':hashlib.sha256(_canonical(request)).hexdigest(),
        'notice':data['notices'].get(current,''),'decisions':data['decisions']}
