"""Import-safe child worker: one bounded archive GET, no retries/fallback.

Runs in a separate process so a hung DNS/connect/read can be killed by the
parent's process-group timeout instead of outliving the socket timeout.
"""
import base64
import json
import sys
import time

_STDIN_CAP = 8193


def _read_request(stream):
    raw = stream.read(_STDIN_CAP)
    if len(raw) >= _STDIN_CAP:
        raise ValueError('STDIN_TOO_LARGE')
    from .archive_process import _reject_duplicate_keys
    from .archive_transport import archive_url_allowed
    payload = json.loads(raw.decode('utf-8'),object_pairs_hook=_reject_duplicate_keys,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    if not isinstance(payload, dict) or set(payload.keys()) != {'url', 'timeout', 'max_bytes'}:
        raise ValueError('MALFORMED_REQUEST')
    url = payload['url']
    timeout = payload['timeout']
    max_bytes = payload['max_bytes']
    if not isinstance(url, str) or not archive_url_allowed(url):
        raise ValueError('MALFORMED_REQUEST')
    if type(timeout) is bool or type(timeout) not in (int, float):
        raise ValueError('MALFORMED_REQUEST')
    if not (0 < timeout <= 60):
        raise ValueError('MALFORMED_REQUEST')
    if type(max_bytes) is not int or not (1 <= max_bytes <= 1_048_576):
        raise ValueError('MALFORMED_REQUEST')
    return url, timeout, max_bytes


def main():
    try:
        url, timeout, max_bytes = _read_request(sys.stdin.buffer)
        from .archive_transport import ArchiveHTTPClient

        deadline = time.monotonic() + timeout

        def check_deadline():
            if time.monotonic() > deadline:
                raise TimeoutError('WORKER_DEADLINE_EXCEEDED')

        response = ArchiveHTTPClient().get(url, timeout, max_bytes, check_deadline=check_deadline)
        headers = dict(response.headers)
        if len(json.dumps(headers, separators=(',', ':'))) > 65536:
            raise ValueError('HEADERS_TOO_LARGE')
        body_b64 = base64.b64encode(response.body).decode('ascii')
        envelope = dict(status='ok', http_status=response.status, url=response.url,
                         headers=headers, body_b64=body_b64)
        sys.stdout.buffer.write(json.dumps(envelope, separators=(',', ':')).encode('utf-8'))
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        try:
            sys.stdout.buffer.write(json.dumps(dict(status='error', error='ARCHIVE_WORKER_FAILED'),
                                                separators=(',', ':')).encode('utf-8'))
            sys.stdout.buffer.flush()
        except Exception:
            pass
        return 2


if __name__ == '__main__':
    sys.exit(main())
