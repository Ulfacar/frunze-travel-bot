"""Reproduce a complete, unapproved text/position archive of the supplied PDF.

Offline document tooling only. The original PDF, derived Markdown and executable
catalogs are never modified. Existing differing output is never overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path

PDF_SHA256 = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
PDF_NAME = 'Kyrgyzstan-visa-knowledge-base-v1.1.pdf'
PYMUPDF_VERSION = '1.27.2.3'
MUPDF_VERSION = '1.27.2'
PAGE_COUNT = 94
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'knowledge/kg_entry/source_v1_1/full-text-archive.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def extract(source):
    import fitz
    source = Path(source)
    if source.stat().st_size > 128*1024*1024:
        raise ValueError('source_size_limit')
    raw = source.read_bytes()
    if digest(raw) != PDF_SHA256:
        raise ValueError('source_hash_changed')
    if (fitz.VersionBind, fitz.VersionFitz) != (PYMUPDF_VERSION, MUPDF_VERSION):
        raise ValueError('extractor_version_changed')
    pages = []
    with fitz.open(stream=raw, filetype='pdf') as document:
        if document.needs_pass or document.page_count != PAGE_COUNT:
            raise ValueError('source_structure_changed')
        for number, page in enumerate(document, 1):
            blocks = [dict(order=i, number=int(block[5]), bbox=list(block[:4]), text=block[4],
                           text_sha256=digest(block[4].encode('utf-8')))
                for i, block in enumerate(page.get_text('blocks', sort=False,
                    flags=fitz.TEXTFLAGS_BLOCKS & ~fitz.TEXT_PRESERVE_IMAGES)) if block[6]==0]
            text = page.get_text('text', sort=False)
            if text != ''.join(block['text'] for block in blocks):
                raise ValueError('page_text_block_disagreement')
            payload = dict(page=number, rect=list(page.rect), rotation=page.rotation,
                text=text, text_sha256=digest(text.encode('utf-8')), blocks=blocks)
            pages.append({**payload, 'content_sha256':digest(encoded(payload))})
    content = dict(format='kg-full-pdf-text-archive/1', source_document=PDF_NAME, source_sha256=PDF_SHA256,
        extractor=dict(name='PyMuPDF', binding_version=PYMUPDF_VERSION, mupdf_version=MUPDF_VERSION,
                       order='original_pdf_text_block_order', coordinates='PDF_points_as_returned', sort=False),
        approval='unapproved_source_evidence', executable=False,
        limitations=['Text and text-block positions only; the original PDF remains the authoritative artifact.',
                     'Extraction does not approve legal currency, table interpretation or executable coverage.'],
        page_count=PAGE_COUNT, pages=pages)
    return {**content, 'content_sha256':digest(encoded(content))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args(argv)
    try:
        data = encoded(extract(args.source))
        if args.check:
            if not args.output.is_file() or args.output.read_bytes()!=data:
                raise ValueError('archive_missing_or_changed')
        elif args.output.exists():
            if args.output.read_bytes()!=data:
                raise ValueError('refusing_to_overwrite_changed_archive')
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open('xb') as stream:
                stream.write(data)
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(dict(result='PASS', mode='check' if args.check else 'create_or_identical',
        pages=PAGE_COUNT, sha256=digest(data), bytes=len(data))))


if __name__=='__main__':
    main()
