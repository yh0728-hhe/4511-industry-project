"""Bounded single-attempt PyPI/npm historical artifact retrieval and verification.

Journal entries are append+flush+fsync'd before each physical HTTP dispatch and
only ever carry public URL/status/hash metadata; no body/prompt/credential text
is ever written. Collection is a single attempt per instance: no retries, no
alternate registries, no silent redirect follow-up.
"""
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from .contracts import aware
from .guards import BudgetStopped, CallBudget
from .npm_names import canonical_tarball_url, parse_npm_name
from .npm_source import verify_npm_source
from .package_source import verify_wheel_source

_NAME_RE = re.compile(r'[a-z0-9][a-z0-9._-]*')
_NPM_SEGMENT = r'[a-z0-9][a-z0-9._-]*'
_NPM_PATH_RE = re.compile(
    rf'/(?:@{_NPM_SEGMENT}/)?{_NPM_SEGMENT}(?:/-/[a-z0-9][a-z0-9._+-]*\.tgz)?')
_ALLOWED_HOSTS = frozenset({'pypi.org', 'files.pythonhosted.org', 'registry.npmjs.org'})

MAX_METADATA_BYTES = 8_000_000
MAX_WHEEL_BYTES = 1_000_000
MAX_NPM_BYTES = 3_000_000


def registry_url_allowed(url):
    try:
        parsed=urlsplit(url)
        if (parsed.scheme!='https' or parsed.netloc not in _ALLOWED_HOSTS or
            parsed.query or parsed.fragment or '%' in parsed.path or '\\' in parsed.path or
            any(p in ('','.','..') for p in parsed.path.split('/')[1:])):
            return False
        if parsed.netloc=='pypi.org':
            return bool(re.fullmatch(r'/pypi/[a-z0-9][a-z0-9._-]*/json',parsed.path))
        if parsed.netloc=='files.pythonhosted.org':
            return parsed.path.startswith('/packages/')
        if parsed.path.startswith('/@'):
            name, separator, filename = parsed.path[1:].partition('/-/')
            identity = parse_npm_name(name)
            if identity is None or identity[0] != 'scoped':return False
            if not separator:return url == f'https://registry.npmjs.org/{name}'
            basename = identity[2]
            prefix = basename + '-'
            if not filename.startswith(prefix) or not filename.endswith('.tgz'):return False
            version = filename[len(prefix):-4]
            return url == canonical_tarball_url(name,version)
        return bool(_NPM_PATH_RE.fullmatch(parsed.path))
    except (ValueError,TypeError):return False


class RegistryTransportError(RuntimeError):
    pass


class RegistryTransportTimeout(RegistryTransportError):
    """The isolated transport child exceeded its bounded process wait."""
    pass


class RegistryHTTPClient:
    """One attempt, no retries/redirects; only the three fixed registry hosts."""

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        import urllib.error
        import urllib.request

        if not registry_url_allowed(url) or type(max_bytes) is not int or max_bytes<1 or timeout<=0:
            raise RegistryTransportError('HOST_PATH_OR_BOUNDS_NOT_ALLOWED')

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                # A hidden follow-up would evade the per-GET reservation count.
                return None

        opener = urllib.request.build_opener(NoRedirect())
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Columbia-IEOR4511-PackageRegistryResearch/1.0',
            'Accept-Encoding': 'identity',
        })
        try:
            with opener.open(req, timeout=timeout) as response:
                encoding = response.headers.get('Content-Encoding', '').strip().lower()
                if encoding not in ('', 'identity'):
                    raise RegistryTransportError('UNSUPPORTED_CONTENT_ENCODING')
                pieces = []
                size = 0
                while True:
                    check_deadline()
                    part = response.read1(min(8192, max_bytes + 1 - size))
                    if not part:
                        break
                    pieces.append(part)
                    size += len(part)
                    if size > max_bytes:
                        raise RegistryTransportError('BODY_LIMIT')
                body = b''.join(pieces)
                from .archive_transport import HTTPResponse
                return HTTPResponse(response.status, response.geturl(), dict(response.headers), body)
        except urllib.error.HTTPError as exc:
            from .archive_transport import HTTPResponse
            return HTTPResponse(exc.code, url, dict(exc.headers or {}), b'')
        except RegistryTransportError:
            raise
        except BudgetStopped:
            raise
        except Exception:
            raise RegistryTransportError('HTTP_TRANSPORT_ERROR') from None


def _reject_duplicate_keys(pairs):
    seen = set()
    result = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError('DUPLICATE_JSON_KEY')
        seen.add(key)
        result[key] = value
    return result


def _valid_pypi_file_url(url, filename):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'files.pythonhosted.org':
        return False
    if parsed.username is not None or parsed.password is not None or parsed.port is not None:
        return False
    if parsed.query or parsed.fragment or '%' in parsed.path or '\\' in parsed.path:
        return False
    if not parsed.path.startswith('/packages/'):
        return False
    parts = parsed.path.split('/')[1:]
    if any(part in ('', '.', '..') for part in parts):
        return False
    return parts[-1] == filename


def _select_wheel(payload, package_name, as_of):
    releases = payload.get('releases')
    if not isinstance(releases, dict):
        return None
    cutoff = aware(as_of)
    best = None
    for files in releases.values():
        if not isinstance(files, list):
            continue
        for record in files:
            if not isinstance(record, dict):
                continue
            if record.get('yanked') is not False or record.get('packagetype') != 'bdist_wheel':
                continue
            size = record.get('size')
            if type(size) is not int or not 0 < size <= MAX_WHEEL_BYTES:
                continue
            filename = record.get('filename')
            if not isinstance(filename, str):
                continue
            upload = record.get('upload_time_iso_8601')
            if not isinstance(upload, str):
                continue
            try:
                stamp = aware(datetime.fromisoformat(upload.replace('Z', '+00:00')))
            except ValueError:
                continue
            if stamp > cutoff:
                continue
            key = (stamp, filename)
            if best is None or key > best[0]:
                best = (key, record)
    if best is None:
        return None
    record = best[1]
    if not _valid_pypi_file_url(record.get('url'),record['filename']):raise ValueError('INVALID_ARTIFACT_URL')
    return record['url'], record


def _valid_npm_tarball_url(url, name, version):
    if not isinstance(url, str):
        return False
    expected = canonical_tarball_url(name, version)
    if expected is None or url != expected:
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'registry.npmjs.org' and
            parsed.username is None and parsed.password is None and parsed.port is None)


def _select_npm(payload, package_name, as_of):
    versions = payload.get('versions')
    times = payload.get('time')
    if not isinstance(versions, dict) or payload.get('name') != package_name or not isinstance(times, dict):
        return None
    cutoff = aware(as_of)
    best = None
    for version, info in versions.items():
        if not isinstance(info, dict) or not isinstance(version, str):
            continue
        if info.get('name') != package_name or info.get('version') != version:
            continue
        published = times.get(version)
        if not isinstance(published, str):
            continue
        try:
            stamp = aware(datetime.fromisoformat(published.replace('Z', '+00:00')))
        except ValueError:
            continue
        if stamp > cutoff:
            continue
        dist = info.get('dist')
        if not isinstance(dist, dict):
            continue
        integrity = dist.get('integrity')
        if not isinstance(integrity, str) or not integrity.startswith('sha512-'):
            continue
        key = (stamp, version)
        if best is None or key > best[0]:
            best = (key, version, published, dist)
    if best is None:
        return None
    _, version, published, dist = best
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z.+-]*',version) or not _valid_npm_tarball_url(dist.get('tarball'),package_name,version):raise ValueError('INVALID_ARTIFACT_URL')
    metadata = {'name': package_name, 'version': version, 'published': published,
                'dist': {'tarball': dist['tarball'], 'integrity': dist['integrity']}}
    return dist['tarball'], metadata


class PackageRegistryCollector:
    """One `collect` attempt per instance against a durable, exclusive journal."""

    def __init__(self, request, budget, client, journal_path):
        if not isinstance(budget, CallBudget) or budget.bound_request is not request:
            raise ValueError('EXACT_BOUND_BUDGET_REQUIRED')
        self.request = request
        self.budget = budget
        self.client = client
        self._used = False
        self._lock = Lock()
        if not callable(getattr(client,"get",None)):raise ValueError("EXPLICIT_HTTP_CLIENT_REQUIRED")
        try:
            self._journal_file = open(Path(journal_path), 'x', encoding='utf-8')
        except FileExistsError:
            raise ValueError('JOURNAL_PATH_ALREADY_EXISTS') from None

    def _journal_write(self, record):
        line = json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n'
        try:
            self._journal_file.write(line)
            self._journal_file.flush()
            os.fsync(self._journal_file.fileno())
        except (OSError,ValueError):
            self.budget.stop('REGISTRY_JOURNAL_UNAVAILABLE')
            raise BudgetStopped(self.budget.stop_reason) from None

    def _dispatch(self, url, max_bytes, purpose):
        self.budget.check()
        remaining = self.budget.remaining_seconds()
        if remaining <= 0:
            raise BudgetStopped('STOP_OR_DEADLINE')
        timeout = min(15, remaining)
        try:
            with self.budget.reserve('search'):
                self._journal_write(dict(event='intent',url=url,purpose=purpose))
                self.budget.check()
                response = self.client.get(url, timeout, max_bytes, check_deadline=self.budget.check)
        except BudgetStopped as exc:
            self.budget.stop(str(exc));raise
        except RegistryTransportTimeout:
            try:self.budget.check()
            except BudgetStopped as exc:
                self.budget.stop(str(exc));raise BudgetStopped(self.budget.stop_reason) from None
            self.budget.stop('REGISTRY_REQUEST_TIMEOUT')
            self._journal_write(dict(event='error',url=url,purpose=purpose,error=self.budget.stop_reason))
            raise BudgetStopped(self.budget.stop_reason) from None
        except Exception:
            self.budget.stop('REGISTRY_TRANSPORT_ERROR')
            self._journal_write(dict(event='error',url=url,purpose=purpose,error='REGISTRY_TRANSPORT_ERROR'))
            raise BudgetStopped('REGISTRY_TRANSPORT_ERROR') from None
        from .archive_transport import HTTPResponse
        if not isinstance(response,HTTPResponse) or type(response.status) is not int or not isinstance(response.body,bytes) or len(response.body)>max_bytes:
            self.budget.stop('REGISTRY_INVALID_RESPONSE');raise BudgetStopped('REGISTRY_INVALID_RESPONSE')
        if response.url != url:
            self.budget.stop('REGISTRY_RESPONSE_URL_MISMATCH')
            self._journal_write(dict(event='rejected', url=url, purpose=purpose, status='URL_MISMATCH'))
            raise BudgetStopped('REGISTRY_RESPONSE_URL_MISMATCH')
        if response.status in (403,429):
            self.budget.stop('REGISTRY_RATE_LIMITED' if response.status==429 else 'REGISTRY_ACCESS_RESTRICTED')
        body_hash = hashlib.sha256(response.body).hexdigest()
        self._journal_write(dict(event='response', url=url, purpose=purpose,
                                  status=response.status, body_sha256=body_hash))
        if response.status in (403, 429):
            cause = 'REGISTRY_RATE_LIMITED' if response.status == 429 else 'REGISTRY_ACCESS_RESTRICTED'
            self.budget.stop(cause)
            raise BudgetStopped(cause)
        if response.status not in (200, 404):
            self.budget.stop('REGISTRY_UNEXPECTED_STATUS')
            raise BudgetStopped('REGISTRY_UNEXPECTED_STATUS')
        self.budget.check()
        return response

    def close(self):
        with self._lock:
            self._used=True
            self._journal_file.close()

    def collect(self,package_name,artifact_format):
        with self._lock:
            if self._used:raise RuntimeError('COLLECTOR_SINGLE_USE')
            self._used=True
            try:return self._collect(package_name,artifact_format)
            except BudgetStopped as exc:
                self.budget.stop(str(exc));raise
            finally:self._journal_file.close()

    def _collect(self, package_name, artifact_format):
        if artifact_format not in ('wheel', 'npm'):
            raise ValueError('UNSUPPORTED_ARTIFACT_FORMAT')
        if artifact_format == 'wheel':
            if (not isinstance(package_name, str) or not _NAME_RE.fullmatch(package_name) or
                    '..' in package_name):
                raise ValueError('INVALID_PACKAGE_NAME')
        else:
            if parse_npm_name(package_name) is None:
                raise ValueError('INVALID_PACKAGE_NAME')

        metadata_url = (f'https://pypi.org/pypi/{package_name}/json' if artifact_format == 'wheel'
                         else f'https://registry.npmjs.org/{package_name}')
        metadata_response = self._dispatch(metadata_url, MAX_METADATA_BYTES, 'metadata')
        if metadata_response.status == 404:
            return None

        try:
            payload = json.loads(metadata_response.body.decode('utf-8', errors='strict'),
                                  object_pairs_hook=_reject_duplicate_keys,parse_constant=lambda _value:(_ for _ in ()).throw(ValueError('INVALID_JSON_CONSTANT')))
        except (UnicodeDecodeError, ValueError):
            self.budget.stop('REGISTRY_METADATA_INVALID')
            raise BudgetStopped('REGISTRY_METADATA_INVALID') from None
        if not isinstance(payload, dict):
            self.budget.stop('REGISTRY_METADATA_INVALID')
            raise BudgetStopped('REGISTRY_METADATA_INVALID')

        try:
            selection = (_select_wheel(payload,package_name,self.request.as_of) if artifact_format=='wheel'
                         else _select_npm(payload,package_name,self.request.as_of))
        except (ValueError,TypeError,KeyError):
            self.budget.stop('REGISTRY_METADATA_INVALID');raise BudgetStopped('REGISTRY_METADATA_INVALID') from None
        if selection is None:
            return None
        artifact_url, file_metadata = selection

        artifact_cap = MAX_WHEEL_BYTES if artifact_format == 'wheel' else MAX_NPM_BYTES
        artifact_response = self._dispatch(artifact_url, artifact_cap, 'artifact')
        if artifact_response.status == 404:
            return None

        artifact_bytes = artifact_response.body
        try:
            if artifact_format == 'wheel':
                verify_wheel_source(artifact_bytes, file_metadata, package_name, self.request)
            else:
                verify_npm_source(artifact_bytes, file_metadata, package_name, self.request)
        except ValueError:
            self.budget.stop('REGISTRY_ARTIFACT_INVALID')
            raise BudgetStopped('REGISTRY_ARTIFACT_INVALID') from None

        return dict(artifact_bytes=artifact_bytes, file_metadata=file_metadata,
                    expected_package=package_name, artifact_format=artifact_format)
