"""One bounded in-memory multipart file; no temp files or document parsing."""
from dataclasses import dataclass
import re

try:
    from python_multipart.multipart import MultipartParser, parse_options_header
except ImportError:  # The repository also supports the original package name.
    from multipart.multipart import MultipartParser, parse_options_header


class UploadFormInvalid(ValueError):
    pass


class UploadTooLarge(UploadFormInvalid):
    pass


@dataclass(frozen=True)
class ParsedUpload:
    fields: dict
    data: bytes
    filename: str
    media_type: str


async def parse_upload(request, *, max_file_bytes):
    content_type=request.headers.get('content-type','')
    if len(content_type)>256: raise UploadFormInvalid('invalid multipart header')
    media,options=parse_options_header(content_type)
    boundary=options.get(b'boundary',b'')
    if media!=b'multipart/form-data' or not 1<=len(boundary)<=70 or any(c<33 or c>126 for c in boundary):
        raise UploadFormInvalid('invalid multipart boundary')
    fields={}; data=bytearray(); part={}; file_info={}; ended=False; parts=0

    def begin():
        nonlocal parts
        parts+=1
        if parts>20: raise UploadTooLarge('too many parts')
        part.clear(); part.update(headers={},field=bytearray(),value=bytearray(),body=bytearray(),header_bytes=0)

    def header(which,chunk,start,end):
        part['header_bytes']+=end-start
        if part['header_bytes']>2048: raise UploadTooLarge('header too large')
        part[which].extend(chunk[start:end])

    def header_end():
        key=bytes(part['field']).lower()
        if key in part['headers'] or key not in (b'content-disposition',b'content-type'):
            raise UploadFormInvalid('unexpected header')
        part['headers'][key]=bytes(part['value'])
        part['field'].clear(); part['value'].clear()

    def headers_finished():
        # Do not let a generic header parser strip a Windows path or collapse
        # duplicate name/filename parameters before security validation.
        disposition=part['headers'].get(b'content-disposition',b'').strip()
        match=re.fullmatch(rb'form-data;\s*name="([A-Za-z0-9_]{1,64})"(?:;\s*filename="([^"\r\n]{0,1024})")?',disposition)
        if not match: raise UploadFormInvalid('invalid disposition')
        name=match[1].decode('ascii'); filename=match[2]
        part['name']=name; part['file']=filename is not None
        if part['file']:
            if name!='file' or file_info: raise UploadFormInvalid('one file required')
            try:
                file_info.update(filename=filename.decode('utf-8'),
                                 media_type=part['headers'].get(b'content-type',b'').decode('ascii'))
            except UnicodeError: raise UploadFormInvalid('invalid file header') from None
        elif name in fields or name=='file': raise UploadFormInvalid('duplicate field')

    def part_data(chunk,start,end):
        target=data if part['file'] else part['body']; limit=max_file_bytes if part['file'] else 256
        if len(target)+end-start>limit: raise UploadTooLarge('part too large')
        target.extend(chunk[start:end])

    def part_end():
        if not part['file']:
            try: fields[part['name']]=part['body'].decode('utf-8')
            except UnicodeError: raise UploadFormInvalid('invalid field encoding') from None

    def end():
        nonlocal ended
        ended=True

    parser=MultipartParser(boundary,{
        'on_part_begin':begin,'on_header_field':lambda *a:header('field',*a),
        'on_header_value':lambda *a:header('value',*a),'on_header_end':header_end,
        'on_headers_finished':headers_finished,'on_part_data':part_data,'on_part_end':part_end,'on_end':end})
    size=0
    try:
        async for chunk in request.stream():
            size+=len(chunk)
            if size>max_file_bytes+16384: raise UploadTooLarge('body too large')
            parser.write(chunk)
        parser.finalize()
    except UploadFormInvalid: raise
    except (ValueError,KeyError): raise UploadFormInvalid('invalid multipart') from None
    if not ended or not file_info: raise UploadFormInvalid('incomplete multipart')
    return ParsedUpload(fields,bytes(data),**file_info)
