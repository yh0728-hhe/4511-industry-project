"""Pure Common Crawl index planning. Capture pointers are never source proof.

No networking, storage, dependencies or proof-ledger writes at import or parse.
URL checks are syntactic: they cannot certify DNS, historical domain ownership,
readable capture bodies, publisher independence or the truth of page claims.
"""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit

_MAX_INT=2**63-1
_COLLECTION=re.compile(r'CC-MAIN-20[0-9]{2}-(?:0[1-9]|[1-4][0-9]|5[0-3])')
_DOMAIN=re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}')
_RESERVED=('local','localhost','internal','invalid','test','example','onion')


@dataclass(frozen=True)
class CapturePointer:
    url: str
    captured_at: datetime
    digest_sha1_base32: str
    filename: str
    offset: int
    length: int

    @property
    def data_url(self):return 'https://data.commoncrawl.org/'+self.filename
    @property
    def range_header(self):return f'bytes={self.offset}-{self.offset+self.length-1}'
    @property
    def source_admission_allowed(self):return False
    @property
    def requires_body_verification(self):return True


@dataclass(frozen=True)
class IndexScan:
    pointers: tuple[CapturePointer,...]
    raw_record_count: int
    rejected_counts: tuple[tuple[str,int],...]
    body_sha256: str

    @property
    def rejected_reason_counts(self):return dict(self.rejected_counts)
    @property
    def source_admission_allowed(self):return False


def _homepage(value):
    if (not isinstance(value,str) or not value or any(ord(c)<=32 or ord(c)>=127 for c in value)
            or any(c in value for c in ('%','\\','?','#'))):
        raise ValueError('EXACT_PUBLIC_HOMEPAGE_REQUIRED')
    try:
        part=urlsplit(value)
        host=part.hostname
        if (part.scheme not in ('http','https') or host is None or
            part.netloc!=host or len(host)>253 or _DOMAIN.fullmatch(host) is None or
            host.rsplit('.',1)[-1] in _RESERVED or part.path not in ('','/') or
            part.query or part.fragment):
            raise ValueError()
    except ValueError:raise ValueError('EXACT_PUBLIC_HOMEPAGE_REQUIRED') from None
    return part.scheme+'://'+host+'/'


def _unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('DUPLICATE_INDEX_JSON_KEY')
        value[key]=item
    return value


def _constant(_):raise ValueError('NONFINITE_INDEX_JSON')


def _uint(value):
    if (not isinstance(value,str) or not 1<=len(value)<=20 or
            re.fullmatch(r'[0-9]+',value) is None):raise ValueError('INVALID_RANGE')
    return int(value)


def _pointer(row,requested,as_of,collection,max_range_bytes):
    if row.get('status')!='200':raise ValueError('NON_200_CAPTURE')
    if row.get('mime')!='text/html':raise ValueError('NON_HTML_CAPTURE')
    try:canonical=_homepage(row.get('url'))
    except ValueError:raise ValueError('URL_MISMATCH') from None
    if canonical!=requested:raise ValueError('URL_MISMATCH')
    stamp=row.get('timestamp')
    if not isinstance(stamp,str) or re.fullmatch(r'[0-9]{14}',stamp) is None:
        raise ValueError('INVALID_TIMESTAMP')
    try:captured=datetime.strptime(stamp,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
    except ValueError:raise ValueError('INVALID_TIMESTAMP') from None
    if captured>as_of:raise ValueError('AFTER_CUTOFF')
    digest=row.get('digest')
    if not isinstance(digest,str) or re.fullmatch(r'[A-Z2-7]{32}',digest) is None:
        raise ValueError('INVALID_DIGEST')
    offset=_uint(row.get('offset'));length=_uint(row.get('length'))
    if not 0<=offset<=_MAX_INT or not 1<=length<=max_range_bytes or offset+length-1>_MAX_INT:
        raise ValueError('INVALID_RANGE')
    filename=row.get('filename')
    pattern=(r'crawl-data/'+re.escape(collection)+r'/segments/[0-9]+\.[0-9]+/warc/'
        r'CC-MAIN-[0-9]{14}-[0-9]{14}-[0-9]{5}\.warc\.gz')
    if not isinstance(filename,str) or re.fullmatch(pattern,filename) is None:
        raise ValueError('INVALID_ARCHIVE_FILENAME')
    return CapturePointer(row['url'],captured,digest,filename,offset,length)


def parse_commoncrawl_index(body,*,requested_url,as_of,collection,
        max_records=20,max_bytes=65536,max_range_bytes=262144):
    """Return bounded non-evidence pointers and rejection counts, never page text.

    Malformed JSON, duplicate keys, non-object rows, conflicting captures and
    size/count overflow fail the whole scan. Otherwise ineligible records are
    counted by reason. Empty or filtered results never prove archive absence.
    """
    requested=_homepage(requested_url)
    if not isinstance(as_of,datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('AWARE_CUTOFF_REQUIRED')
    if not isinstance(collection,str) or _COLLECTION.fullmatch(collection) is None:
        raise ValueError('EXPLICIT_COLLECTION_REQUIRED')
    for value,upper in ((max_records,100),(max_bytes,65536),(max_range_bytes,262144)):
        if type(value) is not int or not 1<=value<=upper:raise ValueError('STRICT_PARSE_BOUNDS_REQUIRED')
    if type(body) is not bytes or len(body)>max_bytes:raise ValueError('INDEX_BODY_TYPE_OR_SIZE')
    try:
        lines=[line for line in body.decode('utf-8').splitlines() if line.strip()]
        if len(lines)>max_records:raise ValueError('INDEX_RECORD_LIMIT')
        rows=[json.loads(line,object_pairs_hook=_unique,parse_constant=_constant) for line in lines]
    except (UnicodeDecodeError,RecursionError):raise ValueError('INVALID_INDEX_ENCODING_OR_DEPTH') from None
    if any(type(row) is not dict for row in rows):raise ValueError('INDEX_OBJECT_ROWS_REQUIRED')
    found={};rejected=Counter()
    for row in rows:
        try:pointer=_pointer(row,requested,as_of,collection,max_range_bytes)
        except ValueError as exc:rejected[str(exc)]+=1;continue
        key=(requested,pointer.captured_at)
        if key in found:
            if found[key]!=pointer:raise ValueError('CONFLICTING_CAPTURE_METADATA')
            rejected['DUPLICATE_CAPTURE']+=1;continue
        found[key]=pointer
    return IndexScan(tuple(sorted(found.values(),key=lambda p:(p.captured_at,p.url))),
        len(rows),tuple(sorted(rejected.items())),hashlib.sha256(body).hexdigest())
