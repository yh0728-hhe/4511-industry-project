"""Offline strict-subset WARC response verification, not a live source provider.

Trusted caller must independently acquire the index and exact range via HTTPS.
This module cannot authenticate a caller-supplied object or certify domain
ownership, publisher independence or claim truth. It never fetches, registers
proof in a ledger, changes defaults, installs code or invokes a model.
Only single gzip-member, unsegmented, non-chunked UTF8 HTML responses are supported.
"""
import base64
from datetime import datetime, timezone
import hashlib
import re
from urllib.parse import urlsplit
import zlib

from .archive_transport import HTTPResponse, visible_text
from .archived_publisher import _BindingParser
from .commoncrawl_index import CapturePointer, parse_commoncrawl_index
from .contracts import digest
from .guards import SourceCandidate, VerifiedRecord
import json

_ERROR='INVALID_COMMONCRAWL_RECORD'


def _sha1(raw):return base64.b32encode(hashlib.sha1(raw).digest()).decode('ascii')


def _headers(raw,limit):
    if len(raw)>limit:raise ValueError(_ERROR)
    lines=raw.decode('ascii').split('\r\n');fields={}
    for line in lines[1:]:
        if not line or ':' not in line:raise ValueError(_ERROR)
        key,value=line.split(':',1)
        if re.fullmatch(r'[A-Za-z0-9-]+',key) is None:raise ValueError(_ERROR)
        value=value.strip()
        if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError(_ERROR)
        fields.setdefault(key.lower(),[]).append(value)
    if any(ord(c)<32 or ord(c)==127 for c in lines[0]):raise ValueError(_ERROR)
    return lines[0],fields


def _one(fields,name,required=True):
    values=fields.get(name.lower(),[])
    if len(values)>1 or (required and len(values)!=1):raise ValueError(_ERROR)
    return values[0] if values else None


def _number(value):
    if not isinstance(value,str) or not 1<=len(value)<=20 or re.fullmatch(r'[0-9]+',value) is None:
        raise ValueError(_ERROR)
    return int(value)


def verify_commoncrawl_record(pointer,response,*,request,collection,
        max_decompressed_bytes=262144,max_text_chars=6000):
    """Return candidate, trusted record, and metadata receipt only after checks.

    SHA1s check consistency with CDX/WARC digests, not collision-resistant
    authentication. SHA256s also identify the compressed record and HTML bytes.
    The candidate URL is the original page locator, NOT newly fetched live text;
    its archive range location must be retained from the returned receipt.
    No real Common Crawl body has yet been validated by this project.
    """
    try:
        return _verify(pointer,response,request,collection,max_decompressed_bytes,max_text_chars)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,UnicodeError,zlib.error):
        raise ValueError(_ERROR) from None


def _verify(pointer,response,request,collection,max_decoded,max_text):
    for value,upper in ((max_decoded,1048576),(max_text,6000)):
        if type(value) is not int or not 1<=value<=upper:raise ValueError(_ERROR)
    if type(pointer) is not CapturePointer or type(response) is not HTTPResponse:raise ValueError(_ERROR)
    if (not isinstance(pointer.captured_at,datetime) or pointer.captured_at.tzinfo is None or
            pointer.captured_at.utcoffset() is None or pointer.captured_at.microsecond!=0):raise ValueError(_ERROR)
    # Revalidate the untrusted pointer; constructing its dataclass is not proof.
    row=dict(url=pointer.url,timestamp=pointer.captured_at.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S'),
        digest=pointer.digest_sha1_base32,offset=str(pointer.offset),length=str(pointer.length),
        filename=pointer.filename,status='200',mime='text/html')
    if type(pointer.offset) is not int or type(pointer.length) is not int:raise ValueError(_ERROR)
    parsed=parse_commoncrawl_index(json.dumps(row).encode(),requested_url=pointer.url,
        as_of=request.as_of,collection=collection,max_range_bytes=262144)
    if len(parsed.pointers)!=1 or parsed.pointers[0]!=pointer:raise ValueError(_ERROR)
    host=urlsplit(pointer.url).hostname.removeprefix('www.')
    if host!=request.company.domain.removeprefix('www.'):raise ValueError(_ERROR)
    if type(response.status) is not int or response.status!=206 or response.url!=pointer.data_url:
        raise ValueError(_ERROR)
    if type(response.body) is not bytes or len(response.body)!=pointer.length:raise ValueError(_ERROR)
    if type(response.headers) is not dict or len(response.headers)>100:raise ValueError(_ERROR)
    headers={}
    for key,value in response.headers.items():
        if not isinstance(key,str) or not isinstance(value,str) or key.lower() in headers:raise ValueError(_ERROR)
        headers[key.lower()]=value
    if sum(len(k)+len(v) for k,v in headers.items())>65536:raise ValueError(_ERROR)
    if headers.get('content-encoding','identity').lower()!='identity':raise ValueError(_ERROR)
    if _number(headers.get('content-length'))!=len(response.body):raise ValueError(_ERROR)
    match=re.fullmatch(r'bytes ([0-9]+)-([0-9]+)/([0-9]+)',headers.get('content-range',''))
    if match is None:raise ValueError(_ERROR)
    start,end,total=map(int,match.groups())
    if start!=pointer.offset or end!=start+pointer.length-1 or total<=end:raise ValueError(_ERROR)
    decoder=zlib.decompressobj(31)
    raw=decoder.decompress(response.body,max_decoded+1)
    if len(raw)>max_decoded or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError(_ERROR)
    head,tail=raw.split(b'\r\n\r\n',1)
    version,warc=_headers(head,16384)
    if version not in ('WARC/1.0','WARC/1.1') or _one(warc,'WARC-Type')!='response':raise ValueError(_ERROR)
    if any(name.startswith('warc-segment-') or name=='warc-truncated' for name in warc):raise ValueError(_ERROR)
    if _one(warc,'Content-Type').replace(' ','').lower()!='application/http;msgtype=response':raise ValueError(_ERROR)
    size=_number(_one(warc,'Content-Length'))
    if len(tail)!=size+4 or tail[-4:]!=b'\r\n\r\n':raise ValueError(_ERROR)
    block=tail[:size]
    if _one(warc,'WARC-Target-URI')!=pointer.url:raise ValueError(_ERROR)
    stamp=datetime.fromisoformat(_one(warc,'WARC-Date').replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError(_ERROR)
    stamp=stamp.astimezone(timezone.utc)
    if stamp.replace(microsecond=0)!=pointer.captured_at or stamp>request.as_of:raise ValueError(_ERROR)
    record_id=_one(warc,'WARC-Record-ID')
    if re.fullmatch(r'<urn:uuid:[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}>',record_id) is None:
        raise ValueError(_ERROR)
    if _one(warc,'WARC-Block-Digest')!='sha1:'+_sha1(block):raise ValueError(_ERROR)
    http_head,payload=block.split(b'\r\n\r\n',1)
    status,http=_headers(http_head,32768)
    if re.fullmatch(r'HTTP/1\.[01] 200(?: [^\r\n]*)?',status) is None:raise ValueError(_ERROR)
    if _one(http,'Transfer-Encoding',False) is not None:raise ValueError(_ERROR)
    if (_one(http,'Content-Encoding',False) or 'identity').lower()!='identity':raise ValueError(_ERROR)
    content_type=_one(http,'Content-Type').lower().replace(' ','')
    if content_type not in ('text/html','text/html;charset=utf-8','text/html;charset=us-ascii'):
        raise ValueError(_ERROR)
    declared=_one(http,'Content-Length',False)
    if declared is not None and _number(declared)!=len(payload):raise ValueError(_ERROR)
    payload_digest=_sha1(payload)
    if payload_digest!=pointer.digest_sha1_base32 or _one(warc,'WARC-Payload-Digest')!='sha1:'+payload_digest:
        raise ValueError(_ERROR)
    # Static HTML only. No JS, CSS computation, outbound links or current pages.
    text=visible_text(payload)
    if not 40<=len(text)<=max_text:raise ValueError(_ERROR)
    parser=_BindingParser();parser.feed(payload.decode('utf-8'))
    name=' '.join(request.company.name.lower().split())
    headline=' '.join(' '.join(parser.headline_parts).lower().split())
    if not 1<=len(name)<=200 or re.search(r'(?<![a-z0-9])'+re.escape(name)+r'(?![a-z0-9])',headline) is None:
        raise ValueError(_ERROR)
    compressed_sha=hashlib.sha256(response.body).hexdigest()
    source_id='commoncrawl-warc:'+digest(collection+'|'+pointer.filename+'|'+str(pointer.offset)+'|'+compressed_sha)
    candidate=SourceCandidate(source_id,pointer.url,request.company.company_id,'archived-company-website',text)
    record=VerifiedRecord(source_id,candidate.url,candidate.company_id,candidate.topic,digest(text),
        stamp,'READABLE_ARCHIVE',True,stamp,stamp)
    receipt=dict(archive='COMMON_CRAWL_WARC_STRICT_SUBSET',original_url=pointer.url,
        archive_data_url=pointer.data_url,range_header=pointer.range_header,record_id=record_id,
        index_capture=pointer.captured_at.isoformat(),warc_capture=stamp.isoformat(),
        compressed_sha256=compressed_sha,decoded_record_sha256=hashlib.sha256(raw).hexdigest(),
        html_sha256=hashlib.sha256(payload).hexdigest(),extracted_text_sha256=digest(text),
        index_and_payload_sha1=payload_digest,block_sha1=_sha1(block),text_chars=len(text),
        semantic_claim_truth_certified=False,domain_ownership_independently_certified=False,
        model_calls=0,source_http_requests=0)
    return candidate,record,receipt
