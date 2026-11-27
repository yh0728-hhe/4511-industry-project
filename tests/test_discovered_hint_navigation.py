"""Offline tests: discovered-research hint forwarding and archived-path reuse.

All content/URLs below are invented fixtures; no real CLI/HTTP/model is used.
These only exercise reuse of the existing ArchivedWebsiteProvider link_hints
and search on an already-observed path -- no new discovery or current-page
fallback capability is introduced or claimed here.
"""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider, HTTPResponse
from closed_loop.contracts import ResearchRequest
from closed_loop.discovered_research import DiscoveredResearchProvider
from closed_loop.fixtures import request
from closed_loop.guards import BudgetStopped, CallBudget, TemporalGateway

DOMAIN = 'synthetic.example'


class HintNavigationHTTP:
    """Serves a homepage with discoverable links and a pricing page."""
    def __init__(self, restrict_pricing=False):
        self.calls = []
        self.restrict_pricing = restrict_pricing

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        check_deadline()
        self.calls.append(url)
        if self.restrict_pricing and url.endswith('/pricing') and '/cdx/' not in url:
            return HTTPResponse(429, url, {}, b'')
        if '/cdx/' in url:
            original = 'https://' + parse_qs(urlparse(url).query)['url'][0]
            return HTTPResponse(200, url, {}, json.dumps([
                ['timestamp', 'original', 'statuscode', 'mimetype'],
                ['20240320000000', original, '200', 'text/html']]).encode())
        text = 'Invented historical homepage/pricing content for hint navigation tests. ' * 2
        if url.endswith('/pricing'):
            text += ' Pricing is ten synthetic units per month.'
        else:
            text += '<a href="/pricing">Pricing plans</a>'
        return HTTPResponse(200, url, {'Memento-Datetime': 'Wed, 20 Mar 2024 00:00:00 GMT',
                                        'Content-Type': 'text/html'}, text.encode())


def build(client=None, cap=10):
    req = request(max_search_calls=cap, max_model_calls=cap)
    budget = CallBudget(req)
    gateway = TemporalGateway(req, [])
    archive = ArchivedWebsiteProvider(req, gateway, budget, client=client or HintNavigationHTTP(), max_requests=cap)
    return req, budget, gateway, archive


def task(req, source_path=None, question='Find a discovered business fact'):
    return ResearchRequest('other', question, req.company.company_id, source_path=source_path)


class FactorySpy:
    def __init__(self):
        self.calls = 0

    def __call__(self, t):
        self.calls += 1
        raise AssertionError('managed discovery factory must not be used for an observed-path route')


class DiscoveredHintNavigationTests(unittest.TestCase):
    def test_archive_bootstrap_then_observed_pricing_two_new_http_zero_factory(self):
        req, budget, gateway, archive = build()
        spy = FactorySpy()
        provider = DiscoveredResearchProvider(req, gateway, budget, spy, archive)
        provider.search(task(req, source_path='/'))
        self.assertEqual(spy.calls, 0)
        self.assertEqual(len(archive.client.calls), 2)
        candidates = provider.search(task(req, source_path='/pricing'))
        self.assertEqual(spy.calls, 0)
        self.assertTrue(any(c.url.endswith('/pricing') for c in candidates))
        self.assertEqual(len(archive.client.calls), 4)

    def test_link_hints_forward_dates_and_unverified_flag(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget, lambda t: None, archive)
        provider.search(task(req, source_path='/'))
        hints = provider.link_hints()
        self.assertEqual(hints, archive.link_hints())
        self.assertTrue(hints)
        for hint in hints:
            self.assertFalse(hint['target_content_verified'])
            self.assertIn('observed_at', hint)

    def test_unobserved_path_never_fetched_no_fallback(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget, lambda t: None, archive)
        provider.search(task(req, source_path='/'))
        before = len(archive.client.calls)
        candidates = provider.search(task(req, source_path='/unseen'))
        self.assertEqual(len(archive.client.calls), before)
        self.assertTrue(all(not c.url.endswith('/unseen') for c in candidates))

    def test_restriction_terminal_preserves_prior_root_candidate(self):
        req, budget, gateway, archive = build(HintNavigationHTTP(restrict_pricing=True))
        provider = DiscoveredResearchProvider(req, gateway, budget, lambda t: None, archive)
        provider.search(task(req, source_path='/'))
        candidates = provider.search(task(req, source_path='/pricing'))
        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0].url.endswith('/'))
        self.assertTrue(budget.stopped)
        self.assertEqual(budget.stop_reason, 'ARCHIVE_RATE_LIMITED')

    def test_already_stopped_budget_blocks_before_factory_or_client(self):
        req, budget, gateway, archive = build()
        spy = FactorySpy()
        provider = DiscoveredResearchProvider(req, gateway, budget, spy, archive)
        budget.stop('PRE_STOPPED_TEST_REASON')
        with self.assertRaises(BudgetStopped):
            provider.search(task(req, source_path='/pricing'))
        self.assertEqual(spy.calls, 0)
        self.assertEqual(archive.client.calls, [])

    def test_runtime_select_with_context_receives_hints_and_chooses_observed_path(self):
        from closed_loop.runtime import ClosedLoopRuntime
        from closed_loop.fixtures import FixtureCommittee

        req, budget, gateway, archive = build()
        spy = FactorySpy()
        provider = DiscoveredResearchProvider(req, gateway, budget, spy, archive)
        provider.search(task(req, source_path='/'))
        seen_hints = []

        class HintPickingLead:
            def select_with_context(self, req, gaps, qa_pairs, hints, fact_revision=0):
                seen_hints.append(hints)
                path = hints[0]['path'] if hints else '/'
                return (ResearchRequest('other', 'Inspect discovered pricing fact', req.company.company_id,
                                         source_path=path),)

        runtime = ClosedLoopRuntime(req, gateway, budget, HintPickingLead(), FixtureCommittee(), provider)
        result = runtime.run()
        self.assertTrue(seen_hints)
        self.assertTrue(any(h['path'] == '/pricing' for h in seen_hints[0]))
        self.assertEqual(spy.calls, 0)
        self.assertEqual(len(result['admitted_fact_ids']), 2)
        self.assertEqual(len(archive.client.calls),4)

    def test_new_managed_discovery_root_then_hint_reuses_cached_root_without_rediscovery(self):
        from test_discovered_research import FakeDiscoveryAgent, discovery_result
        req,budget,gateway,archive=build()
        made=[]
        def factory(t):
            made.append(t)
            return FakeDiscoveryAgent(req,budget,discovery_result(['https://'+DOMAIN+'/']))
        provider=DiscoveredResearchProvider(req,gateway,budget,factory,archive)
        initial=provider.search(task(req))
        self.assertEqual(len(initial),1)
        self.assertEqual(len(archive.client.calls),2)
        self.assertTrue(provider.link_hints())
        follow=provider.search(task(req,source_path='/pricing'))
        self.assertEqual(len(made),1)
        self.assertEqual(len(archive.client.calls),4)
        self.assertEqual(len(follow),2)
        self.assertTrue(any(c.url.endswith('/pricing') for c in follow))


if __name__ == '__main__':
    unittest.main()
