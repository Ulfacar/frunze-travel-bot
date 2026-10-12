"""Offline capture must preserve all pages and refuse drift or destructive output."""
import json

import fitz
import pytest

from scripts import build_kg_full_source_archive as archive


@pytest.fixture
def source(tmp_path, monkeypatch):
    path=tmp_path/'synthetic.pdf'
    with fitz.open() as document:
        document.new_page().insert_text((72,72), 'Synthetic cover')
        document.new_page(width=320, height=500).insert_text((20,60), 'Left\nsecond line')
        document[1].insert_text((180,60), 'Right column')
        document.new_page()  # An empty source page is still evidence, not omitted.
        document.save(path)
    monkeypatch.setattr(archive,'PDF_SHA256',archive.digest(path.read_bytes()))
    monkeypatch.setattr(archive,'PAGE_COUNT',3)
    return path


def test_cover_multicolumn_geometry_and_blank_page_are_preserved(source):
    first=archive.extract(source)
    assert archive.encoded(first)==archive.encoded(archive.extract(source))
    assert [p['page'] for p in first['pages']]==[1,2,3]
    assert first['pages'][0]['text']=='Synthetic cover\n'
    middle=first['pages'][1]
    assert middle['rect']==[0,0,320,500]
    assert len(middle['blocks'])==2
    assert middle['blocks'][0]['bbox'][0] < middle['blocks'][1]['bbox'][0]
    assert 'Left\nsecond line\nRight column\n'==middle['text']
    assert first['pages'][2]['blocks']==[] and first['pages'][2]['text']==''
    assert first['approval']=='unapproved_source_evidence' and first['executable'] is False


def test_changed_pdf_and_extractor_fail_closed(source, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(archive,'PDF_SHA256','0'*64)
        with pytest.raises(ValueError,match='source_hash_changed'): archive.extract(source)
    monkeypatch.setattr(fitz,'VersionBind','unapproved-extractor')
    with pytest.raises(ValueError,match='extractor_version_changed'): archive.extract(source)


def test_existing_output_is_checked_and_never_overwritten(source,tmp_path):
    output=tmp_path/'archive.json'
    args=['--source',str(source),'--output',str(output)]
    archive.main(args)
    original=output.read_bytes()
    archive.main(args+['--check'])
    archive.main(args)
    assert output.read_bytes()==original
    output.write_text('UNRELATED CONTENT','utf-8')
    with pytest.raises(SystemExit,match='refusing_to_overwrite_changed_archive'): archive.main(args)
    with pytest.raises(SystemExit,match='archive_missing_or_changed'): archive.main(args+['--check'])
    assert output.read_text('utf-8')=='UNRELATED CONTENT'
