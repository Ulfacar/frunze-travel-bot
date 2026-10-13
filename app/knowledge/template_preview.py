"""Literal typed draft previews; never executes source expressions or sends text."""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PATH = Path(__file__).resolve().parents[2]/'knowledge/kg_entry/templates_v1_1/catalog.json'
CATALOG_SHA256 = '38c503d27135736d1fb3990a0626fc12be8a364fcc6bfa6d98108ba824dcf2b8'
SLOT = re.compile(r'\{([^{}]+)\}')
CONTROLS = re.compile(r'[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]')


class TemplatePreviewInvalid(ValueError):
    pass


@dataclass(frozen=True)
class TemplateCatalog:
    raw: bytes

    def __post_init__(self):
        if type(self.raw) is not bytes or len(self.raw)>262144:
            raise TemplatePreviewInvalid('template_catalog_invalid')
        normalized=self.raw.replace(b'\r\n',b'\n')
        if hashlib.sha256(normalized).hexdigest()!=CATALOG_SHA256:
            raise TemplatePreviewInvalid('template_catalog_invalid')
        object.__setattr__(self,'raw',normalized)

    def document(self):
        return json.loads(self.raw)


def load_catalog(path=PATH):
    try:
        with Path(path).open('rb') as stream:
            return TemplateCatalog(stream.read(262145))
    except OSError:
        raise TemplatePreviewInvalid('template_catalog_unavailable') from None


def _text(value,maximum=500):
    if type(value) is not str or not 1<=len(value)<=maximum or value!=value.strip() or CONTROLS.search(value):
        raise TemplatePreviewInvalid('invalid_template_value')
    return value


def _render(field,value):
    kind=field['kind']
    if kind=='unresolved_calculation':
        raise TemplatePreviewInvalid('template_calculation_not_approved')
    if kind=='positive_integer':
        if type(value) is not int or not 1<=value<=36600:
            raise TemplatePreviewInvalid('invalid_template_integer')
        return str(value)
    if kind=='money':
        if type(value) is not dict or set(value)!={'amount','currency'}:
            raise TemplatePreviewInvalid('invalid_template_money')
        amount=value['amount'];currency=value['currency']
        if type(amount) is not str or not re.fullmatch(r'(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?',amount):
            raise TemplatePreviewInvalid('invalid_template_money')
        if type(currency) is not str or not re.fullmatch('[A-Z]{3}',currency):
            raise TemplatePreviewInvalid('invalid_template_currency')
        if field['currency'] and currency!=field['currency']:
            raise TemplatePreviewInvalid('template_currency_mismatch')
        return amount if field['currency'] else amount+' '+currency
    value=_text(value)
    if kind=='date':
        try:
            if date.fromisoformat(value).isoformat()!=value:
                raise ValueError
        except ValueError:
            raise TemplatePreviewInvalid('invalid_template_date') from None
    if kind=='choice' and value not in field['choices']:
        raise TemplatePreviewInvalid('invalid_template_choice')
    if kind=='https_url':
        try:
            parsed=urlsplit(value)
            if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or
                parsed.password is not None or '\\' in value or any(c.isspace() for c in value)):
                raise ValueError
            _=parsed.port
        except ValueError:
            raise TemplatePreviewInvalid('invalid_template_url') from None
    return value


def preview(catalog,*,template_id,values):
    data=catalog.document()
    if type(template_id) is not str or type(values) is not dict:
        raise TemplatePreviewInvalid('invalid_template_request')
    template=next((u for u in data['templates'] if u['unit_id']==template_id),None)
    if template is None or not values.keys()<= {f['id'] for f in template['fields']}:
        raise TemplatePreviewInvalid('invalid_template_request')
    fields=iter(template['fields']);unresolved=[]
    def replace(match):
        field=next(fields)
        if field['id'] not in values:
            unresolved.append(field['id'])
            return match[0]
        return _render(field,values[field['id']])
    rendered=SLOT.sub(replace,template['text'])
    # Inserted text is never parsed again, including braces, HTML or instructions.
    return dict(template_id=template_id,text=rendered,unresolved=unresolved,
                fields=template['fields'],source_sha256=data['source_sha256'],
                template_sha256=template['text_sha256'],catalog_sha256=CATALOG_SHA256,
                source_ref=template['source_ref'],page=template['page'],
                confirmation_status=template['confirmation_status'],label=template['label'],
                publication_approved=False,send_allowed=False,status='draft_preview')
