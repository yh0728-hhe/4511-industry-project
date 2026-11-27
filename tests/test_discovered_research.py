"""Offline tests for discovered-URL re-verification and the discovery provider.

Everything here is invented fixture data; no real CLI/HTTP/model is used and
no current-page fetch is permitted. These only exercise the existing
domain-anchored archived-website capability extended to externally
discovered leads -- a general third-party original-publication verifier is
still out of scope and NOT claimed complete here.
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
from closed_loop.web_discovery import DiscoveryResult

DOMAIN = 'synthetic.example'
GOOD_URL = 'https://' + DOMAIN + '/pricing'


def discovery_result(urls=(), status=None):
    status = status if status is not None else ('HELD_FOR_VERIFICATION' if urls else 'NO_LEADS')
    return DiscoveryResult(status=status, source_urls=tuple(urls), admitted_fact_count=0,
        historical_availability='UNVERIFIED', verified=False, managed_http='UNKNOWN',
        observed_websearch_count=1, budget_snapshot={}, resource_unit_note='n/a')


class FakeDiscoveryAgent:
    def __init__(self, bound_request, budget, result=None, exc=None):
        self.request = bound_request
        self.call_budget = budget
        self.result = result
        self.exc = exc
        self.calls = 0

    def discover(self, task):
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return self.result


class DiscoveryHTTP:
    """Serves CDX/replay for an exact domain; everything else is invented."""
    def __init__(self, restrict_path=None, restrict_status=429, bad_memento=False, future_path=None):
        self.calls = []
        self.restrict_path = restrict_path
        self.restrict_status = restrict_status
        self.bad_memento = bad_memento
        self.future_path = future_path

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        check_deadline()
        self.calls.append(url)
        if self.restrict_path and self.restrict_path in url and '/cdx/' not in url:
            return HTTPResponse(self.restrict_status, url, {}, b'')
        if '/cdx/' in url:
            original = 'https://' + parse_qs(urlparse(url).query)['url'][0]
            ts = '20250320000000' if self.future_path and original.endswith(self.future_path) else '20240320000000'
            return HTTPResponse(200, url, {}, json.dumps([
                ['timestamp', 'original', 'statuscode', 'mimetype'],
                [ts, original, '200', 'text/html']]).encode())
        text = ('Invented discovered-lead content for provider verification tests. ' * 2)
        memento = 'Thu, 21 Mar 2024 00:00:00 GMT' if self.bad_memento else 'Wed, 20 Mar 2024 00:00:00 GMT'
        return HTTPResponse(200, url, {'Memento-Datetime': memento, 'Content-Type': 'text/html'}, text.encode())


def build(client=None, max_sources=3, cap=10):
    req = request(max_search_calls=cap, max_model_calls=cap)
    budget = CallBudget(req)
    gateway = TemporalGateway(req, [])
    archive = ArchivedWebsiteProvider(req, gateway, budget, client=client or DiscoveryHTTP(), max_requests=cap)
    return req, budget, gateway, archive


def task(req, subject=None, question='Find a discovered business fact'):
    return ResearchRequest('other', question, req.company.company_id, subject)


class VerifyDiscoveredUrlTests(unittest.TestCase):
    def test_oncanchor_path_requires_exact_cdx_and_matching_memento(self):
        req, budget, gateway, archive = build()
        candidate = archive.verify_discovered_url(task(req), GOOD_URL)
        self.assertIsNotNone(candidate)
        self.assertTrue(candidate.url.endswith('/pricing'))

    def test_foreign_domain_zero_http_no_facts(self):
        req, budget, gateway, archive = build()
        client = archive.client
        candidate = archive.verify_discovered_url(task(req), 'https://foreign.example/pricing')
        self.assertIsNone(candidate)
        self.assertEqual(client.calls, [])

    def test_future_capture_excluded(self):
        req, budget, gateway, archive = build(DiscoveryHTTP(future_path='/pricing'))
        candidate = archive.verify_discovered_url(task(req), GOOD_URL)
        self.assertIsNone(candidate)

    def test_substituted_memento_blocked(self):
        req, budget, gateway, archive = build(DiscoveryHTTP(bad_memento=True))
        candidate = archive.verify_discovered_url(task(req), GOOD_URL)
        self.assertIsNone(candidate)

    def test_malformed_url_variants_rejected_without_http(self):
        req, budget, gateway, archive = build()
        client = archive.client
        for bad in ('https://user:secret@' + DOMAIN + '/pricing', 'ftp://' + DOMAIN + '/pricing',
                    'https://' + DOMAIN + ':8443/pricing', 'https://www.' + DOMAIN + '/pricing',
                    'https://' + DOMAIN + '/pricing#frag', 'https://' + DOMAIN + '/../secret',
                    'https://' + DOMAIN + '/' + 'x' * 600):
            with self.subTest(bad=bad):
                self.assertIsNone(archive.verify_discovered_url(task(req), bad))
        self.assertEqual(client.calls, [])

    def test_context_mismatch_raises(self):
        req, budget, gateway, archive = build()
        with self.assertRaises(ValueError):
            archive.verify_discovered_url(ResearchRequest('other', 'q', 'OTHER_COMPANY'), GOOD_URL)


class DiscoveredResearchProviderTests(unittest.TestCase):
    def test_full_cycle_admits_verified_discovered_fact(self):
        req, budget, gateway, archive = build()
        agent_holder = {}
        def factory(t):
            agent = FakeDiscoveryAgent(req, budget, discovery_result([GOOD_URL]))
            agent_holder['agent'] = agent
            return agent
        provider = DiscoveredResearchProvider(req, gateway, budget, factory, archive)
        candidates = provider.search(task(req))
        self.assertEqual(len(candidates), 1)
        fact, rejection = gateway.admit(candidates[0])
        self.assertIsNotNone(fact)
        self.assertEqual(agent_holder['agent'].calls, 1)
        self.assertTrue(any(row['event'] == 'DISCOVERED_SOURCE_VERIFIED' for row in provider.trace))

    def test_no_leads_zero_http(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result([])), archive)
        candidates = provider.search(task(req))
        self.assertEqual(candidates, ())
        self.assertEqual(archive.client.calls, [])

    def test_malformed_discovery_result_rejected(self):
        req, budget, gateway, archive = build()
        for bad in (object(), discovery_result([GOOD_URL], status='MADE_UP')):
            with self.subTest(bad=bad):
                provider = DiscoveredResearchProvider(req, gateway, budget,
                    lambda t, bad=bad: FakeDiscoveryAgent(req, budget, bad), archive)
                with self.assertRaisesRegex(BudgetStopped,'MALFORMED_DISCOVERY_RESULT'):
                    provider.search(task(req))
                self.assertEqual(provider.trace[-1]['reason'], 'MALFORMED_DISCOVERY_RESULT')
                req, budget, gateway, archive = build()

    def test_foreign_domain_lead_held_no_facts(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result(['https://foreign.example/pricing'])),
            archive)
        candidates = provider.search(task(req))
        self.assertEqual(candidates, ())
        self.assertTrue(any(row['event'] == 'DISCOVERED_URL_HELD' for row in provider.trace))
        self.assertEqual(archive.client.calls, [])

    def test_restriction_terminal_no_second_url(self):
        req, budget, gateway, archive = build(DiscoveryHTTP(restrict_path='/pricing'))
        other_url = 'https://' + DOMAIN + '/team'
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result([GOOD_URL, other_url])), archive)
        candidates = provider.search(task(req))
        self.assertEqual(candidates, ())
        self.assertTrue(budget.stopped)
        self.assertNotIn(other_url, archive.client.calls)
        with self.assertRaises(BudgetStopped):
            provider.search(task(req))

    def test_context_mismatch_rejected(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result([GOOD_URL])), archive)
        with self.assertRaises(ValueError):
            provider.search(ResearchRequest('other', 'q', 'OTHER_COMPANY'))

    def test_max_sources_cap_limits_verification_attempts(self):
        req, budget, gateway, archive = build(max_sources=1)
        urls = [GOOD_URL, 'https://' + DOMAIN + '/team', 'https://' + DOMAIN + '/about']
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result(urls)), archive, max_sources=1)
        provider.search(task(req))
        self.assertEqual(sum(1 for c in archive.client.calls if '/cdx/' not in c), 1)

    def test_discovery_agent_stop_preserves_no_partial_facts(self):
        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, exc=BudgetStopped('WEB_DISCOVERY_WEBSEARCH_COUNT')), archive)
        candidates = provider.search(task(req))
        self.assertEqual(candidates, ())
        self.assertTrue(budget.stopped)

    def test_constructor_rejects_separate_budget_or_gateway(self):
        req, budget, gateway, archive = build()
        other_budget = CallBudget(req)
        with self.assertRaises(ValueError):
            DiscoveredResearchProvider(req, gateway, other_budget,
                lambda t: FakeDiscoveryAgent(req, other_budget, discovery_result([])), archive)
        with self.assertRaises(ValueError):
            DiscoveredResearchProvider(req, TemporalGateway(req, []), budget,
                lambda t: FakeDiscoveryAgent(req, budget, discovery_result([])), archive)

    def test_cache_namespace_is_deterministic_not_factory_repr(self):
        req, budget, gateway, archive = build()
        provider_a = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result([])), archive)
        provider_b = DiscoveredResearchProvider(req, gateway, budget,
            lambda task: FakeDiscoveryAgent(req, budget, discovery_result([])), archive)
        self.assertEqual(provider_a.cache_namespace, provider_b.cache_namespace)

    def test_runtime_integration_with_fixture_lead_committee_and_discovery_double(self):
        from closed_loop.runtime import ClosedLoopRuntime

        class DiscoveryOnlyLead:
            def select(self, req, gaps):
                return (task(req, question='Inspect discovered pricing fact'),)

        class AcceptingCommittee:
            def evaluate(self, view):
                from closed_loop.contracts import CommitteeResult, Decision
                ids = tuple(row['fact_id'] for row in view.qa_pairs)
                if not ids:
                    return CommitteeResult(Decision.MORE_DILIGENCE, 'No evidence yet.', ('pricing',),
                        view.fact_revision, view.argument_revision, ())
                return CommitteeResult(Decision.INVEST, 'Discovered pricing fact supports investment.',
                    (), view.fact_revision, view.argument_revision, ids)

        req, budget, gateway, archive = build()
        provider = DiscoveredResearchProvider(req, gateway, budget,
            lambda t: FakeDiscoveryAgent(req, budget, discovery_result([GOOD_URL])), archive)
        runtime = ClosedLoopRuntime(req, gateway, budget, DiscoveryOnlyLead(), AcceptingCommittee(), provider)
        result = runtime.run()
        self.assertEqual(result['decision'], 'INVEST')
        self.assertEqual(len(result['admitted_fact_ids']), 1)


    def test_partial_evidence_survives_later_http_budget_stop(self):
        req,budget,gateway,archive=build(cap=2)
        provider=DiscoveredResearchProvider(req,gateway,budget,
            lambda t:FakeDiscoveryAgent(req,budget,discovery_result([GOOD_URL,'https://'+DOMAIN+'/team'])),archive)
        candidates=provider.search(task(req))
        self.assertEqual(len(candidates),1)
        self.assertEqual(budget.stop_reason,'HTTP_REQUEST_CAP')
        self.assertTrue(budget.stopped)
        self.assertIsNotNone(gateway.admit(candidates[0])[0])

    def test_fake_verified_or_dated_discovery_cannot_skip_verifier(self):
        from dataclasses import replace
        for changes in ({'verified':True},{'historical_availability':'VERIFIED'},
                        {'source_urls':(GOOD_URL,GOOD_URL)}, {'admitted_fact_count':True}):
            req,budget,gateway,archive=build()
            bad=replace(discovery_result([GOOD_URL]),**changes)
            provider=DiscoveredResearchProvider(req,gateway,budget,
                lambda t:FakeDiscoveryAgent(req,budget,bad),archive)
            with self.assertRaisesRegex(BudgetStopped,'MALFORMED_DISCOVERY_RESULT'):provider.search(task(req))
            self.assertEqual(archive.client.calls,[])

    def test_real_managed_adapter_composed_with_archive_and_runtime(self):
        import tempfile
        from closed_loop.web_discovery import ManagedWebDiscoveryAgent
        from closed_loop.runtime import ClosedLoopRuntime
        from closed_loop.fixtures import FixtureCommittee
        from test_web_discovery import stream
        # Host events are synthetic; actual adapter accounting/parsing is exercised.
        raw=stream().replace(b'https://example.org/historical-source',GOOD_URL.encode())
        class ProcessDouble:
            def __init__(self):self.calls=0
            def run(self,*args):self.calls+=1;return 0,raw,b''
        class Lead:
            def select(self,req,gaps):return (task(req),)
        req,budget,gateway,archive=build(cap=12)
        proc=ProcessDouble()
        with tempfile.TemporaryDirectory() as temp:
            def factory(t):return ManagedWebDiscoveryAgent(req,budget,approved=True,
                executable_path='injected-no-process',output_dir=Path(temp)/'one',executor=proc)
            provider=DiscoveredResearchProvider(req,gateway,budget,factory,archive)
            result=ClosedLoopRuntime(req,gateway,budget,Lead(),FixtureCommittee(),provider).run()
        self.assertEqual(len(result['admitted_fact_ids']),1)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(proc.calls,1)
        self.assertEqual(budget.used['search'],3) # one managed invocation + two direct archive HTTP
        self.assertEqual(len(archive.client.calls),2)
        self.assertEqual(budget.active,0)

    def test_archive_non_numeric_port_encoded_traversal_and_whitespace_held(self):
        req,budget,gateway,archive=build()
        for url in ('https://'+DOMAIN+':bad/pricing','https://'+DOMAIN+'/%2e%2e/secret',
                    'https://'+DOMAIN+'/white space','https://'+DOMAIN+':80/pricing'):
            self.assertIsNone(archive.verify_discovered_url(task(req),url))
        self.assertEqual(archive.client.calls,[])

    def test_cache_configuration_changes_do_not_reuse_other_provider(self):
        req,budget,gateway,archive=build()
        a=DiscoveredResearchProvider(req,gateway,budget,lambda t:None,archive,max_sources=1)
        b=DiscoveredResearchProvider(req,gateway,budget,lambda t:None,archive,max_sources=2)
        self.assertNotEqual(a.cache_namespace,b.cache_namespace)


    def test_index_www_alias_is_not_automatically_same_discovered_target(self):
        class Aliased(DiscoveryHTTP):
            def get(self,url,*args,**kwargs):
                r=super().get(url,*args,**kwargs)
                if '/cdx/' in url:
                    rows=json.loads(r.body);rows[1][1]=rows[1][1].replace('synthetic.example','www.synthetic.example')
                    return HTTPResponse(r.status,r.url,r.headers,json.dumps(rows).encode())
                return r
        req,budget,gateway,archive=build(Aliased())
        self.assertIsNone(archive.verify_discovered_url(task(req),GOOD_URL))
        self.assertEqual(len(archive.client.calls),1)

    def test_index_added_trailing_slash_does_not_substitute_exact_discovered_url(self):
        class DifferentPath(DiscoveryHTTP):
            def get(self,url,*args,**kwargs):
                r=super().get(url,*args,**kwargs)
                if '/cdx/' in url:
                    rows=json.loads(r.body);rows[1][1]+='/'
                    return HTTPResponse(r.status,r.url,r.headers,json.dumps(rows).encode())
                return r
        req,budget,gateway,archive=build(DifferentPath())
        self.assertIsNone(archive.verify_discovered_url(task(req),GOOD_URL))
        self.assertEqual(len(archive.client.calls),1)

    def test_foreign_search_hits_do_not_starve_later_verifiable_official_url(self):
        req,budget,gateway,archive=build()
        urls=['https://publisher.example/article','https://github.com/fixture/repo',GOOD_URL]
        provider=DiscoveredResearchProvider(req,gateway,budget,
            lambda t:FakeDiscoveryAgent(req,budget,discovery_result(urls)),archive,max_sources=1)
        candidates=provider.search(task(req))
        self.assertEqual(len(candidates),1)
        self.assertEqual(len(archive.client.calls),2)
        held=[x for x in provider.trace if x['event']=='DISCOVERED_URL_HELD']
        self.assertEqual(len(held),2)
        self.assertTrue(all(x['reason']=='INDEPENDENT_PUBLISHER_OR_IDENTITY_VERIFIER_REQUIRED' for x in held))


if __name__ == '__main__':
    unittest.main()
