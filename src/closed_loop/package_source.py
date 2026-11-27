"""Offline verification of frozen wheel documentation; never installs package code.

Caller must supply file metadata independently retrieved from PyPI over HTTPS.
This function cannot authenticate a caller-supplied mapping or certify historic
ownership of a domain. Model assertions must never populate this trust input.
Only embedded README text is evidence, not current project metadata or traction.
"""
import hashlib
import io
import re
import stat
import zipfile
from datetime import datetime
from email.parser import Parser
from urllib.parse import urlsplit

from .contracts import digest, aware
from .guards import SourceCandidate, VerifiedRecord

MAX_WHEEL_BYTES=1_000_000
MAX_TOTAL_BYTES=10_000_000
MAX_METADATA_BYTES=128_000


def _fail():
    raise ValueError('INVALID_HISTORICAL_PACKAGE_SOURCE')


def _normalize(name):
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*',name):_fail()
    return re.sub(r'[-_.]+','-',name).lower()


def verify_wheel_source(wheel_bytes,file_metadata,expected_package,request):
    """Return candidate/record only after bounded byte, date and identity checks.

    `file_metadata` is a trusted PyPI file record, not an LLM output. Its upload
    timestamp bounds availability of the digest-bound artifact, not company age.
    The result supports package documentation only. Caller still uses gateway.
    """
    try:
        return _verify(wheel_bytes,file_metadata,expected_package,request)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,
            zipfile.BadZipFile,RuntimeError,NotImplementedError,OSError):
        raise ValueError('INVALID_HISTORICAL_PACKAGE_SOURCE') from None


def _verify(raw,meta,expected,request):
    if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_WHEEL_BYTES:_fail()
    if not isinstance(meta,dict):_fail()
    if type(meta.get('size')) is not int or meta['size']!=len(raw):_fail()
    if meta.get('yanked') is not False or meta.get('packagetype')!='bdist_wheel':_fail()
    filename=meta['filename']
    if not isinstance(filename,str) or not re.fullmatch(r'[A-Za-z0-9_.+-]+\.whl',filename):_fail()
    parts=filename[:-4].split('-')
    if len(parts) not in (5,6) or _normalize(parts[0])!=_normalize(expected):_fail()
    checksum=meta['digests']['sha256']
    if not isinstance(checksum,str) or not re.fullmatch('[a-fA-F0-9]{64}',checksum):_fail()
    checksum=checksum.lower()
    if hashlib.sha256(raw).hexdigest()!=checksum:_fail()
    url=meta['url'];parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.netloc!='files.pythonhosted.org' or
        parsed.query or parsed.fragment or not parsed.path.startswith('/packages/') or
        '%' in parsed.path or '\\' in parsed.path or
        any(p in ('.','..','') for p in parsed.path.split('/')[1:]) or
        parsed.path.rsplit('/',1)[-1]!=filename):_fail()
    stamp=aware(datetime.fromisoformat(meta['upload_time_iso_8601'].replace('Z','+00:00')))
    if stamp>aware(request.as_of):_fail()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries=archive.infolist()
        if not entries or len(entries)>2000 or len({i.filename for i in entries})!=len(entries):_fail()
        if sum(i.file_size for i in entries)>MAX_TOTAL_BYTES:_fail()
        selected=[]
        for entry in entries:
            path=entry.filename
            mode=entry.external_attr>>16
            if (path.startswith('/') or '\\' in path or ':' in path or
                any(p in ('.','..') for p in path.split('/')) or
                entry.flag_bits&1 or stat.S_ISLNK(mode) or
                entry.file_size>200*max(entry.compress_size,1)):_fail()
            if path.endswith('.dist-info/METADATA'):
                if path.count('/')!=1 or entry.file_size>MAX_METADATA_BYTES:_fail()
                selected.append(entry)
        if len(selected)!=1:_fail()
        member=selected[0].filename
        if member.split('/')[0]!=parts[0]+'-'+parts[1]+'.dist-info':_fail()
        text=archive.read(selected[0]).decode('utf-8')
    headers=Parser().parsestr(text)
    if len(headers.get_all('Name',[]))!=1 or len(headers.get_all('Version',[]))!=1:_fail()
    if _normalize(headers['Name'])!=_normalize(expected) or headers['Version']!=parts[1]:_fail()
    body=headers.get_payload()
    if not isinstance(body,str) or not body.strip():_fail()
    domain=request.company.domain.removeprefix('www.')
    identity=False
    for link in re.findall(r'https://[^\s<>\"\)\]]+',body):
        target=urlsplit(link)
        if (target.hostname and target.hostname.lower().removeprefix('www.')==domain and
            target.username is None and target.password is None and target.port in (None,443)):
            identity=True
    if not identity:_fail()
    source_id='pypi-wheel:'+digest(checksum+'|'+member+'|'+request.company.company_id)
    candidate=SourceCandidate(source_id,url,request.company.company_id,'package-documentation',body)
    record=VerifiedRecord(source_id,url,request.company.company_id,candidate.topic,digest(body),
        stamp,'VERIFIED_ORIGINAL_PUBLICATION',True)
    return candidate,record
