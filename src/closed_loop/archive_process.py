"""Process-isolated archive HTTP transport.

Raw urllib timeouts bound individual socket operations, not the entire
DNS/connect/header/read sequence; cumulative setup may outlive that timeout. Running the request in a child process lets
the parent's ProcessExecutor kill the whole process group on a bounded
outer deadline, instead of trusting the raw client to ever return.
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

from .cli_backend import ProcessExecutor
from .guards import BudgetStopped
from .archive_transport import RetrievalFailed, archive_url_allowed

def _reject_duplicate_keys(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result

_SRC_ROOT = str(Path(__file__).resolve().parent.parent)
_MAX_HEADERS_BYTES = 65536


def _bootstrap_argv():
    bootstrap = (
        f'import sys,runpy;sys.path.insert(0,{_SRC_ROOT!r});'
        "runpy.run_module('closed_loop.archive_worker',run_name='__main__')"
    )
    return [sys.executable, '-X', 'utf8', '-c', bootstrap]


class IsolatedArchiveHTTPClient:
    """One child process per get(); no retries, no fallback to an in-process call."""

    def __init__(self, executor=None):
        self.executor = executor if executor is not None else ProcessExecutor()

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        if not archive_url_allowed(url):
            raise RetrievalFailed('HOST_PATH_OR_BOUNDS_NOT_ALLOWED')
        if type(timeout) is bool or type(timeout) not in (int, float) or not (0 < timeout <= 60):
            raise RetrievalFailed('HOST_PATH_OR_BOUNDS_NOT_ALLOWED')
        if type(max_bytes) is not int or not (1 <= max_bytes <= 1_048_576):
            raise RetrievalFailed('HOST_PATH_OR_BOUNDS_NOT_ALLOWED')

        check_deadline()
        request_bytes = json.dumps(
            dict(url=url, timeout=timeout, max_bytes=max_bytes), separators=(',', ':')
        ).encode('utf-8')
        if len(request_bytes)>8192:raise RetrievalFailed('REQUEST_LIMIT')
        try:
            returncode, stdout, stderr = self.executor.run(_bootstrap_argv(), request_bytes, timeout)
        except subprocess.TimeoutExpired:
            check_deadline()
            raise BudgetStopped('ARCHIVE_REQUEST_TIMEOUT') from None
        except BudgetStopped:
            raise
        except Exception:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR') from None
        check_deadline()

        response = self._parse_response(returncode, stdout, url, max_bytes)
        check_deadline()
        return response

    @staticmethod
    def _parse_response(returncode, stdout, url, max_bytes):
        if type(returncode) is not int or returncode != 0:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if not isinstance(stdout, bytes) or len(stdout) > 2 * max_bytes + 131072:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        try:
            envelope = json.loads(stdout.decode('utf-8'),object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda value:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR') from None
        if not isinstance(envelope, dict) or envelope.get('status') != 'ok':
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if set(envelope.keys()) != {'status', 'http_status', 'url', 'headers', 'body_b64'}:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        http_status = envelope['http_status']
        response_url = envelope['url']
        headers = envelope['headers']
        body_b64 = envelope['body_b64']
        if type(http_status) is not int or not 100<=http_status<=599:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if not isinstance(response_url, str) or response_url != url:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if not isinstance(headers, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) for k, v in headers.items()
        ):
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if len(json.dumps(headers, separators=(',', ':'))) > _MAX_HEADERS_BYTES:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if not isinstance(body_b64, str):
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        try:
            body = base64.b64decode(body_b64, validate=True)
        except (ValueError, TypeError):
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR') from None
        if len(body) > max_bytes:
            raise RetrievalFailed('HTTP_TRANSPORT_ERROR')

        from .archive_transport import HTTPResponse
        return HTTPResponse(http_status, response_url, headers, body)
