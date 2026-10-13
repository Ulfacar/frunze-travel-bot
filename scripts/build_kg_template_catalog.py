"""Preserve appendix A as a pinned catalog, without approving source assertions."""
import hashlib
import json
from pathlib import Path
import re

from app.knowledge.validation import load_document

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
SLOT = re.compile(r'\{([^{}]+)\}')


def slot_type(token):
    if token in ('дата', 'дата окончания', 'date', 'end date'):
        return 'date'
    if token in ('N', 'M', 'K'):
        return 'positive_integer'
    if token == 'сумма':
        return 'money'
    if token == 'ссылка':
        return 'https_url'
    if token in ('однократная/многократная', 'single/multiple', 'туризм/деловая поездка', 'tourism/business', '5/2'):
        return 'choice'
    if token in ('дата = +30 дней', 'дата −5 р.д.'):
        return 'unresolved_calculation'
    if token in ('Имя', 'Name', 'reference', 'номер', 'number', 'телефон', 'phone',
                 'что требуется', 'документ', '…', 'страна',
                 'вариант 1 — усилить документы и подать повторно; вариант 2 — другой тип визы'):
        return 'text'
    raise ValueError('Unclassified source placeholder: '+token)


def build():
    path=ROOT/'knowledge/kg_entry/draft-v1.1/units.yaml'
    if hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!='729ca3a4151e0da3a7c9962019ad7bdcdcdc673504c0881143f1848fe19d81ec':
        raise ValueError('Source unit snapshot changed; re-review the extraction')
    units = load_document(path)
    templates = []
    for unit in units:
        if unit['kind'] != 'template':
            continue
        if unit['value'] is not None or unit['confirmation_status'] == 'confirmed':
            raise ValueError('This source extraction expects unapproved templates')
        text = unit['blocked_value']['source']
        fields = []
        for index, match in enumerate(SLOT.finditer(text), 1):
            token = match[1]
            fields.append(dict(id=f'p{index:02}', token=token, kind=slot_type(token),
                               choices=token.split('/') if slot_type(token) == 'choice' else [],
                               currency='USD' if token == 'сумма' and text[match.start()-1:match.start()] == '$' else None))
        templates.append({**{key: unit[key] for key in ('unit_id','title','page','section','source_ref','label','confirmation_status')},
                          'text':text, 'text_sha256':hashlib.sha256(text.encode()).hexdigest(), 'fields':fields})
    if {u['unit_id'] for u in templates} != {f'KG.TPL.A{i:02}' for i in range(1,14)}:
        raise ValueError('Expected every appendix A template')
    return dict(format='kg-message-template-draft/1',version='pdf-1.1-templates-1',
                source_sha256=SOURCE_SHA,publication_approved=False,templates=templates)


if __name__ == '__main__':
    payload = (json.dumps(build(),ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    path = ROOT/'knowledge/kg_entry/templates_v1_1/catalog.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(payload)
    print('Catalog SHA256:',hashlib.sha256(payload).hexdigest())
