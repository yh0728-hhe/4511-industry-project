"""Explicit-client discovery adapter reusing existing registry collector/verifiers.

A discovered npm/PyPI URL is an untrusted lead from a prior discovery stage,
never a trusted identity source. All retrieval is delegated to a fresh
PackageRegistryCollector bound to the caller's exact shared request/budget and
explicit HTTP client; all identity/content verification is delegated to
verify_wheel_source/verify_npm_source, which check embedded links against the caller-declared primary domain
before anything is registered with the gateway. Package
README/homepage text is an attributed maintainer claim, never independent
proof of traction or domain ownership.
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

from .guards import BudgetStopped, CallBudget
from .contracts import digest, ResearchRequest
from .npm_names import parse_npm_name
from .npm_source import verify_npm_source
from .package_registry import PackageRegistryCollector
from .package_source import verify_wheel_source

MAX_CANDIDATE_CHARS = 6000

_NAME_RE = re.compile(r'[a-z0-9][a-z0-9._-]*')
_NPM_SEGMENT = r'[a-z0-9][a-z0-9._-]*'
_NPM_NAME = rf'@{_NPM_SEGMENT}/{_NPM_SEGMENT}|{_NPM_SEGMENT}'
_PYPI_PROJECT_RE = re.compile(r'/project/([a-z0-9][a-z0-9._-]*)/?')
_PYPI_JSON_RE = re.compile(r'/pypi/([a-z0-9][a-z0-9._-]*)/json')
_NPM_WEB_RE = re.compile(rf'/package/({_NPM_NAME})/?')
_NPM_REGISTRY_RE = re.compile(rf'/({_NPM_NAME})')


def _invalid_name(name):
    return not isinstance(name, str) or not _NAME_RE.fullmatch(name) or '..' in name


def _invalid_npm_name(name):
    return not isinstance(name, str) or parse_npm_name(name) is None


def parse_url(url):
    """Return (package_name, artifact_format) for a supported canonical URL, else None.

    Only exact, unversioned, query/fragment-free, non-encoded HTTPS registry
    URLs for lowercase unscoped names or canonical lowercase `@scope/name`
    npm names are accepted; everything else is rejected before any request
    is made.
    """
    if not isinstance(url, str) or url != url.strip() or any(ord(c)<32 or ord(c)==127 for c in url):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.scheme != 'https' or parsed.username is not None or parsed.password is not None or
            parsed.netloc not in ('pypi.org','www.npmjs.com','npmjs.com','registry.npmjs.org') or
            parsed.query or parsed.fragment or
            '%' in parsed.path or '\\' in parsed.path):
        return None
    host = parsed.hostname
    path = parsed.path

    if host == 'pypi.org':
        match = _PYPI_PROJECT_RE.fullmatch(path) or _PYPI_JSON_RE.fullmatch(path)
        if not match:
            return None
        name = match.group(1)
        return None if _invalid_name(name) else (re.sub(r'[-_.]+','-',name), 'wheel')

    if host in ('www.npmjs.com', 'npmjs.com'):
        match = _NPM_WEB_RE.fullmatch(path)
        if not match:
            return None
        name = match.group(1)
        return None if _invalid_npm_name(name) else (name, 'npm')

    if host == 'registry.npmjs.org':
        match = _NPM_REGISTRY_RE.fullmatch(path)
        if not match:
            return None
        name = match.group(1)
        return None if _invalid_npm_name(name) else (name, 'npm')

    return None


def accepts_url(url):
    return parse_url(url) is not None


class DiscoveredPackageVerifier:
    """Verifies a single discovered registry URL about the primary subject only."""

    accepts_url = staticmethod(accepts_url)

    def __init__(self, request, gateway, budget, client, output_dir):
        if not isinstance(budget, CallBudget) or budget.bound_request is not request:
            raise ValueError('EXACT_BOUND_BUDGET_REQUIRED')
        if getattr(gateway,'request',None) is not request:
            raise ValueError('EXACT_GATEWAY_REQUEST_REQUIRED')
        if not callable(getattr(client, 'get', None)):
            raise ValueError('EXPLICIT_HTTP_CLIENT_REQUIRED')
        self.request = request
        self.gateway = gateway
        self.call_budget = budget
        self.client = client
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=False)
        self.domain_anchors = {request.company.company_id: request.company.domain}
        self.receipts = []
        self.trace = []
        self._cache = {}

    def verify_discovered_url(self, task, url):
        """Return a reverified SourceCandidate or None; never installs package code."""
        self.call_budget.check()
        primary_id = self.request.company.company_id
        company_id = getattr(task, 'company_id', None)
        subject_id = getattr(task, 'subject_id', None)
        if not isinstance(task,ResearchRequest) or company_id != primary_id or subject_id not in (None, primary_id):
            self.trace.append(dict(event='peer_rejected_no_network', url_sha256=digest(url) if isinstance(url,str) else None))
            return None

        parsed = parse_url(url)
        if parsed is None:
            self.trace.append(dict(event='unsupported_url', url_sha256=digest(url) if isinstance(url,str) else None))
            return None
        package_name, artifact_format = parsed
        cache_key = (package_name, artifact_format)

        if cache_key in self._cache:
            return self._cache[cache_key]
        # Cache the attempt before any journal/HTTP activity, including misses.
        self._cache[cache_key] = None
        try:
            candidate = self._verify_fresh(package_name, artifact_format, url)
        except BudgetStopped as exc:
            self.call_budget.stop(str(exc))
            self.trace.append(dict(event='package_verification_stopped',reason=self.call_budget.stop_reason))
            raise BudgetStopped(self.call_budget.stop_reason) from None
        except Exception:
            self.call_budget.stop('REGISTRY_VERIFICATION_FAILED')
            self.trace.append(dict(event='package_verification_stopped',reason=self.call_budget.stop_reason))
            raise BudgetStopped(self.call_budget.stop_reason) from None
        self._cache[cache_key] = candidate
        return candidate

    def _verify_fresh(self, package_name, artifact_format, url):
        parsed_name = parse_npm_name(package_name) if artifact_format == 'npm' else None
        journal_stem = digest(package_name) if parsed_name and parsed_name[0] == 'scoped' else package_name
        journal_path = self.output_dir / f'{journal_stem}-{artifact_format}.jsonl'
        collector = PackageRegistryCollector(self.request, self.call_budget, self.client, journal_path)
        collected = collector.collect(package_name, artifact_format)
        if collected is None:
            self.trace.append(dict(event='unknown', package=package_name, format=artifact_format))
            return None

        try:
            if artifact_format == 'wheel':
                candidate, record = verify_wheel_source(
                    collected['artifact_bytes'], collected['file_metadata'], package_name, self.request)
            else:
                candidate, record = verify_npm_source(
                    collected['artifact_bytes'], collected['file_metadata'], package_name, self.request)
        except ValueError as exc:
            self.receipts.append(dict(package=package_name, format=artifact_format, url=url,
                                       outcome='rejected', reason=str(exc)))
            self.trace.append(dict(event='artifact_invalid', package=package_name, format=artifact_format))
            return None

        if len(candidate.text) > MAX_CANDIDATE_CHARS:
            self.receipts.append(dict(package=package_name, format=artifact_format, url=record.url,
                                       outcome='held_oversized', chars=len(candidate.text)))
            self.trace.append(dict(event='oversized_held', package=package_name, format=artifact_format))
            return None

        self.gateway.register_verified_record(record)
        fact, error = self.gateway.admit(candidate)
        if error is not None:
            self.receipts.append(dict(package=package_name, format=artifact_format, url=record.url,
                                       outcome='rejected', reason=error.get('reason')))
            self.trace.append(dict(event='admit_rejected', package=package_name, reason=error.get('reason')))
            return None

        self.receipts.append(dict(package=package_name, format=artifact_format, url=record.url,
                                   outcome='admitted', source_id=record.source_id,
                                   availability_upper_bound=record.availability_upper_bound.isoformat(),
                                   evidence_scope='ATTRIBUTED_PACKAGE_DOCUMENTATION',
                                   historical_domain_ownership_independently_proven=False))
        self.trace.append(dict(event='admitted', package=package_name, format=artifact_format))
        return candidate
