"""Challenge real appendix placeholders, source drift and unsafe interpolation."""

import pytest

from app.knowledge.template_preview import (TemplateCatalog,TemplatePreviewInvalid,load_catalog,preview)
from scripts.build_kg_template_catalog import build


@pytest.fixture
def catalog():
    return load_catalog()


def test_every_source_template_is_preserved_reproducibly(catalog):
    assert build()==catalog.document()
    data=catalog.document()
    assert len(data['templates'])==13
    for template in data['templates']:
        rendered=preview(catalog,template_id=template['unit_id'],values={})
        assert rendered['text']==template['text']
        assert rendered['unresolved']==[f['id'] for f in template['fields']]
        assert rendered['confirmation_status']==template['confirmation_status']
        assert rendered['send_allowed'] is False
    assert 'RL / FF:' in preview(catalog,template_id='KG.TPL.A04',values={})['text']


def test_repeated_dates_have_distinct_meanings_and_values(catalog):
    result=preview(catalog,template_id='KG.TPL.A06',values={'p01':'2026-10-01','p02':'SYN-12','p03':'5','p04':'2026-10-08'})
    assert 'подана 2026-10-01' in result['text'] and 'до\n2026-10-08' in result['text']
    assert result['unresolved']==[] and result['send_allowed'] is False


def test_inserted_braces_and_html_are_literal_never_evaluated(catalog):
    value='{__import__("os").system("false")} <script>alert(1)</script>'
    result=preview(catalog,template_id='KG.TPL.A03',values={'p01':value,'p02':30,'p03':'однократная','p04':{'amount':'62.50','currency':'USD'}})
    assert value in result['text'] and '$62.50' in result['text']
    assert result['send_allowed'] is False and result['publication_approved'] is False


@pytest.mark.parametrize('template_id,values',[
    ('KG.TPL.A03',{'p02':True}),('KG.TPL.A03',{'p02':0}),
    ('KG.TPL.A03',{'p02':'30'}),('KG.TPL.A03',{'p03':'unlimited'}),
    ('KG.TPL.A03',{'p04':{'amount':'62','currency':'KGS'}}),
    ('KG.TPL.A03',{'p04':{'amount':62.0,'currency':'USD'}}),
    ('KG.TPL.A03',{'p04':{'amount':'NaN','currency':'USD'}}),
    ('KG.TPL.A03',{'p04':{'amount':'1.999','currency':'USD'}}),
    ('KG.TPL.A03',{'p01':'abc\nforged line'}),
    ('KG.TPL.A03',{'p01':'a\u202eb'}),
    ('KG.TPL.A06',{'p01':'2026-02-30'}),
    ('KG.TPL.A06',{'p01':'20261001'}),
    ('KG.TPL.A05',{'p02':'javascript:alert(1)'}),
    ('KG.TPL.A05',{'p02':'https://user:pass@example.com'}),
    ('KG.TPL.A05',{'p02':'https://example.com:wrong'}),
    ('KG.TPL.A05',{'p02':'https://example.com\\@evil.com'}),
    ('KG.TPL.A06',{'дата':'2026-10-01'}),
])
def test_invalid_typed_value_is_refused(catalog,template_id,values):
    with pytest.raises(TemplatePreviewInvalid):preview(catalog,template_id=template_id,values=values)


def test_ambiguous_source_calculations_stay_unresolved(catalog):
    original=preview(catalog,template_id='KG.TPL.A08',values={})
    assert '{дата = +30 дней}' in original['text'] and original['confirmation_status']=='blocked'
    with pytest.raises(TemplatePreviewInvalid,match='calculation_not_approved'):
        preview(catalog,template_id='KG.TPL.A08',values={'p02':'2026-11-01'})


def test_money_retains_explicit_currency_and_https_is_not_fetched(catalog):
    rendered=preview(catalog,template_id='KG.TPL.A05',values={'p01':{'amount':'1000','currency':'KGS'},'p02':'https://example.invalid/invoice'})
    assert '1000 KGS' in rendered['text'] and 'https://example.invalid/invoice' in rendered['text']
    assert rendered['send_allowed'] is False


def test_source_drift_and_oversize_fail_and_returned_data_is_owned(catalog):
    with pytest.raises(TemplatePreviewInvalid):TemplateCatalog(catalog.raw.replace(b'false',b'true',1))
    with pytest.raises(TemplatePreviewInvalid):TemplateCatalog(b'x'*262145)
    first=catalog.document();first['publication_approved']=True
    assert catalog.document()['publication_approved'] is False
    result=preview(catalog,template_id='KG.TPL.A06',values={});result['fields'].clear()
    assert len(preview(catalog,template_id='KG.TPL.A06',values={})['fields'])==4
