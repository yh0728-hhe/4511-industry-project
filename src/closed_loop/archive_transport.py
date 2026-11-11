"""Bounded historical website retrieval, using CDX + verified raw replay.

HTTP transport and identity-domain anchors are trusted application components,
not proof fields supplied by an LLM. No current-site fallback is permitted.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html.parser import HTMLParser
import json
from urllib.parse import urlencode, urlparse,urljoin
import urllib.error
import urllib.request
import zlib
import re
from threading import RLock
from functools import wraps
from .historical_links import discover_links,rank_links

from .contracts import CompanySeed, aware, digest
from .guards import BudgetStopped, SourceCandidate, VerifiedRecord


class RetrievalFailed(RuntimeError):
    pass


def serialized(method):
    @wraps(method)
    def guarded(self,*args,**kwargs):
        with self._lock:return method(self,*args,**kwargs)
    return guarded


def archive_url_allowed(url):
    try:
        parsed=urlparse(url)
        return (parsed.scheme=='https' and parsed.hostname=='web.archive.org' and
            parsed.username is None and parsed.password is None and parsed.port in (None,443))
    except (TypeError,ValueError):return False


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    url: str
    headers: dict
    body: bytes


class ArchiveHTTPClient:
    """One request, no retries, bounded body and timeout; archive-only redirects."""
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        if not archive_url_allowed(url):raise RetrievalFailed('HOST_NOT_ALLOWED')
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,headers,newurl):
                # A hidden follow-up would evade the per-HTTP reservation count.
                return None
        opener=urllib.request.build_opener(Redirect())
        req=urllib.request.Request(url,headers={'User-Agent':'Columbia-IEOR4511-HistoricalResearch/1.0',
            'Accept-Encoding':'identity'})
        try:
            with opener.open(req,timeout=timeout) as response:
                pieces=[];size=0
                while True:
                    check_deadline()
                    part=response.read1(min(8192,max_bytes+1-size))
                    if not part:break
                    pieces.append(part);size+=len(part)
                    if size>max_bytes:raise RetrievalFailed('BODY_LIMIT')
                body=b''.join(pieces)
                if response.headers.get('Content-Encoding','').lower()=='gzip' or body[:2]==b'\x1f\x8b':
                    decoder=zlib.decompressobj(16+zlib.MAX_WBITS)
                    body=decoder.decompress(body,max_bytes+1)
                    if len(body)>max_bytes or not decoder.eof:raise RetrievalFailed('DECOMPRESSED_BODY_LIMIT_OR_INVALID')
                return HTTPResponse(response.status,response.geturl(),dict(response.headers),body)
        except urllib.error.HTTPError as exc:
            return HTTPResponse(exc.code,url,dict(exc.headers),b'')
        except RetrievalFailed:raise
        except BudgetStopped:raise
        except Exception:raise RetrievalFailed('HTTP_TRANSPORT_ERROR') from None


class VisibleText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.hidden=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','template','svg'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','template','svg') and self.hidden:self.hidden-=1
    def handle_data(self,text):
        if not self.hidden and text.strip():self.parts.append(text.strip())


def visible_text(raw):
    parser=VisibleText();parser.feed(raw.decode('utf-8',errors='strict'))
    return ' '.join(' '.join(parser.parts).split())


class ArchivedWebsiteProvider:
    """Model-selected research is resolved to bounded historical URL lookups.

    Domain anchors must come from justified identity records. This component
    establishes snapshot availability/content, not historical domain ownership
    independently. Root records anchor provenance for real-company probes.
    """
    def __init__(self, request, gateway, budget, client=None, domain_anchors=None,
                 max_requests=8,per_request_timeout=12,max_body_bytes=262144,max_text_chars=6000):
        self.request=request;self.gateway=gateway;self.call_budget=budget
        self.client=client or ArchiveHTTPClient()
        self.domain_anchors=dict(domain_anchors or {request.company.company_id:request.company.domain})
        for subject,domain in self.domain_anchors.items():CompanySeed(subject,subject,domain)
        if type(max_requests) is not int or max_requests<1:raise ValueError('request cap required')
        if not isinstance(per_request_timeout,(int,float)) or not 0<per_request_timeout<=60:
            raise ValueError('timeout must be positive and <=60 seconds')
        if type(max_body_bytes) is not int or max_body_bytes<128 or type(max_text_chars) is not int or max_text_chars<80:
            raise ValueError('positive explicit content bounds required')
        self.max_requests=max_requests;self.per_request_timeout=per_request_timeout
        self.max_body_bytes=max_body_bytes;self.max_text_chars=max_text_chars
        self.attempts=[];self.receipts=[];self._responses={};self._request_count=0
        self._links={};self._root_candidates={}
        # Serialize provider state and cache ownership, including physical fetch.
        self._lock=RLock()

    @serialized
    def link_hints(self):
        return tuple(dict(subject_id=link.subject_id,url=link.url,path=link.path,label=link.label,
            observed_at=link.observed_at.isoformat(),found_in_source_id=link.found_in_source_id,
            target_content_verified=False) for _,link in sorted(self._links.items()))[:16]

    @serialized
    def _get(self,url):
        if url in self._responses:return self._responses[url]
        if self._request_count>=self.max_requests:raise BudgetStopped('HTTP_REQUEST_CAP')
        self.call_budget.check()
        timeout=min(self.per_request_timeout,self.call_budget.remaining_seconds())
        if timeout<=0:raise BudgetStopped('STOP_OR_DEADLINE')
        with self.call_budget.reserve('search'):
            self._request_count+=1
            try:response=self.client.get(url,timeout,self.max_body_bytes,check_deadline=self.call_budget.check)
            except RetrievalFailed as exc:
                self.attempts.append(dict(url_sha256=digest(url),status=str(exc)))
                self._responses[url]=None;return None
        self.call_budget.check()
        if not archive_url_allowed(response.url):
            self.attempts.append(dict(url_sha256=digest(url),status='FINAL_HOST_NOT_ALLOWED'))
            self._responses[url]=None;return None
        if len(response.body)>self.max_body_bytes:raise RetrievalFailed('BODY_LIMIT')
        self.attempts.append(dict(url_sha256=digest(url),status='HTTP_'+str(response.status)))
        self._responses[url]=response
        return response

    def _capture(self,domain,path,exact_timestamp=None):
        # No rolling lower bound: old relevant evidence remains eligible.
        timestamp=self.request.as_of.astimezone(timezone.utc).strftime('%Y%m%d%H%M%S')
        params=[('url',domain+path),('matchType','exact'),('output','json'),
            ('fl','timestamp,original,statuscode,mimetype'),('to',timestamp),
            ('filter','statuscode:200'),('filter','mimetype:text/html'),('limit','-1')]
        if exact_timestamp is not None:
            if not re.fullmatch(r'\d{14}',exact_timestamp) or exact_timestamp>timestamp:return None
            params=[(key,exact_timestamp if key=='to' else value) for key,value in params]
            params.append(('from',exact_timestamp))
        response=self._get('https://web.archive.org/cdx/search/cdx?'+urlencode(params))
        if response is None or response.status!=200:return None
        try:
            rows=json.loads(response.body)
            if not isinstance(rows,list):raise ValueError()
            captures=[]
            for row in rows:
                if row and row[0]=='timestamp':continue
                if not isinstance(row,list) or len(row)!=4:continue
                ts,original,status,mime=row
                if not isinstance(ts,str) or not re.fullmatch(r'\d{14}',ts):continue
                when=datetime.strptime(ts,'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
                parsed_original=urlparse(original)
                host=(parsed_original.hostname or '').lower()
                wanted=urlparse('https://'+domain+path)
                if (host.removeprefix('www.')==domain.removeprefix('www.') and
                    parsed_original.scheme in ('http','https') and parsed_original.username is None and
                    parsed_original.password is None and parsed_original.port in (None,80,443) and
                    (parsed_original.path.rstrip('/') or '/')==(wanted.path.rstrip('/') or '/') and
                    parsed_original.query==wanted.query and when<=self.request.as_of and
                    status=='200' and mime=='text/html'):
                    captures.append((when,ts,original))
            if not captures:self.attempts.append(dict(status='NO_ELIGIBLE_RETURNED_CAPTURE'));return None
            return max(captures)
        except (ValueError,TypeError,UnicodeDecodeError):
            self.attempts.append(dict(status='INVALID_CDX_RESPONSE'));return None

    def _replay(self,subject,capture,allow_reindex=True,redirected_from=None):
        when,ts,original=capture
        requested='https://web.archive.org/web/'+ts+'id_/'+original
        response=self._get(requested)
        if response is None:return None
        if response.status in (301,302,303,307,308):
            headers={k.lower():v for k,v in response.headers.items()}
            target=urljoin(requested,headers.get('location',''))
            match=re.fullmatch(r'https://web\.archive\.org/web/(\d{14})id_/(https?://.+)',target)
            if not allow_reindex or not match or match[2]!=original or match[1]==ts:
                self.attempts.append(dict(status='REDIRECT_HELD'));return None
            try:proposed_time=datetime.strptime(match[1],'%Y%m%d%H%M%S').replace(tzinfo=timezone.utc)
            except ValueError:
                self.attempts.append(dict(status='INVALID_REDIRECT_TIMESTAMP'));return None
            if proposed_time>self.request.as_of:
                self.attempts.append(dict(status='POST_CUTOFF_REDIRECT_HELD'));return None
            parsed=urlparse(original)
            # Treat the alternate as a NEW indexed candidate; never relabel its
            # body with the originally requested capture's timestamp.
            self.attempts.append(dict(status='ALTERNATE_CAPTURE_REINDEX_REQUIRED'))
            verified=self._capture(parsed.hostname,(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),match[1])
            if verified is None or verified[1]!=match[1] or verified[2]!=original:
                self.attempts.append(dict(status='ALTERNATE_CAPTURE_NOT_INDEX_VERIFIED'));return None
            return self._replay(subject,verified,allow_reindex=False,redirected_from=ts)
        if response.status!=200:return None
        headers={k.lower():v for k,v in response.headers.items()}
        if headers.get('content-type','').split(';')[0].strip().lower() not in ('text/html','application/xhtml+xml'):
            self.attempts.append(dict(status='MISSING_OR_UNSUPPORTED_CONTENT_TYPE'));return None
        try:served=aware(parsedate_to_datetime(headers.get('memento-datetime','')))
        except (TypeError,ValueError,IndexError):
            self.attempts.append(dict(status='MISSING_MEMENTO_HEADER'));return None
        if served!=when or response.url!=requested:
            self.attempts.append(dict(status='REPLAY_IDENTITY_OR_CAPTURE_MISMATCH'));return None
        try:text=visible_text(response.body)
        except UnicodeDecodeError:
            self.attempts.append(dict(status='UNSUPPORTED_TEXT_ENCODING'));return None
        if len(text)<80 or any(marker in text.lower() for marker in (
                'wayback machine has not archived','this url has been excluded','cannot be crawled or displayed')):
            self.attempts.append(dict(status='UNUSABLE_REPLAY_BODY'));return None
        admitted=text[:self.max_text_chars]
        raw_sha=hashlib.sha256(response.body).hexdigest()
        source_id=digest(subject+'|'+requested+'|'+raw_sha)
        candidate=SourceCandidate(source_id,requested,subject,'ARCHIVED_WEBSITE_CONTENT',admitted)
        record=VerifiedRecord(source_id,requested,subject,candidate.topic,digest(admitted),when,
            'READABLE_ARCHIVE',True,when,served)
        self.gateway.register_verified_record(record)
        for link in discover_links(response.body,original,subject,self.domain_anchors[subject],when,source_id):
            self._links[(subject,link.path)]=link
        if any(receipt['source_id']==source_id for receipt in self.receipts):return candidate
        self.receipts.append(dict(source_id=source_id,subject_id=subject,original_url=original,
            replay_url=requested,selected_capture=ts,memento_datetime=served.isoformat(),
            body_sha256=raw_sha,visible_text_sha256=digest(admitted),extractor='stdlib-visible-text-v1',
            truncated=len(text)>self.max_text_chars,availability_proof='READABLE_REPLAY_MATCHING_MEMENTO',
            identity_proof='CALLER_SUPPLIED_DOMAIN_ANCHOR_NOT_INDEPENDENT_OWNERSHIP_CHECK'))
        if redirected_from:self.receipts[-1]['original_requested_capture_before_reindex']=redirected_from
        return candidate

    @serialized
    def search(self,task):
        subject=task.subject_id or task.company_id
        domain=self.domain_anchors.get(subject)
        if domain is None:
            self.attempts.append(dict(status='SUBJECT_DOMAIN_UNRESOLVED'));return ()
        found=[]
        # Bootstrap link discovery from a dated homepage. A discovered href is
        # not itself proof of its target content; every selected target is re-indexed.
        if subject not in self._root_candidates:
            capture=self._capture(domain,'/')
            self._root_candidates[subject]=self._replay(subject,capture) if capture else None
        root=self._root_candidates[subject]
        if root:found.append(root)
        links=tuple(link for (owner,_),link in self._links.items() if owner==subject and link.path!='/')
        if task.source_path is not None:
            if task.source_path not in {link.path for link in links}:
                self.attempts.append(dict(status='REQUESTED_PATH_NOT_OBSERVED_HISTORICALLY'));return tuple(found)
            paths=(task.source_path,)
        else:
            ranked=rank_links(links,task.role,task.question,limit=1)
            paths=tuple(link.path for link in ranked)
            if not paths and task.role in ('team','founder'):paths=('/about','/team')
        for path in paths:
            # Do not start an optional CDX+replay pair that cannot fit. Existing
            # admitted evidence remains available to the committee/review.
            remaining=self.call_budget.caps['search']-self.call_budget.used['search']
            if self.max_requests-self._request_count<2 or remaining<2:
                self.attempts.append(dict(status='OPTIONAL_LOOKUP_SKIPPED_BUDGET'));break
            capture=self._capture(domain,path)
            if capture:
                candidate=self._replay(subject,capture)
                if candidate:found.append(candidate);break
        return tuple(found)
