import asyncio

import pytest

from app.admin.kg_quarantine_multipart import parse_upload, UploadFormInvalid, UploadTooLarge


def multipart(parts, *, closed=True):
    body=b''
    for headers,data in parts:
        body+=b'--synthetic\r\n'+headers+b'\r\n\r\n'+data+b'\r\n'
    return body+(b'--synthetic--\r\n' if closed else b'')


FILE=b'Content-Disposition: form-data; name="file"; filename="scan.pdf"\r\nContent-Type: application/pdf'
PDF=b'%PDF-1.7\nsynthetic only\n%%EOF\n'


def parse(body, *, step=4096, limit=1024, content_type='multipart/form-data; boundary=synthetic'):
    class Request:
        headers={'content-type':content_type}
        async def stream(self):
            for offset in range(0,len(body),step): yield body[offset:offset+step]
    return asyncio.run(parse_upload(Request(),max_file_bytes=limit))


@pytest.mark.parametrize('step',[1,3,7,4096])
def test_stream_boundaries_preserve_exact_bytes_and_fields(step):
    body=multipart([(b'Content-Disposition: form-data; name="_key"',b'abc'),(FILE,PDF)])
    result=parse(body,step=step)
    assert result.fields=={'_key':'abc'} and result.data==PDF
    assert result.filename=='scan.pdf' and result.media_type=='application/pdf'


@pytest.mark.parametrize('body',[
    multipart([(FILE,PDF)],closed=False),
    multipart([(FILE,PDF),(FILE,PDF)]),
    multipart([(b'Content-Disposition: form-data; name="x"',b'a'),(b'Content-Disposition: form-data; name="x"',b'b'),(FILE,PDF)]),
    multipart([(FILE+b'\r\nContent-Type: image/jpeg',PDF)]),
    multipart([(FILE.replace(b'name="file"',b'name="x"; name="file"'),PDF)]),
    multipart([(FILE.replace(b'filename="scan.pdf"',b'filename="scan.pdf"; filename="other.pdf"'),PDF)]),
    multipart([(b'Content-Disposition: form-data; name="x"',b'a')]),
])
def test_incomplete_ambiguous_or_duplicate_multipart_is_rejected(body):
    with pytest.raises(UploadFormInvalid): parse(body,step=3)


@pytest.mark.parametrize('body',[
    multipart([(FILE,PDF+b'x'*1024)]),
    multipart([(b'Content-Disposition: form-data; name="x"',b'x'*257),(FILE,PDF)]),
    multipart([(FILE+b'\r\nX-Overflow: '+b'x'*2049,PDF)]),
    multipart([(f'Content-Disposition: form-data; name="x{i}"'.encode(),b'a') for i in range(21)]+[(FILE,PDF)]),
    b'x'*18000,
])
def test_file_fields_headers_parts_and_whole_body_are_bounded(body):
    with pytest.raises(UploadFormInvalid): parse(body)


def test_parser_preserves_unsafe_path_for_later_rejection():
    result=parse(multipart([(FILE.replace(b'scan.pdf',b'C:\\fakepath\\scan.pdf'),PDF)]))
    assert result.filename=='C:\\fakepath\\scan.pdf'


@pytest.mark.parametrize('header',['application/json','multipart/form-data','multipart/form-data; boundary='+('a'*71)])
def test_invalid_content_type_and_boundary(header):
    with pytest.raises(UploadFormInvalid): parse(b'',content_type=header)
