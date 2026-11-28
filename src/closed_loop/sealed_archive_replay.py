"""Opt-in sealed local Wayback response replay; never a network fallback.

A trusted operator pins the manifest digest from an audited acquisition. A
caller-provided hash authenticates neither transport nor past public availability.
This returns HTTPResponse bytes only; the existing archive/identity/temporal
verifiers must still run. No facts, ledger records, models or outcomes are made.
"""
import hashlib
import json
from pathlib import Path
import re

from .archive_transport import HTTPResponse, archive_url_allowed
from .guards import BudgetStopped


def _strict_pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('DUPLICATE_REPLAY_KEY')
        result[key] = value
    return result


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('SEALED_REPLAY_INPUT_TOO_LARGE')
    return raw


class SealedArchiveReplayClient:
    """Exact URL allowlist, bounded disk reads, no network/import-side I/O."""
    actual_http_requests = 0

    def __init__(self, manifest_path, *, trusted_manifest_sha256, max_gets=12):
        if not isinstance(trusted_manifest_sha256, str) or re.fullmatch(r'[a-f0-9]{64}', trusted_manifest_sha256) is None:
            raise ValueError('EXPLICIT_TRUSTED_MANIFEST_DIGEST_REQUIRED')
        if type(max_gets) is not int or not 1 <= max_gets <= 24:
            raise ValueError('BOUNDED_REPLAY_COUNT_REQUIRED')
        manifest_path = Path(manifest_path).resolve(strict=True)
        raw = _read(manifest_path, 65536)
        if hashlib.sha256(raw).hexdigest() != trusted_manifest_sha256:
            raise ValueError('SEALED_REPLAY_MANIFEST_CHANGED')
        manifest = json.loads(raw.decode('utf-8'), object_pairs_hook=_strict_pairs,
                              parse_constant=lambda v: (_ for _ in ()).throw(ValueError('NONFINITE_REPLAY_VALUE')))
        if (not isinstance(manifest, dict) or set(manifest) != {'version', 'responses'} or
                type(manifest['version']) is not int or manifest['version'] != 1 or
                not isinstance(manifest['responses'], list) or not 1 <= len(manifest['responses']) <= 12):
            raise ValueError('EXACT_SEALED_REPLAY_MANIFEST_REQUIRED')
        self._root = manifest_path.parent
        self._entries = {}
        for row in manifest['responses']:
            if not isinstance(row, dict) or set(row) != {'request_url', 'status', 'response_url', 'headers', 'body_file', 'body_sha256'}:
                raise ValueError('EXACT_SEALED_REPLAY_ENTRY_REQUIRED')
            url = row['request_url']
            if not isinstance(url, str) or len(url) > 4096 or not archive_url_allowed(url) or url in self._entries:
                raise ValueError('INVALID_OR_DUPLICATE_REPLAY_URL')
            if row['response_url'] != url or type(row['status']) is not int or not 100 <= row['status'] <= 599:
                raise ValueError('INVALID_SEALED_REPLAY_RESPONSE')
            headers = row['headers']
            if (not isinstance(headers, dict) or len(headers) > 100 or
                    any(not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()) or
                    len(json.dumps(headers)) > 65536):
                raise ValueError('INVALID_SEALED_REPLAY_HEADERS')
            if not isinstance(row['body_sha256'], str) or re.fullmatch(r'[a-f0-9]{64}', row['body_sha256']) is None:
                raise ValueError('BODY_DIGEST_REQUIRED')
            filename = row['body_file']
            if not isinstance(filename, str) or re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}', filename) is None:
                raise ValueError('LOCAL_REPLAY_BASENAME_REQUIRED')
            path = (self._root / filename).resolve(strict=True)
            if not path.is_relative_to(self._root) or not path.is_file():
                raise ValueError('REPLAY_BODY_OUTSIDE_ROOT')
            # Headers are copied out on get(), never returned by reference.
            self._entries[url] = dict(row, body_path=path)
        self.max_gets = max_gets
        self._count = 0
        self.events = []
        self.manifest_sha256 = trusted_manifest_sha256

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        if (not isinstance(url, str) or len(url) > 4096 or not archive_url_allowed(url) or
                type(timeout) not in (int, float) or not 0 < timeout <= 60 or
                type(max_bytes) is not int or not 1 <= max_bytes <= 1048576):
            raise ValueError('INVALID_REPLAY_GET_BOUNDS')
        check_deadline()
        if self._count >= self.max_gets:
            raise BudgetStopped('SEALED_REPLAY_CALL_CAP')
        self._count += 1
        event = dict(call=self._count, request_url_sha256=hashlib.sha256(url.encode()).hexdigest(),
                     status='STARTED', actual_http_requests=0)
        self.events.append(event)
        try:
            if url not in self._entries:
                raise BudgetStopped('SEALED_REPLAY_CACHE_MISS')
            row = self._entries[url]
            # Re-resolve and re-hash on every read: post-construction changes hold.
            path = (self._root / row['body_file']).resolve(strict=True)
            if path != row['body_path'] or not path.is_relative_to(self._root):
                raise ValueError('SEALED_REPLAY_BODY_CHANGED')
            body = _read(path, max_bytes)
            if hashlib.sha256(body).hexdigest() != row['body_sha256']:
                raise ValueError('SEALED_REPLAY_BODY_CHANGED')
            check_deadline()
            response = HTTPResponse(row['status'], row['response_url'], dict(row['headers']), body)
        except Exception as exc:
            event.update(status='HELD', error_type=type(exc).__name__)
            raise
        event.update(status='REPLAYED', body_sha256=row['body_sha256'], bytes=len(body))
        return response
