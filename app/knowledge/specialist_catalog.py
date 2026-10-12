"""Pinned clause evidence; catalogue membership never grants approval."""
import hashlib
import json
from pathlib import Path

PATH=Path(__file__).resolve().parents[2]/'knowledge/kg_entry/specialist_catalog_v1.json'
CATALOG_SHA256='4d6f964df3052dd1f70614b76913a6975a99fb2617e728e622852acafd2ac28e'
FORMAT='kg-specialist-source-catalog/1'


def load():
    raw=PATH.read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(raw).hexdigest()!=CATALOG_SHA256:raise ValueError('specialist_source_catalog_changed')
    value=json.loads(raw)
    if value['format']!=FORMAT or value['approval']!='unapproved_source_evidence':
        raise ValueError('invalid_specialist_source_catalog')
    return value


def capability(identifier):
    values=[v for v in load()['capabilities'] if v['id']==identifier]
    if len(values)!=1:raise ValueError('unsupported_specialist_capability')
    return values[0]


def source_pin(identifier):
    document=load();item=capability(identifier)
    return dict(catalog_sha256=CATALOG_SHA256,source_sha256=document['source_sha256'],
        archive_sha256=document['archive_sha256'],capability=item,
        sections=[s for s in document['sections'] if s['section'] in item['sections']])
