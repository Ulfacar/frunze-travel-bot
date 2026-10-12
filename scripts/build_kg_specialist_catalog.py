"""Index supplied source clauses, without approving them or enabling a service."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SOURCE='141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
ARCHIVE='bca8256562d0fe4cdb37c096fff030b58b7f5499801b08cd8355214452dcb62f'
SECTIONS={
 '2.1':[19], '2.2':[20,21,22], '2.3':[22], '2.4':[22], '2.5':[23], '4.1':[30],
 '4.3':[30,31,32], '19.1':[79,80], '19.2':[81], '19.3':[81], '19.4':[81], '19.5':[81],
 '19.6':[82], '19.7':[82], '19.8':[82], '19.9':[82,83], '19.10':[83],
 '19.11':[83,84], '19.12':[84], '19.13':[84], '19.14':[84], 'B.8':[89,90],
}


def encoded(value):return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def digest(value):return hashlib.sha256(value).hexdigest()


def build():
    archive=json.loads((ROOT/'knowledge/kg_entry/source_v1_1/full-text-archive.json').read_text('utf-8'))
    content={k:v for k,v in archive.items() if k!='content_sha256'}
    if archive['source_sha256']!=SOURCE or archive['content_sha256']!=ARCHIVE or digest(encoded(content))!=ARCHIVE:
        raise ValueError('original source archive changed')
    pages={p['page']:p for p in archive['pages']}
    if set(pages)!=set(range(1,95)):raise ValueError('incomplete source archive')
    indexed=[]
    for section,numbers in SECTIONS.items():
        refs=[]
        for number in numbers:
            page=pages[number];body={k:v for k,v in page.items() if k!='content_sha256'}
            if digest(encoded(body))!=page['content_sha256'] or digest(page['text'].encode())!=page['text_sha256']:
                raise ValueError('source page changed')
            blocks=[]
            for block in page['blocks']:
                if digest(block['text'].encode())!=block['text_sha256']:raise ValueError('source block changed')
                blocks.append(dict(order=block['order'],number=block['number'],text_sha256=block['text_sha256']))
            refs.append(dict(page=number,content_sha256=page['content_sha256'],text_sha256=page['text_sha256'],blocks=blocks))
        indexed.append(dict(section=section,pages=refs))
    # These YAML files intentionally use the JSON subset. Only applicability is
    # indexed; blocked outcomes remain blocked and no review metadata is changed.
    units=json.loads((ROOT/'knowledge/kg_entry/draft-v1.1/units.yaml').read_text('utf-8'))
    conditions=json.loads((ROOT/'knowledge/kg_entry/conditions_v1_1/catalog.json').read_text('utf-8'))
    if conditions['source_hash']!=SOURCE:raise ValueError('condition source changed')
    conditional={r['unit_id']:r for r in conditions['rules']}
    regimes=[]
    for unit in units:
        if unit['kind'] not in ('visa_free_regime','visa_required_regime','special_regime'):continue
        uid=unit['unit_id']
        if uid in conditional:shape=dict(condition=conditional[uid])
        elif uid=='KG.VR.GENERAL':shape=dict(general=unit['value'])
        elif isinstance((unit['value'] or {}).get('countries'),list):
            shape=dict(countries=sorted(unit['value']['countries']))
        else:shape=dict(country=unit['blocked_value']['country_iso3'])
        regimes.append(dict(unit_id=uid,kind=unit['kind'],applicability=shape))
    if len(regimes)!=18:raise ValueError('regime census changed')
    return dict(format='kg-specialist-source-catalog/1',source_sha256=SOURCE,archive_sha256=ARCHIVE,
        approval='unapproved_source_evidence',sections=indexed,
        capabilities=[dict(id='B_MEETING_ABROAD_SINGLE',product='B',procedure='visa',mode='new',
            sections=['2.1','2.2','2.3','2.4','2.5','4.1','4.3','19.1','19.3','B.8'],
            scope='IND_ordinary_adult_abroad_single_business_no_foreign_documents',
            regime_applicability=regimes,current_source_units=['KG.VR.GENERAL'],
            maximum_planned_days=30,meaning='recorded_specialist_internal_plan',
            automatic_eligibility=False,automatic_delivery=False)])


if __name__=='__main__':
    path=ROOT/'knowledge/kg_entry/specialist_catalog_v1.json';data=encoded(build())
    if path.exists() and path.read_bytes()!=data:raise SystemExit('refusing to overwrite a changed catalog')
    if not path.exists():path.write_bytes(data)
    print(json.dumps(dict(path=str(path.relative_to(ROOT)),sha256=digest(data),approved=False)))
