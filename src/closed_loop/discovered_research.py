"""Research provider over independently re-verified managed-discovery leads.

A managed web-discovery agent only returns *unverified leads* (URLs it saw
in a search result). Nothing from that agent -- its summary text, any date
hint, its own status string -- is ever treated as evidence. Primary website
leads use exact-domain/CDX/Memento replay verification. Optional same-budget
publisher verification establishes a historical headline/link association,
not editorial independence or claim truth. Optional package verification
uses authenticated registry metadata and digest-bound artifact documentation,
not the lead page or current registry summary. Every returned candidate is
independently admitted again by the same historical gateway before runtime use.
"""
import json
from pathlib import Path
from urllib.parse import urlsplit

from .contracts import digest, ResearchRequest
from .guards import BudgetStopped
from .web_discovery import DiscoveryResult

_ACCEPTED_STATUSES = ('HELD_FOR_VERIFICATION', 'NO_LEADS')


class DiscoveredResearchProvider:
    """Discover unverified leads, then independently re-verify each one.

    ``discovery_factory(task)`` must return a ``ManagedWebDiscoveryAgent``
    sharing this provider's ``request``/``budget`` with its own exclusive
    output directory; it may be a test double. ``archive_provider`` must
    share this provider's ``request``/``gateway``/``budget``.
    """
    controls_historical_navigation = True

    def __init__(self, request, gateway, budget, discovery_factory, archive_provider, *, max_sources=3, publisher_verifier=None, package_verifier=None):
        if gateway.request != request or budget.bound_request != request:
            raise ValueError('request/gateway/budget contexts must match')
        if (archive_provider.request != request or archive_provider.gateway is not gateway
                or archive_provider.call_budget is not budget):
            raise ValueError('archive provider must share request/gateway/budget')
        if publisher_verifier is not None and (publisher_verifier.request != request or
                publisher_verifier.gateway is not gateway or publisher_verifier.call_budget is not budget or
                publisher_verifier.domain_anchors.get(request.company.company_id) !=
                    archive_provider.domain_anchors.get(request.company.company_id)):
            raise ValueError('publisher verifier must share request/gateway/budget/company anchor')
        self.publisher_verifier=publisher_verifier
        if package_verifier is not None and (package_verifier.request is not request or
                package_verifier.gateway is not gateway or package_verifier.call_budget is not budget or
                package_verifier.domain_anchors.get(request.company.company_id) != request.company.domain or
                not callable(getattr(package_verifier,'accepts_url',None))):
            raise ValueError('package verifier must share request/gateway/budget/company anchor')
        self.package_verifier=package_verifier
        if discovery_factory is None or not callable(discovery_factory):
            raise ValueError('explicit discovery agent factory required')
        if type(max_sources) is not int or not 1 <= max_sources <= 5:
            raise ValueError('max_sources must be an integer from 1 to 5')
        self.request = request
        self.gateway = gateway
        self.call_budget = budget
        self.discovery_factory = discovery_factory
        self.archive_provider = archive_provider
        self.max_sources = max_sources
        self.trace = []

    @property
    def cache_namespace(self):
        # Deterministic fingerprint: component code + domain anchors + config.
        # Never the factory's own repr, which is not stable across test doubles.
        fingerprint = dict(component='DiscoveredResearchProvider-v1',
            domain_anchors=dict(sorted(self.archive_provider.domain_anchors.items())),
            max_sources=self.max_sources,publisher_enabled=self.publisher_verifier is not None,
            package_enabled=self.package_verifier is not None,
            component_code={name:digest(Path(__file__).with_name(name).read_text(encoding='utf-8'))
                for name in ('discovered_research.py','web_discovery.py','archive_transport.py','archived_publisher.py','discovered_package.py','package_registry.py','package_source.py','npm_source.py','npm_names.py','registry_process.py','registry_worker.py')})
        return digest(json.dumps(fingerprint, sort_keys=True, separators=(',', ':')))

    def link_hints(self):
        hints=list(self.archive_provider.link_hints())
        if self.publisher_verifier is not None:
            hints.extend(self.publisher_verifier.link_hints())
        unique={}
        for hint in hints:
            unique[(hint['subject_id'],hint['path'],hint['found_in_source_id'])]=hint
        return tuple(unique.values())[:16]

    def _search_archived_path(self, task, subject):
        # An already-observed historical path is re-verified via the trusted
        # archive provider directly; no managed discovery/model dispatch for this route.
        path_hash = digest(task.source_path)
        self.trace.append(dict(event='DISCOVERED_RESEARCH_ARCHIVE_PATH', path_sha256=path_hash))
        try:
            own_paths={h['path'] for h in self.archive_provider.link_hints() if h['subject_id']==subject}
            publisher_hint=next((h for h in (self.publisher_verifier.link_hints() if self.publisher_verifier else ())
                if h['subject_id']==subject and h['path']==task.source_path),None)
            if publisher_hint is not None and task.source_path not in own_paths:
                candidate=self.archive_provider.verify_discovered_url(task,publisher_hint['url'])
                candidates=(candidate,) if candidate is not None else ()
            else:
                candidates = self.archive_provider.search(task)
        except BudgetStopped as exc:
            self.call_budget.stop(str(exc))
            self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason=self.call_budget.stop_reason))
            root = self.archive_provider._root_candidates.get(subject)
            candidates = (root,) if root else ()
        found = []
        for candidate in candidates:
            fact, rejection = self.gateway.admit(candidate, task.subject_id)
            if fact is None:
                self.trace.append(dict(event='DISCOVERED_SOURCE_HELD', path_sha256=path_hash,
                    source_id=candidate.source_id, **rejection))
                continue
            self.trace.append(dict(event='DISCOVERED_SOURCE_VERIFIED', path_sha256=path_hash,
                source_id=candidate.source_id))
            found.append(candidate)
        return tuple(found)

    def search(self, task):
        if not isinstance(task,ResearchRequest) or task.company_id != self.request.company.company_id:
            raise ValueError('research task must match run company')
        self.call_budget.check()
        subject = task.subject_id or task.company_id
        domain = self.archive_provider.domain_anchors.get(subject)
        if domain is None:
            self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason='SUBJECT_DOMAIN_UNRESOLVED'))
            return ()
        if task.source_path is not None:
            return self._search_archived_path(task, subject)
        agent = self.discovery_factory(task)
        if agent.request is not self.request or agent.call_budget is not self.call_budget:
            raise ValueError('discovery agent must share request/call_budget with this provider')
        try:
            result = agent.discover(task)
        except BudgetStopped as exc:
            self.call_budget.stop(str(exc))
            self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason=str(exc)))
            return ()
        if (not isinstance(result, DiscoveryResult) or result.verified is not False or
                type(result.admitted_fact_count) is not int or result.admitted_fact_count != 0 or
                result.status not in _ACCEPTED_STATUSES or result.historical_availability != 'UNVERIFIED' or
                type(result.observed_websearch_count) is not int or result.observed_websearch_count != 1 or
                not isinstance(result.source_urls,tuple) or len(result.source_urls)>5 or
                not all(isinstance(u,str) and u for u in result.source_urls) or
                len(set(result.source_urls))!=len(result.source_urls) or
                (result.status=='NO_LEADS' and bool(result.source_urls))):
            self.call_budget.stop('MALFORMED_DISCOVERY_RESULT')
            self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason='MALFORMED_DISCOVERY_RESULT'))
            raise BudgetStopped(self.call_budget.stop_reason)
        self.trace.append(dict(event='DISCOVERY_COMPLETE', status=result.status,
            lead_count=len(result.source_urls)))
        if result.status == 'NO_LEADS' or not result.source_urls:
            return ()
        found = []
        attempted = 0
        def host_of(url):
            try:return urlsplit(url).hostname
            except ValueError:return None
        ordered=sorted(result.source_urls,key=lambda u:host_of(u)!=domain)
        for url in ordered:
            try:
                self.call_budget.check()
            except BudgetStopped as exc:
                self.call_budget.stop(str(exc))
                self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason=str(exc)))
                break
            url_hash = digest(url)
            try:
                host = urlsplit(url).hostname
            except ValueError:
                host = None
            package_supported=(self.package_verifier is not None and
                subject==self.request.company.company_id and self.package_verifier.accepts_url(url))
            if host != domain and self.publisher_verifier is None and not package_supported:
                self.trace.append(dict(event='DISCOVERED_URL_HELD',url_sha256=url_hash,
                    reason='INDEPENDENT_PUBLISHER_OR_IDENTITY_VERIFIER_REQUIRED'))
                continue
            if attempted >= self.max_sources:
                self.trace.append(dict(event='DISCOVERED_URL_HELD',url_sha256=url_hash,
                    reason='SOURCE_VERIFICATION_CAP'))
                continue
            attempted += 1
            try:
                verifier=(self.archive_provider if host==domain else
                    self.package_verifier if package_supported else self.publisher_verifier)
                candidate = verifier.verify_discovered_url(task, url)
            except BudgetStopped as exc:
                self.call_budget.stop(str(exc))
                self.trace.append(dict(event='DISCOVERED_RESEARCH_STOP', reason=self.call_budget.stop_reason))
                break
            if candidate is None:
                self.trace.append(dict(event='DISCOVERED_URL_HELD', url_sha256=url_hash))
                continue
            fact, rejection = self.gateway.admit(candidate, task.subject_id)
            if fact is None:
                self.trace.append(dict(event='DISCOVERED_SOURCE_HELD', url_sha256=url_hash,
                    source_id=candidate.source_id, **rejection))
                continue
            self.trace.append(dict(event='DISCOVERED_SOURCE_VERIFIED', url_sha256=url_hash,
                source_id=candidate.source_id))
            found.append(candidate)
        return tuple(found)
