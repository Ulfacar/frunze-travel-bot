"""Offline lossless source extraction for the draft document-matrix review."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
PRODUCTS = dict(TS='TS — туристическая', B='B — деловая', RL='RL — туугандар',
                FF='FF — семья иностранца', S='S — учебная', EP='Единое разрешение',
                RES='Резидент-карта', L='L — выездная', REG='Регистрация')


def build():
    text = (ROOT/'docs/kb-visa-inbound-v1.1-derived.md').read_text(encoding='utf-8')
    sections = {}
    for number, pages in [('5.1',[35]),('5.2',[36,37,38]),('5.3',[38,39]),
                          ('5.4',[39,40]),('5.5',[40]),('11.4',[53,54])]:
        match = re.search(rf'^#{{1,2}} {re.escape(number)}\. .*?(?=^#{{1,2}} |\Z)', text, re.M|re.S)
        if not match: raise ValueError('source_section_missing:'+number)
        source = match.group().strip()
        # A block heading immediately follows 5.5 in this conversion.
        sections[number] = dict(text=source, pages=pages, sha256=hashlib.sha256(source.encode()).hexdigest())
    rows=[];page=None
    for line in sections['5.2']['text'].splitlines():
        marker = re.fullmatch(r'<!--TABLE pdf p\.(\d+)-->', line)
        if marker: page=int(marker[1])
        if not re.match(r'^\| \d',line): continue
        cells=[cell.strip() for cell in line.strip('|').split('|')]
        if len(cells)!=11 or page not in (36,37): raise ValueError('invalid_matrix_row')
        rows.append(dict(id=f'd{len(rows)+1:02}',number=cells[0],name=cells[1],page=page,
                         source_text=line,cells=dict(zip(PRODUCTS,cells[2:]))))
    if len(rows)!=23: raise ValueError('unexpected_matrix_size:'+str(len(rows)))
    return dict(format='kg-document-matrix-draft/1',version='pdf-1.1-documents-review-1',
                publication_approved=False,source_sha256=SOURCE_SHA,products=PRODUCTS,
                sections=sections,rows=rows)


if __name__=='__main__':
    data=build();payload=(json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    path=ROOT/'knowledge/kg_entry/documents_v1_1/catalog.json'
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
    print('Rows:',len(data['rows']),'products:',len(data['products']),'SHA256:',hashlib.sha256(payload).hexdigest())
