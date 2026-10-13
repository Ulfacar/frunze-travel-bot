"""Deterministic typed v3 interview planning; no LLM, legal decision or sending."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from . import interview_catalog as catalog

VERSION='kg-interview-reducer/1'
UNKNOWN='unknown'
NA='not_applicable'
COUNTRIES=frozenset(json.loads((Path(__file__).resolve().parents[2]/'knowledge/kg_entry/source_v1_1/iso3166.json').read_text(encoding='utf-8')))
WORK=('work_hire','work_individual_employer','entrepreneur','equipment_installation')
FAMILY=('relatives_kg_citizen','family_of_foreigner','private_visit')
INTERRUPTS=frozenset(('manager_requested','complaint','refund','legal_question','unsafe_request','criminal_mention',
    'conflicting_answers','special_process','calendar_needed','uncertain_answer','consent_withdrawn'))
CONDITION_INPUTS={
    'own_minor':('applicant.age',),'own_child_born_kg':('applicant.age','applicant.born_in_kg'),
    'own_family_document':('purpose','applicant.family_relation','relationship_document.exists'),
    'own_adult_child':('purpose','applicant.family_relation','applicant.age'),
    'own_adult_child_or_parent':('purpose','applicant.family_relation','applicant.age'),
    'foreign_family_purpose':('purpose',),
    'always':(), 'consent_yes':('consent.given',), 'terms_yes':('terms.accepted',),
    'multiple_citizenships':('citizenships',), 'foreign_residence':('foreign_residence.exists',),
    'china_india':('citizenships',), 'long_visa':('long_visa.exists',), 'abroad':('location',),'in_kg':('location',),
    'detailed_purpose':('purpose',),'hard_deadline':('hard_deadline.exists',),'tourism':('purpose',),
    'organized_group':('organized_group.exists',),'event':('purpose',),'previous_visits':('previous_visits',),
    'history_member':('history_count',),'reported_window':('reported_window',),'entry_ban':('risk.entry_ban',),
    'previous_refusal':('previous_refusal',),'previous_visa_member':('previous_visa_count',),
    'current_visa':('current_basis',),'registered':('registration.exists',),'inviter_needed':('purpose',),
    'inviter':('inviter.exists',),'employer_or_study':('purpose','inviter.exists'),'work':('purpose',),
    'garment':('employment.garment',),'work_in_kg':('purpose','location'),'permit':('permit.exists',),
    'business':('purpose',),'company':('company.exists','company.planned'),'investor':('purpose',),
    'family_member':('family_count',),'family_purpose':('purpose',),'family_purpose_member':('family_count','purpose'),
    'family_document':('family_count','purpose','family.{i}.relationship_document'),
    'principal_document':('principal.status',),'minor_child':('family.{i}.relation','family.{i}.age'),
    'child':('family.{i}.relation',),'child_born_kg':('family.{i}.relation','family.{i}.born_in_kg'),
    'adult_child':('family.{i}.relation','family.{i}.age'),
    'adult_child_or_parent':('family.{i}.relation','family.{i}.age')}


class InterviewInvalid(ValueError):pass


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _known(value):return value is not None and value not in (UNKNOWN,NA)


def _day(value):
    if type(value) is not str:raise InterviewInvalid('invalid_date')
    try:
        day=date.fromisoformat(value)
        if day.isoformat()!=value:raise ValueError
        return day
    except ValueError:raise InterviewInvalid('invalid_date') from None


def validate_value(field,value):
    if type(value) is str and value in (UNKNOWN,NA):return value
    kind=field['kind']
    if kind=='boolean':
        if type(value) is not bool:raise InterviewInvalid('invalid_boolean')
    elif kind=='integer':
        if type(value) is not int or not 0<=value<=field['maximum']:raise InterviewInvalid('invalid_integer')
        if field['path']=='applicants_count' and value==0:raise InterviewInvalid('invalid_applicant_count')
    elif kind in ('countries','choices'):
        allowed=COUNTRIES if kind=='countries' else field['choices']
        if (type(value) is not list or len(value)>(5 if kind=='countries' else len(allowed)) or
            kind=='countries' and not value or any(type(v) is not str or v not in allowed for v in value) or
            len(value)!=len(set(value))):raise InterviewInvalid('invalid_choices')
        value=sorted(value)
    else:
        if type(value) is not str or not value or value.strip()!=value or any(unicodedata.category(c).startswith('C') for c in value):
            raise InterviewInvalid('invalid_text')
        if kind=='date':_day(value)
        elif kind=='country':
            if value not in COUNTRIES:raise InterviewInvalid('invalid_country')
        elif kind=='choice':
            if value not in field['choices']:raise InterviewInvalid('invalid_choice')
        elif kind=='proof':
            if not re.fullmatch('[a-f0-9]{64}',value):raise InterviewInvalid('invalid_proof')
        elif kind=='opaque':
            if not re.fullmatch('[A-Z][A-Z0-9._/-]{0,79}',value):raise InterviewInvalid('invalid_reference')
        elif kind=='decimal':
            if not re.fullmatch(r'(0|[1-9][0-9]{0,11})(\.[0-9]{1,2})?',value):raise InterviewInvalid('invalid_decimal')
            try:Decimal(value)
            except InvalidOperation:raise InterviewInvalid('invalid_decimal') from None
        elif kind=='text':
            if len(value)>field['maximum'] or len(value.encode())>2000:raise InterviewInvalid('invalid_text')
        else:raise InterviewInvalid('unknown_field_type')
    return deepcopy(value)


class Answers:
    """Latest answers retain dependency revision stamps; old commands remain in the journal."""
    def __init__(self,values,*,catalog_document=None):
        if type(values) is not dict or len(values)>1000:raise InterviewInvalid('invalid_answers')
        self.values=values;self.catalog_document=catalog.document() if catalog_document is None else catalog_document
        repeats=self.catalog_document['repeats']
        counts={p:v.get('value') for p,v in values.items() if p in repeats.values() and type(v) is dict}
        for prefix,p in repeats.items():
            count=counts.get(p)
            maximum=100 if prefix=='history' else 20
            if type(count) is int and not 0<=count<=maximum:raise InterviewInvalid('invalid_repeat_count')
        self.fields={f['path']:f for f in catalog.expanded(counts,catalog_document=self.catalog_document)}
        # Retain inactive ordinal answers for audit; they cannot be used as another member.
        for path in values:
            if path not in self.fields:
                match=re.fullmatch(r'(family|history|previous_visa)\.([1-9][0-9]*)\.(\w+)',path)
                if not match:raise InterviewInvalid('unknown_answer_path')
                prefix,index,_=match.groups();max_index=100 if prefix=='history' else 20
                if int(index)>max_index:raise InterviewInvalid('unknown_answer_path')
                possible={f['path']:f for f in catalog.expanded({repeats[prefix]:int(index)},catalog_document=self.catalog_document)}
                if path not in possible:raise InterviewInvalid('unknown_answer_path')
                self.fields[path]=possible[path]
        self._busy=set();self._cache={}
        for path,row in values.items():
            if (type(row) is not dict or row.keys()!={'value','revision','context'} or
                type(row['revision']) is not int or row['revision']<1 or
                type(row['context']) is not str or not re.fullmatch('[a-f0-9]{64}',row['context'])):raise InterviewInvalid('invalid_answer_record')
            if validate_value(self.fields[path],row['value'])!=row['value']:raise InterviewInvalid('noncanonical_answer')

    def dependencies(self,path):
        field=self.fields[path];member=str(field.get('member',''))
        return set(field['depends'])|{p.replace('{i}',member) for p in CONDITION_INPUTS[field['when']]}

    def context(self,path):
        found={}
        def visit(key,seen):
            if key in seen:raise InterviewInvalid('catalog_dependency_cycle')
            if key in found:return
            row=self.values.get(key)
            found[key]=row
            if key in self.fields:
                for parent in self.dependencies(key):visit(parent,seen|{key})
        for parent in sorted(self.dependencies(path)):visit(parent,{path})
        return digest(found)

    def fresh(self,path):
        if path not in self.values or path not in self.fields:return False
        return self.values[path]['context']==self.context(path)

    def get(self,path):
        if path in self._cache:return self._cache[path]
        if path in self._busy:raise InterviewInvalid('catalog_dependency_cycle')
        self._busy.add(path)
        try:
            value=self.values[path]['value'] if self.fresh(path) else None
            if value is not None and self.applicability(self.fields[path]) is not True:value=None
            self._cache[path]=value;return value
        finally:self._busy.remove(path)

    def applicability(self,f):
        rule=f['when'];idx=f.get('member');prefix=f'family.{idx}.'
        def is_(path,*allowed):
            if path in self.fields and self.applicability(self.fields[path]) is False:return False
            value=self.get(path)
            return value in allowed if _known(value) else None
        def all_(*items):return False if False in items else None if None in items else True
        def repeated(kind):
            parent=self.catalog_document['repeats'][kind]
            if self.applicability(self.fields[parent]) is False:return False
            value=self.get(parent)
            return idx<=value if type(value) is int else None
        if rule=='always':return True
        boolean={'consent_yes':'consent.given','terms_yes':'terms.accepted','foreign_residence':'foreign_residence.exists',
            'long_visa':'long_visa.exists','hard_deadline':'hard_deadline.exists','organized_group':'organized_group.exists',
            'previous_visits':'previous_visits','entry_ban':'risk.entry_ban','previous_refusal':'previous_refusal',
            'registered':'registration.exists','inviter':'inviter.exists','garment':'employment.garment','permit':'permit.exists'}
        if rule in boolean:return is_(boolean[rule],True)
        if rule in ('abroad','in_kg'):return is_('location',rule)
        if rule in ('multiple_citizenships','china_india'):
            value=self.get('citizenships')
            if type(value) is not list:return None
            return len(value)>1 if rule=='multiple_citizenships' else bool(set(value)&{'CHN','IND'})
        if rule in ('inviter_needed','detailed_purpose'):
            value=self.get('purpose');return value not in ('tourism','transit') if _known(value) else None
        if rule=='tourism':return is_('purpose','tourism')
        if rule=='event':return is_('purpose','event','sport','medical','business_meeting')
        if rule=='work':return is_('purpose',*WORK)
        if rule=='work_in_kg':return all_(is_('purpose',*WORK),is_('location','in_kg'))
        if rule=='employer_or_study':return all_(is_('purpose',*WORK,'study'),is_('inviter.exists',True))
        if rule=='business':return is_('purpose','business_meeting','entrepreneur','investor')
        if rule=='investor':return is_('purpose','investor')
        if rule=='company':
            items=(is_('company.exists',True),is_('company.planned',True))
            return True if True in items else None if None in items else False
        if rule=='current_visa':return is_('current_basis','visa')
        if rule=='reported_window':
            if self.applicability(self.fields['reported_window']) is False:return False
            return True if _known(self.get('reported_window')) else None
        if rule=='principal_document':
            if self.applicability(self.fields['principal.status']) is False:return False
            value=self.get('principal.status');return value not in ('citizen','none') if _known(value) else None
        if rule in ('family_member','history_member','previous_visa_member'):return repeated(rule[:-7])
        if rule=='family_purpose':return is_('purpose',*FAMILY)
        if rule=='foreign_family_purpose':return is_('purpose','family_of_foreigner')
        if rule=='own_family_document':return all_(is_('purpose',*FAMILY),is_('relationship_document.exists',True))
        if rule in ('own_minor','own_child_born_kg'):
            age=self.get('applicant.age');minor=age<18 if type(age) is int else None
            return minor if rule=='own_minor' else all_(minor,is_('applicant.born_in_kg',True))
        if rule in ('own_adult_child','own_adult_child_or_parent'):
            family=is_('purpose',*FAMILY)
            if rule=='own_adult_child_or_parent' and is_('applicant.family_relation','parent') is True:return family
            age=self.get('applicant.age');adult=age>=18 if type(age) is int else None
            return all_(family,is_('applicant.family_relation','child'),adult)
        if rule=='family_purpose_member':return all_(repeated('family'),is_('purpose',*FAMILY))
        if rule=='family_document':return all_(repeated('family'),is_('purpose',*FAMILY),is_(prefix+'relationship_document',True))
        if rule in ('child','child_born_kg','minor_child','adult_child','adult_child_or_parent'):
            child=is_(prefix+'relation','child')
            if rule=='child':return all_(repeated('family'),child)
            if rule=='child_born_kg':return all_(repeated('family'),child,is_(prefix+'born_in_kg',True))
            if rule=='adult_child_or_parent' and is_(prefix+'relation','parent') is True:return repeated('family')
            age=self.get(prefix+'age');age_ok=(age<18 if rule=='minor_child' else age>=18) if type(age) is int else None
            return all_(repeated('family'),child,age_ok)
        raise InterviewInvalid('unknown_condition')


def consent_complete(a,on):
    return (a.get('consent.given') is True and all(_known(a.get('consent.'+p)) for p in ('on','evidence_ref','evidence_sha256'))
            and _day(a.get('consent.on'))<=_day(on))


def analyze(values,*,on,language,pre_consent,catalog_document=None):
    if language not in ('ru','en'):raise InterviewInvalid('invalid_language')
    today=_day(on);a=Answers(values,catalog_document=catalog_document);gaps=[];stale=[];askable=[];status={};consent=consent_complete(a,on)
    for path,f in a.fields.items():
        applies=a.applicability(f);row=values.get(path);fresh=a.fresh(path)
        if row is not None and not fresh:stale.append(path)
        state=('not_applicable' if applies is False else 'applicability_unknown' if applies is None else
               'stale' if row is not None and not fresh else 'missing' if row is None else
               'unknown' if row['value']==UNKNOWN else 'invalid_not_applicable' if row['value']==NA else 'answered')
        status[path]=state
        if state not in ('not_applicable','answered'):gaps.append(dict(path=path,code=f['code'],reason=state))
        if applies is True and (row is None or not fresh) and (consent or template_path(path) in pre_consent):askable.append(f)
    stops=[]
    if a.get('consent.given') is False:stops.append('consent_not_granted')
    if a.get('document_type') not in (None,UNKNOWN,NA,'ordinary'):stops.append('special_document')
    if a.get('purpose') in WORK:stops.append('work_specialist')
    if a.get('party_type')=='company' or type(a.get('applicants_count')) is int and a.get('applicants_count')>5:stops.append('group_or_company')
    for key in ('risk.overstay','risk.fines','risk.deportation','risk.entry_ban','previous_refusal','residence_petition'):
        if a.get(key) is True:stops.append('reported_'+key)
    if a.get('current_basis')=='none':stops.append('current_basis_missing')
    for key in ('passport_expiry','current_until','registration.until','hard_deadline.on'):
        value=a.get(key)
        if _known(value) and _day(value)<today:stops.append(key+'_passed')
    conflicts=[]
    for first,last in [('entry_on','exit_on'),('event.from','event.to'),('employment.contract_from','employment.contract_until'),('long_visa.from','long_visa.until')]:
        if _known(a.get(first)) and _known(a.get(last)) and a.get(first)>a.get(last):conflicts.append(first+'_after_'+last)
    if _known(a.get('actual_entry.on')) and _day(a.get('actual_entry.on'))>today:conflicts.append('future_actual_entry')
    if _known(a.get('consent.on')) and _day(a.get('consent.on'))>today:conflicts.append('future_consent')
    if _known(a.get('terms.on')) and _day(a.get('terms.on'))>today:conflicts.append('future_terms_acceptance')
    if _known(a.get('applicant.birth_on')) and _day(a.get('applicant.birth_on'))>today:conflicts.append('future_applicant_birth')
    if type(a.get('applicant.age')) is int and a.get('applicant.age')<18 and a.get('applicant.both_parents') is False:stops.append('minor_applicant_without_both_parents')
    if type(a.get('citizenships')) is list and _known(a.get('passport_country')) and a.get('passport_country') not in a.get('citizenships'):conflicts.append('passport_citizenship')
    if type(a.get('family_count')) is int and type(a.get('applicants_count')) is int and a.get('family_count')+1>a.get('applicants_count'):conflicts.append('family_exceeds_group')
    if type(a.get('reported_days')) is int and _known(a.get('reported_window')) and a.get('reported_days')>int(a.get('reported_window')):conflicts.append('reported_days_exceed_window')
    for i in range(1,(a.get('family_count') if type(a.get('family_count')) is int else 0)+1):
        p=f'family.{i}.'
        if a.get(p+'together') is True and a.get(p+'later') is True:conflicts.append(p+'arrival_conflict')
        if a.get(p+'relation')=='child' and type(a.get(p+'age')) is int and a.get(p+'age')<18 and a.get(p+'both_parents') is False:stops.append('minor_without_both_parents')
        if _known(a.get(p+'birth_on')) and _day(a.get(p+'birth_on'))>today:conflicts.append(p+'future_birth')
    intervals=[]
    for i in range(1,(a.get('history_count') if type(a.get('history_count')) is int else 0)+1):
        first,last=a.get(f'history.{i}.entry'),a.get(f'history.{i}.exit')
        if _known(first) and _known(last):
            if first>last or _day(last)>today:conflicts.append(f'history.{i}.date_conflict')
            intervals.append((first,last))
    intervals.sort()
    if any(b[0]<=a_[1] for a_,b in zip(intervals,intervals[1:])):conflicts.append('reported_intervals_overlap')
    for i in range(1,(a.get('previous_visa_count') if type(a.get('previous_visa_count')) is int else 0)+1):
        first,last=a.get(f'previous_visa.{i}.from'),a.get(f'previous_visa.{i}.until')
        if _known(first) and _known(last) and first>last:conflicts.append(f'previous_visa.{i}.date_conflict')
    if conflicts:stops.append('conflicting_answers')
    priority={p:i for i,p in enumerate(a.catalog_document['primary'])}
    askable.sort(key=lambda f:(0 if f['path'].startswith('consent.') else 1 if f['path'] in priority else 2,priority.get(f['path'],1000),list(a.fields).index(f['path'])))
    selected=[]
    for f in askable:
        if any(other['path'] in a.dependencies(f['path']) or f['path'] in a.dependencies(other['path']) for other in selected):continue
        selected.append(f)
        if len(selected)==3:break
    questions=[dict(path=f['path'],code=f['code'],text=f[language],rationale=f['rationale_'+language],kind=f['kind'],choices=f['choices'],maximum=f['maximum']) for f in selected]
    return dict(catalog_version=a.catalog_document['version'],reducer_version='kg-interview-reducer/1',on=on,language=language,consent_complete=consent,
        gaps=gaps,stale=sorted(stale),field_states=status,stops=sorted(set(stops)),conflicts=sorted(set(conflicts)),
        questions=[] if stops else questions,manual_questions=questions,legal_qualification='unknown',quote='unknown',confidence=None)


def template_path(path):return re.sub(r'\.(?:[1-9][0-9]*)\.', '.{i}.',path)


def apply_answers(values,changes,*,revision,on,pre_consent,removals=(),catalog_document=None):
    if (type(changes) is not dict or type(removals) not in (tuple,list) or
        not 1<=len(changes)+len(removals)<=3 or len(set(removals))!=len(removals) or set(changes)&set(removals)):
        raise InterviewInvalid('invalid_answer_batch')
    a=Answers(values,catalog_document=catalog_document);result=deepcopy(values);allowed=consent_complete(a,on)
    for path in set(changes)|set(removals):
        if path not in a.fields:raise InterviewInvalid('unknown_answer_path')
        if not allowed and template_path(path) not in pre_consent:raise InterviewInvalid('consent_required')
        if a.dependencies(path)&(set(changes)|set(removals)):raise InterviewInvalid('dependent_batch_requires_separate_confirmation')
    for path in removals:
        if path not in result:raise InterviewInvalid('answer_missing')
        del result[path]
    for path,value in changes.items():
        f=a.fields[path];value=validate_value(f,value);applicable=a.applicability(f)
        if value==NA and applicable is not False:raise InterviewInvalid('unproven_not_applicable')
        if applicable is False and value!=NA:raise InterviewInvalid('field_not_applicable')
        # Reaffirming a current fact must not invalidate its dependent evidence.
        # A stale identical value is an explicit new confirmation and gets a new stamp.
        if a.fresh(path) and a.values[path]['value']==value:continue
        result[path]=dict(value=value,revision=revision,context=a.context(path))
    if len(json.dumps(result,ensure_ascii=False).encode())>262144:raise InterviewInvalid('answers_size_limit')
    return result
