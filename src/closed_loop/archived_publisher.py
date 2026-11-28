"""Bounded third-party-publisher historical binding, reusing the archive verifier.

This proves only that a historical, archived snapshot of some arbitrary
publisher domain visibly named the target company in its headline AND linked
back to the company's own anchored domain -- a historical headline/link
relationship, nothing about editorial independence or the truth of any claim
in the article. There is no publisher whitelist: any public HTTP(S) hostname
can be inspected, but only the target company (never a peer subject) may be
bound this way, and the official company domain itself is explicitly out of
scope here (the first-party ``ArchivedWebsiteProvider.verify_discovered_url``
already covers it).
"""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse

from .archive_transport import ArchivedWebsiteProvider, ArchiveRestricted, VisibleText, serialized
from .contracts import CompanySeed, ResearchRequest, digest
from .guards import SourceCandidate, VerifiedRecord

PUBLISHER_CONTEXT_TOPIC = 'ARCHIVED_EXTERNAL_PUBLISHER_CONTEXT'

_HIDDEN_TAGS = ('script', 'style', 'noscript', 'template', 'svg')


class _BindingParser(HTMLParser):
    """Visible title/h1 text plus anchor labels (incl. image alt), hidden-tag aware."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self._headline_depth = 0
        self.headline_parts = []
        self.headline_blocks = []
        self.current_href = None
        self.label_parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in _HIDDEN_TAGS:
            self.hidden += 1
            return
        if self.hidden:
            return
        if tag in ('title', 'h1'):
            if self._headline_depth == 0:self.headline_blocks.append([])
            self._headline_depth += 1
        if tag == 'a':
            self.current_href = dict(attrs).get('href')
            self.label_parts = []
        if tag == 'img' and self.current_href is not None:
            alt = dict(attrs).get('alt')
            if alt:
                self.label_parts.append(alt)

    def handle_endtag(self, tag):
        if tag in _HIDDEN_TAGS:
            if self.hidden:
                self.hidden -= 1
            return
        if self.hidden:
            return
        if tag in ('title', 'h1') and self._headline_depth:
            self._headline_depth -= 1
        if tag == 'a' and self.current_href is not None:
            if len(self.links) < 1000:
                self.links.append((self.current_href, ' '.join(self.label_parts)))
            self.current_href = None
            self.label_parts = []

    def handle_data(self, text):
        if self.hidden:
            return
        stripped = text.strip()
        if not stripped:
            return
        if self._headline_depth:
            self.headline_parts.append(stripped)
            self.headline_blocks[-1].append(stripped)
        if self.current_href is not None:
            self.label_parts.append(stripped)


class _ContextParser(VisibleText):
    """Select static article/main text; navigation is not target-company evidence."""
    def __init__(self):
        super().__init__();self.blocks=[];self.active={'article':[],'main':[]}
    def handle_starttag(self,tag,attrs):
        if tag in ('nav','footer'):
            self.hidden+=1;return
        super().handle_starttag(tag,attrs)
        if self.hidden:return
        if tag in self.active:
            block=[];self.active[tag].append(block);self.blocks.append((tag,block))
    def handle_endtag(self,tag):
        if tag in ('nav','footer'):
            if self.hidden:self.hidden-=1
            return
        if self.hidden:
            super().handle_endtag(tag);return
        super().handle_endtag(tag)
        if tag in self.active and self.active[tag]:self.active[tag].pop()
    def handle_data(self,data):
        if self.hidden or not data.strip():return
        for stack in self.active.values():
            for block in stack:block.append(data.strip())

def _publisher_context(body,company_name,company_domain):
    parser=_ContextParser();parser.feed(body.decode('utf-8',errors='strict'))
    for wanted in ('article','main'):
        for tag,parts in parser.blocks:
            if tag!=wanted:continue
            text=' '.join(' '.join(parts).split())
            if len(text)>=80 and (_contains_whole_phrase(text,company_name) or company_domain in text):
                return text
    return None


def _contains_whole_phrase(text, phrase):
    return re.search(r'(?<!\w)' + re.escape(' '.join(phrase.split())) + r'(?!\w)', text, re.I) is not None


class ArchivedPublisherVerifier(ArchivedWebsiteProvider):
    """Same constructor/budget/client/domain_anchors contract as the base provider.

    Default domain anchors still target the company itself; a publisher host
    is never treated as the company domain. Only ``verify_discovered_url`` is
    public, and only the task's own company (never a peer subject id) may be
    bound against a third-party publisher.
    """

    @serialized
    def verify_discovered_url(self, task, url):
        if not isinstance(task,ResearchRequest) or task.company_id != self.request.company.company_id:
            raise ValueError('task must match run company')
        subject = task.subject_id or task.company_id
        if subject != task.company_id:
            self.attempts.append(dict(status='PEER_PUBLISHER_BINDING_UNSUPPORTED'))
            return None
        official_domain = self.domain_anchors.get(task.company_id)
        if official_domain is None:
            self.attempts.append(dict(status='SUBJECT_DOMAIN_UNRESOLVED'))
            return None
        if not isinstance(url, str) or not url or any(ch.isspace() or ord(ch) < 32 for ch in url) or ';' in url:
            self.attempts.append(dict(url_sha256=digest(url if isinstance(url, str) else ''),
                status='DISCOVERED_URL_REJECTED'))
            return None
        try:
            parsed = urlparse(url)
            port = parsed.port
        except ValueError:
            self.attempts.append(dict(url_sha256=digest(url), status='DISCOVERED_URL_REJECTED'))
            return None
        hostname = parsed.hostname
        if (parsed.scheme not in ('http', 'https') or parsed.username is not None or
                parsed.password is not None or port not in (None, 443 if parsed.scheme == 'https' else 80) or
                parsed.fragment or hostname is None):
            self.attempts.append(dict(url_sha256=digest(url), status='DISCOVERED_URL_REJECTED'))
            return None
        hostname = hostname.lower()
        try:
            CompanySeed('_publisher_host_probe', '_publisher_host_probe', hostname)
        except ValueError:
            self.attempts.append(dict(url_sha256=digest(url), status='DISCOVERED_URL_REJECTED'))
            return None
        if hostname.removeprefix('www.') == official_domain.lower().removeprefix('www.'):
            # The company's own domain is handled by the first-party verifier;
            # this component never pretends a publisher host is the company.
            self.attempts.append(dict(url_sha256=digest(url), status='OFFICIAL_DOMAIN_USE_FIRST_PARTY_VERIFIER'))
            return None
        path = parsed.path or '/'
        full = path + ('?' + parsed.query if parsed.query else '')
        if (len(full) > 512 or any(part in ('.', '..') for part in path.split('/')) or
                '%' in path or path.startswith('//')):
            self.attempts.append(dict(url_sha256=digest(url), status='DISCOVERED_URL_REJECTED'))
            return None
        try:
            capture = self._capture(hostname, full)
            if capture is None:
                return None
            when, ts, original = capture
            returned = urlparse(original)
            if returned.hostname != hostname or (returned.path or '/') != path or returned.query != parsed.query:
                self.attempts.append(dict(url_sha256=digest(url), status='DISCOVERED_CAPTURE_URL_MISMATCH'))
                return None
            requested = 'https://web.archive.org/web/' + ts + 'id_/' + original
            response = self._get(requested)
            if response is None or response.status != 200:
                self.attempts.append(dict(url_sha256=digest(url), status='PUBLISHER_REPLAY_UNAVAILABLE'))
                return None
            if not self._binding_established(response, self.request.company.name, official_domain):
                self.attempts.append(dict(url_sha256=digest(url), status='PUBLISHER_BINDING_NOT_ESTABLISHED'))
                return None
            context=_publisher_context(response.body,self.request.company.name,official_domain)
            if context is None:
                self.attempts.append(dict(status='PUBLISHER_ARTICLE_CONTEXT_NOT_ESTABLISHED'))
                return None
            base = super()._replay(task.company_id, capture, allow_reindex=False)
            if base is None:
                return None
            return self._register_publisher_context(task.company_id, base, capture,context)
        except ArchiveRestricted:
            # Terminal for this run; caller must stop, never retry an alternate.
            return None

    def _binding_established(self, response, company_name, company_domain):
        try:
            parser = _BindingParser()
            parser.feed(response.body.decode('utf-8', errors='strict'))
        except UnicodeDecodeError:
            return False
        if not any(_contains_whole_phrase(' '.join(' '.join(block).split()),company_name)
                   for block in parser.headline_blocks):
            return False
        base_domain = company_domain.lower()
        for href, label in parser.links:
            if not isinstance(href, str) or len(href) > 1024:
                continue
            try:
                target = urlparse(urljoin(response.url, href))
                target_port = target.port
            except ValueError:
                continue
            host = (target.hostname or '').lower()
            if (target.scheme not in ('http', 'https') or target.username or target.password or
                    target_port not in (None,443 if target.scheme=='https' else 80) or
                    any(c.isspace() or ord(c)<32 for c in href)):
                continue
            if host != base_domain:
                continue
            label_clean = ' '.join(label.split())
            if _contains_whole_phrase(label_clean, company_name) or company_domain.lower() in label_clean.lower():
                return True
        return False

    def _register_publisher_context(self, company_id, base_candidate, capture,context):
        when, _ts, _original = capture
        prefix = ('Third-party publisher archived context; headline/link binding only, '
                  'not independently verified claims or editorial independence: ')
        if self.max_text_chars-len(prefix)<80:
            self.attempts.append(dict(status='PUBLISHER_CONTEXT_TEXT_CAP_TOO_SMALL'))
            return None
        text=(prefix+context)[:self.max_text_chars]
        record = VerifiedRecord(base_candidate.source_id, base_candidate.url, company_id,
            PUBLISHER_CONTEXT_TOPIC, digest(text), when, 'READABLE_ARCHIVE', True, when, when)
        self.gateway.register_verified_record(record)
        for receipt in self.receipts:
            if receipt['source_id'] == base_candidate.source_id:
                receipt.update(identity_binding='HEADLINE_AND_LINK_MATCHED_COMPANY_NAME_OR_DOMAIN',
                    source_scope='THIRD_PARTY_PUBLISHER_NOT_WHITELISTED',
                    editorial_independence='UNKNOWN',
                    context_text_sha256=digest(text),context_extractor='static-article-main-v1')
                break
        return SourceCandidate(base_candidate.source_id, base_candidate.url, company_id,
            PUBLISHER_CONTEXT_TOPIC, text)
