"""Bounded exact quote arithmetic. A supplied recipe is not legal eligibility."""
from copy import deepcopy
from datetime import date
from decimal import Context,Decimal,localcontext
import hashlib
import json
import re
import unicodedata

VERSION='kg-quote-calculator/1'
COMPONENTS=('service','government','bank','partner')
PROCEDURES=('visa','unified_permit','resident_card','registration','violation_protocol','exit_visa')
MAX_AMOUNT=Decimal('999999999.99')
CENT=Decimal('.01')


class QuoteInvalid(ValueError):pass


def fail(code='invalid_quote_recipe'):raise QuoteInvalid(code)


def exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys):fail()


def day(value):
    try:
        if type(value) is not str:raise ValueError
        parsed=date.fromisoformat(value)
        if parsed.isoformat()!=value:raise ValueError
        return parsed
    except ValueError:fail('invalid_quote_date')


def label(value,maximum=180):
    if (type(value) is not str or not value.strip() or value!=value.strip() or len(value)>maximum
        or len(value.encode())>maximum*4 or any(unicodedata.category(c).startswith('C') for c in value)):
        fail('invalid_quote_label')
    return value


def token(value):
    if type(value) is not str or not re.fullmatch('[A-Z][A-Z0-9._/-]{0,79}',value):fail('invalid_quote_reference')
    return value


def proof(value):
    if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):fail('invalid_quote_proof')
    return value


def money(value):
    if type(value) is not str or not re.fullmatch(r'(0|[1-9][0-9]{0,8})\.[0-9]{2}',value):fail('invalid_quote_amount')
    result=Decimal(value)
    if result>MAX_AMOUNT:fail('invalid_quote_amount')
    return result


def multiplier(value):
    if type(value) is not str or not re.fullmatch(r'(?:[1-9]|10)(?:\.[0-9]{1,4})?',value):fail('invalid_quote_multiplier')
    result=Decimal(value)
    if not Decimal(1)<=result<=Decimal(10):fail('invalid_quote_multiplier')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _line(value):
    exact(value,('id','title_ru','title_en','component','status','currency','amount','step_amount',
        'urgent_multiplier','reference','proof','urgent_reference','urgent_proof','reason'))
    token(value['id']);label(value['title_ru']);label(value['title_en'])
    if value['component'] not in COMPONENTS or value['status'] not in ('known','unknown','not_applicable'):fail()
    if value['reason'] is not None:label(value['reason'])
    for ref,sha in (('reference','proof'),('urgent_reference','urgent_proof')):
        if (value[ref] is None)!=(value[sha] is None):fail('incomplete_quote_evidence')
        if value[ref] is not None:token(value[ref]);proof(value[sha])
    if value['status']=='known':
        if value['currency'] not in ('USD','KGS'):fail('unsupported_quote_currency')
        amount=money(value['amount']);step=money(value['step_amount'])
        if value['reference'] is None:fail('quote_evidence_required')
        if amount==0 and not value['reason']:fail('quote_zero_evidence_required')
        factor=value['urgent_multiplier']
        if value['component']!='government':
            if factor!='1' or value['urgent_reference'] is not None:fail('government_only_urgency')
        elif factor is not None:
            multiplier(factor)
            if value['urgent_reference'] is None:fail('quote_urgency_evidence_required')
        elif value['urgent_reference'] is not None:fail('invalid_quote_urgency')
    else:
        if any(value[k] is not None for k in ('amount','step_amount','urgent_multiplier','urgent_reference','urgent_proof')):fail()
        if not value['reason']:fail('quote_unknown_reason_required')
        if value['status']=='not_applicable':
            if value['currency'] is not None or value['reference'] is None:fail('quote_exemption_evidence_required')
        elif value['currency'] not in ('USD','KGS',None):fail('unsupported_quote_currency')


def validate_recipe(value):
    exact(value,('format','id','version','title_ru','title_en','procedure','valid_from','review_due_on',
        'authority_reference','authority_proof','max_additional_blocks','lines'))
    if value['format']!='kg-quote-recipe/1' or value['procedure'] not in PROCEDURES:fail()
    for key in ('id','version','authority_reference'):token(value[key])
    proof(value['authority_proof']);label(value['title_ru']);label(value['title_en'])
    if day(value['valid_from'])>day(value['review_due_on']):fail('invalid_quote_validity')
    if type(value['max_additional_blocks']) is not int or not 0<=value['max_additional_blocks']<=120:fail('invalid_quote_blocks')
    lines=value['lines']
    if type(lines) is not list or not 4<=len(lines)<=32:fail('invalid_quote_lines')
    for line in lines:_line(line)
    if len({line['id'] for line in lines})!=len(lines):fail('duplicate_quote_line')
    if {line['component'] for line in lines}!=set(COMPONENTS):fail('quote_component_missing')
    if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>65536:fail('quote_recipe_size_limit')
    return deepcopy(value)


def validate_request(value,recipe):
    exact(value,('recipe_id','additional_blocks','urgent'))
    if value['recipe_id']!=recipe['id']:fail('quote_recipe_mismatch')
    if type(value['additional_blocks']) is not int or not 0<=value['additional_blocks']<=recipe['max_additional_blocks']:fail('invalid_quote_blocks')
    if type(value['urgent']) is not bool:fail('invalid_quote_urgent')
    return deepcopy(value)


def _calculate_v1(recipe,request,*,on):
    recipe=validate_recipe(recipe);request=validate_request(request,recipe);today=day(on)
    subtotal={};by_component={key:{} for key in COMPONENTS};lines=[];issues=[]
    valid=day(recipe['valid_from'])<=today<=day(recipe['review_due_on'])
    for source in recipe['lines']:
        result={k:deepcopy(source[k]) for k in ('id','title_ru','title_en','component','status','currency','reference','proof','reason')}
        result.update(total=None,base=source['amount'],step=source['step_amount'],additional_blocks=request['additional_blocks'],
            multiplier=None,urgent_reference=source['urgent_reference'] if request['urgent'] else None,
            urgent_proof=source['urgent_proof'] if request['urgent'] else None)
        reason=None
        if not valid:reason='quote_recipe_expired_or_future'
        elif source['status']=='unknown':reason='quote_price_unknown'
        elif source['status']=='known':
            factor=source['urgent_multiplier'] if request['urgent'] else '1'
            if factor is None:reason='quote_urgent_price_unknown'
            else:
                with localcontext() as context:
                    context.prec=32
                    total=(money(source['amount'])+money(source['step_amount'])*request['additional_blocks'])*multiplier(factor)
                    if total>MAX_AMOUNT:reason='quote_total_limit'
                    elif total!=total.quantize(CENT):reason='quote_rounding_policy_required'
                    else:
                        result.update(total=f'{total:.2f}',multiplier=factor)
                        currency=source['currency'];component=by_component[source['component']]
                        subtotal[currency]=subtotal.get(currency,Decimal(0))+total
                        component[currency]=component.get(currency,Decimal(0))+total
        if reason:issues.append(dict(line_id=source['id'],code=reason))
        lines.append(result)
    if any(v>MAX_AMOUNT for v in subtotal.values()):issues.append(dict(line_id=None,code='quote_total_limit'))
    if not subtotal and not issues:issues.append(dict(line_id=None,code='quote_no_priced_line'))
    amounts=lambda values:{key:f'{value:.2f}' for key,value in sorted(values.items())}
    known=amounts(subtotal);complete=not issues
    return dict(calculator_version='kg-quote-calculator/1',recipe_hash=digest(recipe),recipe_id=recipe['id'],recipe_version=recipe['version'],
        on=on,applicants=1,status='complete' if complete else 'blocked',complete=complete,lines=lines,issues=issues,
        known_subtotals=known,totals_by_currency=known if complete else None,
        component_subtotals={key:amounts(value) for key,value in by_component.items()},
        currency_conversion='not_performed',legal_eligibility='not_assessed',payment='not_created')


CALCULATORS={VERSION:_calculate_v1}


def calculate(recipe,request,*,on,version=None):
    version=VERSION if version is None else version
    if type(version) is not str:fail('unsupported_quote_calculator')
    calculator=CALCULATORS.get(version)
    if calculator is None:fail('unsupported_quote_calculator')
    with localcontext(Context(prec=40)):
        return calculator(recipe,request,on=on)
