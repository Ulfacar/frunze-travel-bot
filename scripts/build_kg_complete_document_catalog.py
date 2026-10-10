"""Offline source clauses for complete document definitions; no source approval.

The original matrix catalog is immutable. This builds a separate version with
explicit source scopes and conditional supplements. Operator applicability is
unknown by default; it is never inferred from the absence of a document.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.knowledge.document_checklist import checklist, load_document_catalog

PRODUCTS = {
    'TS':'Туристическая TS', 'B':'Деловая B', 'TR':'Транзитная TR', 'RL':'Туугандар RL',
    'FF':'Семья иностранца FF', 'S':'Учебная S', 'SW1':'Специальная рабочая SW1',
    'SW2':'Специальная рабочая SW2', 'DN':'DN', 'J':'J', 'M':'Мекен M', 'I':'Инвестиционная I',
    'R':'Религиозная R', 'T':'Водительская T', 'A':'A', 'EP':'Единое разрешение',
    'RES':'Резидент-карта', 'L':'Выездная L', 'REG':'Регистрация',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def plain(value):
    return re.sub(r'[*`]', '', value).strip()


def paragraphs(section):
    """Retain source paragraph, heading and physical page; skip table containers."""
    page = section['pages'][0]; heading = ''; ordinal = 0
    for block in re.split(r'\n\s*\n', section['text']):
        marker = re.search(r'<!--PDF:(\d+)-->|> PDF стр\. (\d+)', block)
        if marker:
            page = int(marker.group(1) or marker.group(2))
        block = re.sub(r'<!--.*?-->', '', block, flags=re.S).strip()
        if not block or block.startswith('>') or block.startswith('|'):
            continue
        if block.startswith('#'):
            heading = block.lstrip('# ').strip()
            continue
        ordinal += 1
        yield ordinal, heading, page, block


def _type_scope(heading, body):
    if heading.startswith('Регистрация'):
        return ['REG']
    if heading.startswith('SW1 / SW2'):
        if body.startswith('**SW1:'): return ['SW1']
        if body.startswith('**SW2 '): return ['SW2']
        return ['SW1','SW2']
    if heading.startswith('DN, J, M, I, R, T, A'):
        match = re.match(r'\*\*([A-Z]+):', body)
        if not match: raise ValueError('unclassified source product')
        return [match.group(1)]
    prefix = heading.split(' — ', 1)[0]
    if prefix not in PRODUCTS: raise ValueError('unclassified source heading: '+heading)
    return [prefix]


def extract_clauses(source):
    clauses = []
    def add(identifier, section, page, text, paragraph, products, kind, condition=None, marks=()):
        if text not in paragraph: raise ValueError('fragment lost source binding')
        clauses.append(dict(id=identifier, section=section, page=page, text=plain(text).strip(' ;'),
            source_fragment=text, source_paragraph=paragraph, paragraph_sha256=digest(paragraph),
            source_section_sha256=source['sections'][section]['sha256'], products=products,
            kind=kind, condition=condition, marks=list(marks)))

    section = source['sections']['5.1']
    table_rows = [line for line in section['text'].splitlines() if line.startswith('| ')][1:]
    for ordinal, line in enumerate(table_rows, 1):
        cells = [v.strip() for v in line.strip('|').split('|')]
        if len(cells) != 3: raise ValueError('general requirements table changed')
        name, body, reference = cells
        for part, fragment in enumerate(body.split(';'), 1):
            kind = 'conditional' if ordinal in (5,6,8) else 'required'
            marks = [mark for marker,mark in (('[ПРАКТИКА','practice'),('[ПРОВЕРИТЬ','verify'),('[РЕШЕНИЕ','decision'))
                     if marker in fragment or marker in reference]
            add(f'g{ordinal:02}_{part:02}', '5.1', 35, fragment, line, list(PRODUCTS), kind,
                'Применимость общего требования к выбранной процедуре' if kind == 'conditional' else None, marks)

    for ordinal, heading, page, paragraph in paragraphs(source['sections']['5.2']):
        if ordinal == 1: continue  # matrix symbol legend, retained in the immutable original catalog
        if ordinal != 2: raise ValueError('medical supplement changed')
        marker = 'Для резидент-карты по работе'
        boundary = paragraph.index(marker)
        add('med01', '5.2', page, paragraph[:boundary], paragraph, ['SW1','SW2','S','RL','FF','RES'],
            'conditional', 'Долгосрочная виза или резидент-карта на перечисленном основании')
        add('med02', '5.2', page, paragraph[boundary:], paragraph, ['RES'],
            'conditional', 'Резидент-карта по работе')

    for ordinal, heading, page, paragraph in paragraphs(source['sections']['5.3']):
        products = _type_scope(heading, paragraph)
        label = re.match(r'^\*\*([^*]+)\*\*\s*', paragraph)
        prefix = label.group(1) if label else ''
        body = paragraph[label.end():] if label else paragraph
        default = ('recommended' if prefix.startswith('Желательно') else
                   'conditional' if prefix.startswith(('В отдельных','Для ','Долгосрочно','Если ','SW2 (','Представитель','Студенты','Работники','Безвизовые')) else 'required')
        for part, fragment in enumerate(body.split(';'), 1):
            add(f't{ordinal:02}_{part:02}', '5.3', page, fragment, paragraph, products, default,
                plain(prefix).rstrip(':') if default == 'conditional' else None,
                ['practice'] if '[ПРАКТИКА]' in fragment else [])

    for ordinal, heading, page, paragraph in paragraphs(source['sections']['5.4']):
        if ordinal == 1: continue  # template navigation, not a document requirement
        add(f'letter{ordinal-1:02}', '5.4', page, paragraph, paragraph, list(PRODUCTS),
            'conditional', 'Письмо/ходатайство требуется и этот пункт применим к приглашающей стороне')

    for ordinal, heading, page, paragraph in paragraphs(source['sections']['5.5']):
        add(f'quality{ordinal:02}', '5.5', page, paragraph, paragraph, list(PRODUCTS),
            'policy' if ordinal == 4 else 'practice',
            'Утверждённая политика обработки персональных данных' if ordinal == 4 else None,
            ['decision'] if ordinal == 4 else ['practice'])

    for ordinal, heading, page, paragraph in paragraphs(source['sections']['11.4']):
        if ordinal == 11: continue  # resident inheritance heading; rules1-10 also scoped to work-based RES
        products = ['EP','RES'] if ordinal <= 10 or ordinal == 17 else ['RES']
        add(f'work{ordinal:02}', '11.4', page, paragraph, paragraph, products, 'conditional',
            'ЕР или резидент-карта после ЕР; применимость к работодателю/ИП и данным ЕСУВМ')
    return clauses


def annotate(clauses):
    """Explicit source conditions, not a citizenship/risk classifier or legal approval."""
    rows = {row['id']:deepcopy(row) for row in clauses}
    if len(rows) != 139: raise ValueError('source clauses changed; review annotations')
    facts = {}
    def fact(name, label, expected=True, choices=None):
        schema = dict(label=label, values=choices if choices is not None else [False,True])
        if name in facts and facts[name] != schema: raise ValueError('conflicting fact schema')
        facts[name] = schema
        return {'eq':[name,expected]}
    def all_of(*values): return {'all':list(values)}
    def any_of(*values): return {'any':list(values)}
    def product(*values): return {'product':list(values)}
    def set_when(ids, expression):
        for identifier in ids.split(): rows[identifier]['when'] = expression
    def split(identifier, markers):
        row = rows.pop(identifier); text = row['source_fragment']; positions = [0]
        positions += [text.index(marker) for marker in markers]; positions += [len(text)]
        for i,(start,end) in enumerate(zip(positions,positions[1:]),1):
            piece = deepcopy(row); piece.update(id=identifier+f'_{i}', source_fragment=text[start:end], text=plain(text[start:end]).strip(' ;'))
            rows[piece['id']] = piece
    # Separate normative photo/form requirements from recommendations and paper/minor conditions.
    split('g03_01', ['Для бумажной подачи', 'Рекомендуем:'])
    rows['g03_01_1']['marks'] = []; rows['g03_01_2']['marks'] = []
    rows['g03_01_3'].update(kind='recommended', marks=['practice'])
    split('g04_01', ['Бумажная анкета'])
    split('work03', ['официальный адрес юрлица'])
    split('t31_01', ['ходатайство вуза'])
    for row in rows.values():
        row['when'] = True
    paper = fact('paper_submission', 'Бумажная подача')
    set_when('g03_01_2 g04_01_2', paper)
    set_when('g04_01_1', fact('paper_submission', 'Бумажная подача', False))
    set_when('g04_02', all_of(paper, fact('minor', 'Заявитель младше 18 лет')))
    foreign_language = fact('foreign_language_documents', 'Документы не на кыргызском/русском языке')
    set_when('g05_01', fact('foreign_language_documents', 'Документы не на кыргызском/русском языке', False))
    set_when('g05_02', foreign_language)
    set_when('g06_01 work17', fact('foreign_public_documents', 'Есть иностранные документы, требующие проверки перевода/легализации'))
    invitation = fact('invitation_required', 'В составе пакета нужно письмо/ходатайство приглашающей стороны')
    set_when('g08_01 '+' '.join(f'letter{i:02}' for i in range(1,11)), invitation)
    long_term = fact('long_term', 'Долгосрочная виза')
    basis_values = ['work','SW1','SW2','S','RL','FF']
    resident_medical = any_of(*(fact('resident_basis', 'Основание резидент-карты', value, basis_values)
                               for value in ('SW1','SW2','S','RL','FF')))
    medical = any_of(all_of(product('SW1','SW2','S','RL','FF'),long_term), all_of(product('RES'),resident_medical))
    set_when('med01', medical)
    # Work-based RES inherits §11.4; a separate false checkbox cannot suppress it.
    resident_after_ep = fact('resident_basis', 'Основание резидент-карты', 'work', basis_values)
    set_when('med02', resident_after_ep)
    set_when('t02_03', fact('high_risk_country', 'Риск по гражданству отдельно оценён специалистом'))
    set_when('t03_01', fact('simplified_ts', 'Проверяется упрощённая TS по иностранному ВНЖ/резидент-карте'))
    set_when('t03_02', fact('gambling', 'Основание связано с игорным заведением'))
    set_when('t05_01', fact('medical_purpose', 'Деловая виза для лечения'))
    set_when('t06_01', fact('international_representation', 'Приглашает международная организация/дипмиссия'))
    set_when('t10_01 t21_04', fact('in_kg', 'Заявитель находится в Кыргызстане'))
    set_when('t10_02', fact('refugee_entry_exit', 'Беженец оформляет выездную-въездную визу'))
    set_when('t10_03 t12_02 t14_01 t18_01', long_term)
    for identifier, code in (('t10_03','RL'),('t12_02','FF'),('t14_01','S')):
        rows[identifier]['products'].append('RES')
        rows[identifier]['when'] = any_of(all_of(product(code),long_term),
            all_of(product('RES'),fact('resident_basis','Основание резидент-карты',code,basis_values)))
    set_when('t12_01', fact('employer_invites', 'Приглашает юрлицо — работодатель'))
    tax_missing = fact('tax_in_esuvm', 'Налоговые сведения доступны в ЕСУВМ', False)
    set_when('t13_05', tax_missing)
    sw2_values = ['journalist','volunteer','fund']
    journalist = fact('sw2_category','Основание SW2','journalist',sw2_values)
    volunteer = fact('sw2_category','Основание SW2','volunteer',sw2_values)
    fund = fact('sw2_category','Основание SW2','fund',sw2_values)
    set_when('t16_01 t16_03', journalist)
    set_when('t16_02', all_of(journalist,long_term))
    set_when('t17_01 t17_02 t17_03 t17_04', any_of(volunteer,fund))
    set_when('t17_05', fund)
    extension = fact('extension','Продление')
    set_when('t20_03', extension)
    set_when('t27_01', fact('extradition','Есть процедура экстрадиции'))
    set_when('t27_02', fact('expulsion','Есть решение суда о выдворении'))
    set_when('t29_01', fact('host_is_owner','Принимающая сторона — собственник жилья',False))
    set_when('t30_01', fact('representative','Документы подаёт представитель'))
    student = fact('registration_student','Регистрация на основании учёбы')
    set_when('t31_01_1', all_of(student,fact('visa_free','Безвизовое пребывание')))
    set_when('t31_01_2', student)
    worker = fact('registration_worker','Регистрация на основании работы')
    eaeu = fact('eaeu_worker','Работник — гражданин ЕАЭС')
    set_when('t32_01', all_of(worker, fact('eaeu_worker','Работник — гражданин ЕАЭС',False)))
    set_when('t32_02', all_of(worker,eaeu))
    set_when('t32_03', all_of(eaeu,fact('worker_family','Член семьи работника')))
    set_when('t33_01', all_of(extension,
        any_of(fact('visa_free','Безвизовое пребывание'),fact('stateless','Лицо без гражданства')),
        fact('insurance_in_esuvm','Страховой полис доступен в ЕСУВМ',False)))
    work = any_of(product('EP'),all_of(product('RES'),resident_after_ep))
    for identifier in rows:
        if identifier.startswith('work') and identifier!='work17': rows[identifier]['when'] = work
    entity = fact('employer_is_entity','Работодатель — юридическое лицо')
    set_when('work03_2 work05 work10', all_of(work,entity))
    entrepreneur = fact('foreign_entrepreneur','Заявитель — иностранный ИП')
    set_when('work07 work13', all_of(work,entrepreneur))
    set_when('work06', all_of(work,tax_missing))
    set_when('work08', all_of(work,fact('licensed_activity','Деятельность подлежит лицензированию')))
    for row in rows.values():
        # Conditional labels are explanatory; a known scope may make an obligation mandatory.
        if row['when'] is not True and row['kind']=='required': row['kind']='conditional'
        if row['kind']=='policy': row['when']=True  # cannot turn off a server-owned policy with form facts
    return list(rows.values()), facts


def build():
    catalog = load_document_catalog(); source = catalog.document()
    clauses, facts = annotate(extract_clauses(source))
    return dict(format='kg-complete-document-definitions/1', version='pdf-1.1-complete-documents-review-1',
        source_sha256=source['source_sha256'], matrix_catalog_sha256=catalog.digest,
        publication_approved=False, products=PRODUCTS, clauses=clauses, facts=facts,
        matrix={product:checklist(catalog, product) for product in source['products']},
        reference_sections=source['sections'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'runs/e6-08-source/complete-clauses-draft.json')
    args = parser.parse_args()
    document = build(); args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n', 'utf-8')
    print(f"{len(document['clauses'])} source clauses / {len(PRODUCTS)} products; UNAPPROVED draft: {args.output.name}")


if __name__ == '__main__':
    main()
