"""Tests for src/closed_loop/source_preflight.py using injected HTTP only.

No real network or model call is made: ArchivedWebsiteProvider is constructed
with a fake HTTP client, and no LLM/backend object is ever created here.
"""
from dataclasses import replace
from datetime import timedelta
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import importlib
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider, HTTPResponse
from closed_loop.fixtures import request as fixture_request
from closed_loop.guards import CallBudget, TemporalGateway
from closed_loop import source_preflight
from closed_loop.source_preflight import PreflightState, source_readiness_preflight


class FakeHTTPClient:
    """Stands in for ArchiveHTTPClient; never touches a real socket."""

    def __init__(self, cdx_rows=(), restrict_status=None,
                 replay_status=200, replay_headers=None, replay_body=b''):
        self.cdx_rows = cdx_rows
        self.restrict_status = restrict_status
        self.replay_status = replay_status
        self.replay_headers = replay_headers or {}
        self.replay_body = replay_body
        self.calls = []

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        self.calls.append(url)
        if 'cdx/search/cdx' in url:
            if self.restrict_status is not None:
                return HTTPResponse(self.restrict_status, url, {}, b'')
            return HTTPResponse(200, url, {}, json.dumps(list(self.cdx_rows)).encode())
        return HTTPResponse(self.replay_status, url, self.replay_headers, self.replay_body)


DOMAIN = 'synthetic.example'
CAPTURE_WHEN = datetime(2024, 1, 1, tzinfo=timezone.utc)
CAPTURE_TS = '20240101000000'
ORIGINAL_URL = 'http://synthetic.example/'
REPLAY_BODY = ('<html><body>' + ('Historical homepage content. ' * 6) + '</body></html>').encode()


def admitted_fixture():
    return FakeHTTPClient(
        cdx_rows=[[CAPTURE_TS, ORIGINAL_URL, '200', 'text/html']],
        replay_headers={'Content-Type': 'text/html',
                        'Memento-Datetime': format_datetime(CAPTURE_WHEN, usegmt=True)},
        replay_body=REPLAY_BODY)


def build_env(client, max_search_calls=5):
    request = fixture_request(max_search_calls=max_search_calls)
    gateway = TemporalGateway(request, ())
    budget = CallBudget(request)
    provider = ArchivedWebsiteProvider(request, gateway, budget, client=client)
    return request, gateway, budget, provider


class ImportHasNoSideEffects(unittest.TestCase):
    def test_import_makes_no_network_call(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('must not be called')) as mocked:
            importlib.reload(source_preflight)
        self.assertEqual(mocked.call_count, 0)


class AdmittedSource(unittest.TestCase):
    def test_admits_homepage_and_is_ready(self):
        client = admitted_fixture()
        request, gateway, budget, provider = build_env(client)
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.ADMITTED_SOURCE)
        self.assertTrue(result.ready_for_dispatch)
        self.assertEqual(len(result.admitted_fact_ids), 1)
        self.assertIsNone(result.stop_reason)

    def test_repeated_preflight_reuses_cached_root(self):
        client = admitted_fixture()
        request, gateway, budget, provider = build_env(client)
        first = source_readiness_preflight(request, gateway, budget, provider)
        calls_after_first = list(client.calls)
        second = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(second.state, PreflightState.ADMITTED_SOURCE)
        self.assertEqual(second.admitted_fact_ids, first.admitted_fact_ids)
        self.assertEqual(client.calls, calls_after_first)


class NoAdmissibleSource(unittest.TestCase):
    def test_empty_index_is_not_restriction(self):
        client = FakeHTTPClient(cdx_rows=[])
        request, gateway, budget, provider = build_env(client)
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.NO_ADMISSIBLE_SOURCE)
        self.assertFalse(result.ready_for_dispatch)
        self.assertEqual(result.admitted_fact_ids, ())
        self.assertFalse(budget.stopped)


class RestrictedSource(unittest.TestCase):
    def test_http_403_is_access_restricted_and_blocked(self):
        client = FakeHTTPClient(restrict_status=403)
        request, gateway, budget, provider = build_env(client)
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.ACCESS_RESTRICTED)
        self.assertFalse(result.ready_for_dispatch)
        self.assertEqual(result.stop_reason, 'ARCHIVE_ACCESS_RESTRICTED')
        self.assertTrue(budget.stopped)

    def test_http_429_is_rate_limited_and_blocked(self):
        client = FakeHTTPClient(restrict_status=429)
        request, gateway, budget, provider = build_env(client)
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.RATE_LIMITED)
        self.assertFalse(result.ready_for_dispatch)
        self.assertEqual(result.stop_reason, 'ARCHIVE_RATE_LIMITED')


class BudgetStoppedFailures(unittest.TestCase):
    def test_call_cap_is_stopped_not_ready(self):
        client = admitted_fixture()
        request, gateway, budget, provider = build_env(client, max_search_calls=0)
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.STOPPED)
        self.assertFalse(result.ready_for_dispatch)
        self.assertEqual(result.stop_reason, 'CALL_CAP')
        self.assertTrue(budget.stopped)
        self.assertEqual(client.calls, [])

    def test_prior_stop_reason_is_preserved_first_cause(self):
        client = admitted_fixture()
        request, gateway, budget, provider = build_env(client)
        budget.stop('PRIOR_REASON')
        result = source_readiness_preflight(request, gateway, budget, provider)
        self.assertEqual(result.state, PreflightState.STOPPED)
        self.assertEqual(result.stop_reason, 'PRIOR_REASON')
        self.assertEqual(client.calls, [])


class ContextMismatch(unittest.TestCase):
    def test_mismatched_request_is_rejected(self):
        client = admitted_fixture()
        request, gateway, budget, provider = build_env(client)
        other_request = replace(request, mandate='different-mandate')
        with self.assertRaises(ValueError):
            source_readiness_preflight(other_request, gateway, budget, provider)

class ReviewerAcceptance(unittest.TestCase):
    def test_expired_cached_root_cannot_be_ready(self):
        client=admitted_fixture();request,gateway,budget,provider=build_env(client)
        source_readiness_preflight(request,gateway,budget,provider);before=len(client.calls)
        budget.clock=lambda:request.deadline+timedelta(seconds=1)
        result=source_readiness_preflight(request,gateway,budget,provider)
        self.assertFalse(result.ready_for_dispatch);self.assertEqual(result.stop_reason,'STOP_OR_DEADLINE')
        self.assertEqual(result.http_requests_delta,0);self.assertEqual(len(client.calls),before)

    def test_preflight_does_not_follow_matching_homepage_links(self):
        client=admitted_fixture();client.replay_body+=b'<a href="/historical-homepage">Historical homepage</a>'
        request,gateway,budget,provider=build_env(client)
        result=source_readiness_preflight(request,gateway,budget,provider)
        self.assertTrue(result.ready_for_dispatch);self.assertEqual(result.http_requests_delta,2)
        self.assertEqual(len(client.calls),2);self.assertFalse(result.historical_domain_ownership_independently_verified)
        self.assertNotIn('REQUESTED_PATH_NOT_OBSERVED_HISTORICALLY',[a['status'] for a in provider.attempts])

    def test_transport_failure_distinct_from_no_capture(self):
        from closed_loop.archive_transport import RetrievalFailed
        class BadHTTP:
            def get(self,*args,**kwargs):raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        request,gateway,budget,provider=build_env(BadHTTP())
        result=source_readiness_preflight(request,gateway,budget,provider)
        self.assertEqual(result.state,PreflightState.TRANSPORT_ERROR)
        self.assertFalse(result.ready_for_dispatch);self.assertEqual(result.http_requests_delta,1)


if __name__ == '__main__':
    unittest.main()
