from copy import deepcopy
from decimal import localcontext,Inexact
import pytest
from app.knowledge import quote_rules as rules

ON='2026-10-11'


def line(component,amount='50.00',**changes):
    return dict(id=component.upper(),title_ru='Synthetic '+component,title_en='Synthetic '+component,
        component=component,status='known',currency='USD',amount=amount,step_amount='0.00',
        urgent_multiplier='3' if component=='government' else '1',reference='SYN-RATE',proof='a'*64,
        urgent_reference='SYN-URGENCY' if component=='government' else None,
        urgent_proof='b'*64 if component=='government' else None,reason=None)|changes


def na(component):
    return line(component,None,status='not_applicable',currency=None,step_amount=None,urgent_multiplier=None,
        urgent_reference=None,urgent_proof=None,reason='Synthetic explicit exemption')


def unknown(component):
    return line(component,None,status='unknown',currency=None,step_amount=None,urgent_multiplier=None,
        reference=None,proof=None,urgent_reference=None,urgent_proof=None,reason='Synthetic fee is unknown')


def recipe(**changes):
    return dict(format='kg-quote-recipe/1',id='SYN-TS',version='SYN-V1',title_ru='Synthetic quote',title_en='Synthetic quote',
        procedure='visa',valid_from='2026-01-01',review_due_on='2026-12-31',authority_reference='SYN-AUTHORITY',
        authority_proof='c'*64,max_additional_blocks=12,
        lines=[line('service'),line('government'),unknown('bank'),na('partner')])|changes


def request(**changes):return dict(recipe_id='SYN-TS',additional_blocks=0,urgent=False)|changes


def calculate(value=None,**changes):return rules.calculate(value or recipe(),request(**changes),on=ON)


@pytest.mark.parametrize('base,step,blocks,urgent,expected',[
    ('50.00','0.00',0,False,'100.00'),('50.00','0.00',0,True,'200.00'),
    ('60.00','15.00',2,False,'140.00'),('60.00','15.00',2,True,'320.00')])
def test_pdf_shaped_known_subtotals_never_hide_unknown_bank(base,step,blocks,urgent,expected):
    r=recipe();r['lines'][1]=line('government',base,step_amount=step)
    result=calculate(r,additional_blocks=blocks,urgent=urgent)
    assert not result['complete'] and result['totals_by_currency'] is None
    assert result['known_subtotals']=={'USD':expected}
    assert result['component_subtotals']['service']=={'USD':'50.00'}
    assert result['issues']==[{'line_id':'BANK','code':'quote_price_unknown'}]
    assert result['legal_eligibility']=='not_assessed' and result['payment']=='not_created'


def test_mixed_currencies_multiple_government_lines_and_exact_source_pins():
    r=recipe();r['lines'][2]=line('bank','10.01',currency='KGS')
    r['lines'].append(line('government','5000.00',id='DEPOSIT',currency='KGS',urgent_multiplier='1'))
    result=calculate(r,urgent=True)
    assert result['complete'] and result['totals_by_currency']=={'KGS':'5010.01','USD':'200.00'}
    assert result['component_subtotals']['government']=={'KGS':'5000.00','USD':'150.00'}
    assert result['lines'][1]['urgent_proof']=='b'*64
    assert result['recipe_hash']==rules.digest(r) and result['currency_conversion']=='not_performed'


@pytest.mark.parametrize('value',[True,50,50.1,'NaN','Infinity','-0.00','-1.00','1e2','1.001','1.0','01.00','1000000000.00',' 1.00'])
def test_money_requires_bounded_canonical_decimal_strings(value):
    r=recipe();r['lines'][0]['amount']=value
    with pytest.raises(rules.QuoteInvalid):calculate(r)


def test_zero_is_not_unknown_and_needs_explicit_evidence():
    r=recipe();r['lines'][2]=line('bank','0.00')
    with pytest.raises(rules.QuoteInvalid,match='zero_evidence'):calculate(r)
    r['lines'][2]['reason']='Synthetic bank waiver'
    result=calculate(r)
    assert result['complete'] and result['lines'][2]['total']=='0.00'
    r['lines'][2]['reference']=None;r['lines'][2]['proof']=None
    with pytest.raises(rules.QuoteInvalid,match='evidence_required'):calculate(r)


@pytest.mark.parametrize('mutation',['missing_component','duplicate','unknown_amount','na_without_evidence','service_urgent','no_urgent_evidence','extra'])
def test_incomplete_or_unproven_recipe_rejected(mutation):
    r=recipe()
    if mutation=='missing_component':r['lines'][2]=na('partner');r['lines'][2]['id']='PARTNER2'
    if mutation=='duplicate':r['lines'].append(deepcopy(r['lines'][0]))
    if mutation=='unknown_amount':r['lines'][2]['amount']='0.00'
    if mutation=='na_without_evidence':r['lines'][3]['reference']=None;r['lines'][3]['proof']=None
    if mutation=='service_urgent':r['lines'][0]['urgent_multiplier']='3'
    if mutation=='no_urgent_evidence':r['lines'][1]['urgent_reference']=None;r['lines'][1]['urgent_proof']=None
    if mutation=='extra':r['discount']='10.00'
    with pytest.raises(rules.QuoteInvalid):calculate(r)


def test_unknown_urgency_and_subcent_are_blocked_without_rounding():
    r=recipe();r['lines'][2]=na('bank')
    r['lines'][1].update(urgent_multiplier=None,urgent_reference=None,urgent_proof=None)
    assert calculate(r)['complete']
    assert calculate(r,urgent=True)['issues']==[{'line_id':'GOVERNMENT','code':'quote_urgent_price_unknown'}]
    r['lines'][1]=line('government','0.01',urgent_multiplier='1.5')
    result=calculate(r,urgent=True)
    assert result['totals_by_currency'] is None and result['lines'][1]['total'] is None
    assert result['issues'][0]['code']=='quote_rounding_policy_required'


def test_context_independence_expiry_overflow_and_calculator_version():
    r=recipe();r['lines'][2]=na('bank')
    expected=calculate(r)
    with localcontext() as context:
        context.prec=2;context.traps[Inexact]=True
        assert calculate(r)==expected
    r['review_due_on']='2026-10-10';assert not calculate(r)['complete']
    r['review_due_on']='2026-12-31';r['lines'][1]['amount']='999999999.99'
    assert calculate(r,urgent=True)['totals_by_currency'] is None
    with pytest.raises(rules.QuoteInvalid,match='unsupported_quote_calculator'):
        rules.calculate(r,request(),on=ON,version='kg-quote-calculator/99')


@pytest.mark.parametrize('changes',[{'additional_blocks':True},{'additional_blocks':-1},{'additional_blocks':121},
    {'urgent':1},{'amount':'1.00'},{'quantity':3},{'recipe_id':'FOREIGN'}])
def test_manual_parameters_cannot_inject_prices_or_other_people(changes):
    with pytest.raises(rules.QuoteInvalid):calculate(**changes)


def test_immutable_input_and_all_exempt_does_not_invent_currency_or_price():
    r=recipe();original=deepcopy(r);calculate(r);assert r==original
    r['lines']=[na(component) for component in rules.COMPONENTS]
    assert calculate(r)['totals_by_currency'] is None

def test_retained_v1_does_not_read_active_version(monkeypatch):
    from app.knowledge import quote_rules as rules
    monkeypatch.setattr(rules,'VERSION','kg-quote-calculator/2')
    old=rules.calculate(recipe(),request(),on='2026-10-11',version='kg-quote-calculator/1')
    assert old['calculator_version']=='kg-quote-calculator/1'
