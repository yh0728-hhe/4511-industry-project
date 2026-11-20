"""Offline admission, navigation, stop and nested accounting regressions."""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider, HTTPResponse
from closed_loop.contracts import ResearchRequest
from closed_loop.fixtures import request, source
from closed_loop.guards import BudgetStopped, CallBudget, TemporalGateway
from closed_loop.research_backend import MeteredResearchProvider, ResearchNavigationPlan


class HistoricalHTTP:
    def __init__(self, future_target=False):
        self.calls = []
        self.future_target = future_target

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        check_deadline()
        self.calls.append(url)
        if '/cdx/' in url:
            original = 'https://' + parse_qs(urlparse(url).query)['url'][0]
            ts = '20250320000000' if self.future_target and original.endswith('/pricing') else '20240320000000'
            return HTTPResponse(200, url, {}, json.dumps([
                ['timestamp', 'original', 'statuscode', 'mimetype'],
                [ts, original, '200', 'text/html']]).encode())
        text = 'Invented historical website content for navigation and admission tests. ' * 2
        if url.endswith('/pricing'):
            text += ' Pricing is ten synthetic units per month.'
        elif url.endswith('/team'):
            text += ' The synthetic founding team builds the fixture product.'
        else:
            text += '<a href="/pricing">Pricing plans</a><a href="/team">Our founders</a>'
        return HTTPResponse(200, url, {'Memento-Datetime': 'Wed, 20 Mar 2024 00:00:00 GMT',
                                      'Content-Type': 'text/html'}, text.encode())


class Planner:
    def __init__(self, plans=None):
        self.plans = list(plans or [ResearchNavigationPlan('FETCH', '/pricing')])
        self.calls = []

    def generate(self, schema, messages, temperature):
        self.calls.append((schema, messages))
        return self.plans.pop(0) if self.plans else ResearchNavigationPlan('STOP', None)


def setup(*, cap=10, model_cap=4, future_target=False, plans=None, steps=2):
    req = request(max_search_calls=cap, max_model_calls=model_cap)
    budget = CallBudget(req)
    gateway = TemporalGateway(req, [])
    client = HistoricalHTTP(future_target)
    archive = ArchivedWebsiteProvider(req, gateway, budget, client=client, max_requests=cap)
    backend = Planner(plans)
    provider = MeteredResearchProvider(req, gateway, budget, backend, archive,
                                       max_navigation_steps=steps)
    return provider, backend, client, budget, gateway


def task(question='Find a dated business fact'):
    # No rank-matching keyword: bootstrap reads only the homepage.
    return ResearchRequest('other', question, 'SYNTHETIC_COMPANY')


class ResearchBackendTests(unittest.TestCase):
    def test_iterative_model_selection_retrieves_and_readmits_historical_target(self):
        provider, backend, client, budget, gateway = setup()
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(budget.used, {'model': 2, 'search': 4})
        self.assertEqual(len(backend.calls), 2)
        self.assertTrue(any('ten synthetic units' in candidate.text for candidate in candidates))
        self.assertTrue(all(gateway.admit(candidate)[0] is not None for candidate in candidates))
        prompt = json.loads(backend.calls[0][1][-1].content)
        self.assertEqual({hint['path'] for hint in prompt['historical_link_hints']}, {'/pricing', '/team'})
        self.assertTrue(all(not hint['target_content_verified'] for hint in prompt['historical_link_hints']))
        self.assertEqual(provider.trace[-1]['reason'], 'MODEL_STOP')

    def test_model_cannot_invent_or_switch_to_current_url(self):
        for path in ['/unseen', 'https://current.example/funding', '//evil.example/path']:
            with self.subTest(path=path):
                provider, _, client, budget, _ = setup(plans=[ResearchNavigationPlan('FETCH', path)])
                candidates = provider.search(task())
                self.assertEqual(len(candidates), 1)
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(budget.used['model'], 1)
                self.assertEqual(provider.trace[-1]['reason'], 'RESEARCH_PLAN_NOT_OBSERVED')

    def test_future_target_never_becomes_evidence_or_planner_context(self):
        provider, backend, client, budget, _ = setup(future_target=True)
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(budget.used['search'], 3)
        self.assertFalse(any('/pricing' in row['original_url'] for row in provider.receipts))
        self.assertFalse(any('ten synthetic units' in message.content
                             for _, messages in backend.calls for message in messages))

    def test_rejected_future_identity_and_unverified_candidates_never_reach_planner(self):
        provider, backend, client, _, gateway = setup()
        future, future_record = source('future', 'topic', 'SECRET_FUTURE_MARKER',
                                       available='2025-01-01T00:00:00Z')
        peer, peer_record = source('peer', 'topic', 'SECRET_PEER_MARKER', company_id='OTHER_COMPANY')
        # Fixture helper only alters the record: align the candidate to the peer.
        from dataclasses import replace
        peer = replace(peer, company_id='OTHER_COMPANY')
        unverified, _ = source('unknown', 'topic', 'SECRET_UNVERIFIED_MARKER')
        gateway.register_verified_record(future_record)
        gateway.register_verified_record(peer_record)
        original_search = provider.archive_provider.search
        provider.archive_provider.search = lambda value: (*original_search(value), future, peer, unverified)
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 2)
        texts = '\n'.join(message.content for _, messages in backend.calls for message in messages)
        self.assertNotIn('SECRET_', texts)
        self.assertTrue({'AFTER_CUTOFF', 'IDENTITY_MISMATCH', 'UNVERIFIED_SOURCE'} <=
                        {row.get('reason') for row in provider.trace})

    def test_future_cross_origin_and_unadmitted_hints_are_hidden(self):
        provider, backend, _, _, _ = setup()
        original = provider.archive_provider.link_hints
        def hints():
            values = list(original())
            if not values:
                return ()
            good = values[0]
            return (*values,
                    dict(good, path='/future', url='https://synthetic.example/future',
                         observed_at='2025-01-01T00:00:00+00:00'),
                    dict(good, path='/foreign', url='https://foreign.example/foreign'),
                    dict(good, path='/unadmitted', url='https://synthetic.example/unadmitted',
                         found_in_source_id='NO_VERIFIED_SOURCE'))
        provider.archive_provider.link_hints = hints
        provider.search(task())
        prompt = json.loads(backend.calls[0][1][-1].content)
        self.assertEqual({hint['path'] for hint in prompt['historical_link_hints']}, {'/pricing', '/team'})
        self.assertEqual({hint['path'] for hint in provider.link_hints()}, {'/pricing', '/team'})

    def test_duplicate_selection_stops_before_repeat_http_or_retry(self):
        provider, backend, client, _, _ = setup(plans=[ResearchNavigationPlan('FETCH', '/pricing')] * 4)
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(provider.trace[-1]['reason'], 'RESEARCH_PLAN_NOT_OBSERVED')

    def test_step_cap_bounds_model_work_even_when_more_links_exist(self):
        provider, backend, _, budget, _ = setup(steps=1)
        provider.search(task())
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(budget.used['model'], 1)
        self.assertEqual(provider.trace[-1]['reason'], 'NAVIGATION_STEP_CAP')

    def test_no_model_dispatch_when_no_target_can_fit_http_cap(self):
        provider, backend, client, budget, _ = setup(cap=3)
        self.assertEqual(len(provider.search(task())), 1)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(backend.calls, [])
        self.assertEqual(budget.used['model'], 0)
        self.assertEqual(provider.trace[-1]['reason'], 'INSUFFICIENT_HTTP_BUDGET')

    def test_exhausted_shared_model_budget_preserves_only_prior_admitted_evidence(self):
        provider, backend, client, budget, _ = setup(model_cap=0)
        self.assertEqual(len(provider.search(task())), 1)
        self.assertEqual(backend.calls, [])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(provider.trace[-1]['reason'], 'CALL_CAP')
        self.assertEqual(budget.used['model'], 0)

    def test_archive_physical_cap_prevents_planner_spend_even_with_logical_room(self):
        provider, backend, client, budget, _ = setup()
        provider.archive_provider.max_requests = 3
        self.assertEqual(len(provider.search(task())), 1)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(backend.calls, [])
        self.assertEqual(budget.used['model'], 0)
        self.assertEqual(provider.trace[-1]['reason'], 'INSUFFICIENT_HTTP_BUDGET')

    def test_terminal_model_failure_preserves_evidence_and_stops_all_later_dispatch(self):
        for reason in ('API_PROVIDER_ERROR', 'API_ACCOUNTING_BOUND_BREACH',
                       'API_INVALID_STRUCTURED_OUTPUT', 'API_USAGE_MISSING'):
            with self.subTest(reason=reason):
                provider, _, client, budget, _ = setup()
                class FailingBackend(Planner):
                    def generate(self, schema, messages, temperature):
                        self.calls.append((schema, messages))
                        raise BudgetStopped(reason)
                backend = FailingBackend()
                provider.backend = backend
                self.assertEqual(len(provider.search(task())), 1)
                self.assertTrue(budget.stopped)
                self.assertEqual(provider.trace[-1]['reason'], reason)
                with self.assertRaisesRegex(BudgetStopped, 'STOP_OR_DEADLINE'):
                    provider.search(task())
                with self.assertRaisesRegex(BudgetStopped, 'STOP_OR_DEADLINE'):
                    with budget.reserve('model'):
                        self.fail('terminal provider error allowed another stage to dispatch')
                self.assertEqual(len(client.calls), 2)
                self.assertEqual(len(backend.calls), 1)

    def test_owned_backend_reserves_physical_request_once(self):
        provider, _, _, budget, _ = setup(steps=1)
        class OwningBackend(Planner):
            call_budget = budget
            def generate(self, schema, messages, temperature):
                with self.call_budget.reserve('model'):
                    return super().generate(schema, messages, temperature)
        owner = OwningBackend()
        provider.backend = owner
        provider.search(task())
        self.assertEqual(len(owner.calls), 1)
        self.assertEqual(budget.used['model'], 1)

    def test_unresolved_peer_and_mismatched_company_do_not_dispatch(self):
        provider, backend, client, _, _ = setup()
        self.assertEqual(provider.search(ResearchRequest('other', 'Question', 'SYNTHETIC_COMPANY', 'PEER')), ())
        with self.assertRaisesRegex(ValueError, 'match run company'):
            provider.search(ResearchRequest('other', 'Question', 'OTHER_COMPANY'))
        self.assertEqual(client.calls, [])
        self.assertEqual(backend.calls, [])

    def test_existing_runtime_accepts_provider_and_keeps_missing_evidence_unknown(self):
        from closed_loop.fixtures import FixtureCommittee
        from closed_loop.runtime import ClosedLoopRuntime
        provider, backend, client, budget, gateway = setup(model_cap=10)
        class Lead:
            def select(self, req, gaps):
                return (task(),)
        runtime = ClosedLoopRuntime(provider.request, gateway, budget, Lead(), FixtureCommittee(), provider)
        result = runtime.run()
        self.assertEqual(result['decision'], 'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'], 'NO_NEW_EVIDENCE')
        self.assertEqual(len(result['admitted_fact_ids']), 2)
        self.assertEqual(len(client.calls), 4)
        self.assertEqual(len(backend.calls), 2)
        self.assertIn('unknown, not negative', result['rationale'])

    def test_constructor_rejects_separate_budget_or_gateway(self):
        provider, backend, _, budget, gateway = setup()
        other_budget = CallBudget(provider.request)
        with self.assertRaisesRegex(ValueError, 'share request/gateway/budget'):
            MeteredResearchProvider(provider.request, gateway, other_budget, backend, provider.archive_provider)
        with self.assertRaisesRegex(ValueError, 'share request/gateway/budget'):
            MeteredResearchProvider(provider.request, TemporalGateway(provider.request, []), budget,
                                    backend, provider.archive_provider)


if __name__ == '__main__':
    unittest.main()
