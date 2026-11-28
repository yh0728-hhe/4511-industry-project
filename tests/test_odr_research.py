"""ODR-reuse-role navigation regressions: role/prompt adaptation only.

These fixtures are offline doubles, not a live research-quality benchmark;
passing tests confirm the adapted schema/metering/stop wiring behaves as
specified here, not that any mocked "plan" is a good research decision.
"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider
from closed_loop.guards import BudgetStopped, CallBudget, TemporalGateway
from closed_loop.contracts import ResearchRequest
from closed_loop.fixtures import request, source
from closed_loop.odr_research import (ODRNavigationPlan, ODRResearchProvider,
    ODR_UPSTREAM_FIVE_STEPS, odr_prompt_fingerprint)

from test_research_backend import HistoricalHTTP, task


class ODRPlanner:
    def __init__(self, plans=None):
        self.plans = list(plans or [ODRNavigationPlan('FETCH', '/pricing', 'check pricing', [])])
        self.calls = []

    def generate(self, schema, messages, temperature):
        self.calls.append((schema, messages))
        return self.plans.pop(0) if self.plans else ODRNavigationPlan('STOP', None, 'no more leads', [])


def setup(*, cap=10, model_cap=4, plans=None, steps=2):
    req = request(max_search_calls=cap, max_model_calls=model_cap)
    budget = CallBudget(req)
    gateway = TemporalGateway(req, [])
    client = HistoricalHTTP()
    archive = ArchivedWebsiteProvider(req, gateway, budget, client=client, max_requests=cap)
    backend = ODRPlanner(plans)
    provider = ODRResearchProvider(req, gateway, budget, backend, archive, max_navigation_steps=steps)
    return provider, backend, client, budget, gateway


class ODRResearchTests(unittest.TestCase):
    def test_real_inherited_search_fetches_pricing_and_admits_new_fact(self):
        provider, backend, client, budget, _ = setup()
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 2)
        self.assertTrue(any('ten synthetic units' in candidate.text for candidate in candidates))
        self.assertEqual(budget.used, {'model': 2, 'search': 4})

    def test_missing_remains_unknown_only_in_trace_not_fact(self):
        plans = [ODRNavigationPlan('STOP', None, 'cannot find more', ['founder background unknown'])]
        provider, backend, client, budget, _ = setup(plans=plans)
        provider.search(task())
        trace_event = next(e for e in provider.trace if e['event'] == 'ODR_RESEARCH_PLAN')
        self.assertEqual(trace_event['missing_information'], ['founder background unknown'])
        self.assertFalse(any('founder background unknown' in c.text for c in provider.archive_provider.search(task())))

    def test_trace_citations_only_admitted_fact_ids(self):
        provider, backend, client, budget, _ = setup(
            plans=[ODRNavigationPlan('STOP', None, 'enough found', [])])
        candidates = provider.search(task())
        trace_event = next(e for e in provider.trace if e['event'] == 'ODR_RESEARCH_PLAN')
        self.assertTrue(set(trace_event['citations']) <= {c.source_id for c in candidates} |
                        {provider._admitted[k].fact_id for k in provider._admitted})

    def test_no_future_body_reaches_planner(self):
        provider, backend, client, _, gateway = setup()
        future, future_record = source('future', 'topic', 'SECRET_FUTURE_MARKER',
                                       available='2025-01-01T00:00:00Z')
        gateway.register_verified_record(future_record)
        original_search = provider.archive_provider.search
        provider.archive_provider.search = lambda value: (*original_search(value), future)
        provider.search(task())
        texts = '\n'.join(m.content for _, msgs in backend.calls for m in msgs)
        self.assertNotIn('SECRET_', texts)

    def test_domain_invalid_plan_fails(self):
        provider, backend, client, budget, _ = setup(
            plans=[ODRNavigationPlan('FETCH', '/unseen', 'guessing', [])])
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 1)
        self.assertEqual(provider.trace[-1]['reason'], 'RESEARCH_PLAN_NOT_OBSERVED')

    def test_stop_shape_requires_null_path(self):
        provider, backend, client, budget, _ = setup(
            plans=[ODRNavigationPlan('STOP', '/pricing', 'contradictory stop', [])])
        provider.search(task())
        self.assertTrue(budget.stopped)
        self.assertEqual(provider.trace[-1]['reason'], 'ODR_PLAN_SCHEMA_INVALID')

    def test_blank_reason_rejected(self):
        provider, backend, client, budget, _ = setup(plans=[ODRNavigationPlan('STOP', None, '   ', [])])
        provider.search(task())
        self.assertEqual(provider.trace[-1]['reason'], 'ODR_PLAN_SCHEMA_INVALID')

    def test_too_many_missing_information_items_rejected(self):
        plans = [ODRNavigationPlan('STOP', None, 'many gaps', [f'gap {i}' for i in range(9)])]
        provider, backend, client, budget, _ = setup(plans=plans)
        provider.search(task())
        self.assertEqual(provider.trace[-1]['reason'], 'ODR_PLAN_SCHEMA_INVALID')

    def test_blank_missing_information_item_rejected(self):
        plans = [ODRNavigationPlan('STOP', None, 'gap present', ['   '])]
        provider, backend, client, budget, _ = setup(plans=plans)
        provider.search(task())
        self.assertEqual(provider.trace[-1]['reason'], 'ODR_PLAN_SCHEMA_INVALID')

    def test_same_meter_no_doublecount(self):
        provider, backend, client, budget, _ = setup()
        provider.search(task())
        self.assertEqual(budget.used['model'], len(backend.calls))

    def test_prompt_uses_cutoff_not_wallclock_label(self):
        provider, backend, client, budget, _ = setup()
        req = provider.request
        provider.search(task())
        prompt = json.loads(backend.calls[0][1][-1].content)
        self.assertEqual(prompt['cutoff'], req.as_of.isoformat())
        self.assertNotIn('today', prompt['instruction'].lower())

    def test_upstream_five_steps_actually_included(self):
        provider, backend, client, budget, _ = setup()
        provider.search(task())
        prompt = json.loads(backend.calls[0][1][-1].content)
        self.assertIn(ODR_UPSTREAM_FIVE_STEPS, prompt['instruction'])

    def test_allowed_hints_exact(self):
        provider, backend, client, budget, _ = setup()
        provider.search(task())
        prompt = json.loads(backend.calls[0][1][-1].content)
        self.assertEqual({hint['path'] for hint in prompt['historical_link_hints']}, {'/pricing', '/team'})

    def test_no_extra_model_clients_single_backend(self):
        provider, backend, client, budget, _ = setup()
        self.assertIs(provider.backend, backend)
        provider.search(task())
        self.assertEqual(len(provider.last_calls), len(backend.calls))

    def test_max_navigation_steps_respected(self):
        provider, backend, client, budget, _ = setup(steps=1, plans=[
            ODRNavigationPlan('FETCH', '/pricing', 'go', []), ODRNavigationPlan('FETCH', '/team', 'go', [])])
        provider.search(task())
        self.assertEqual(len(backend.calls), 1)
        self.assertEqual(provider.trace[-1]['reason'], 'NAVIGATION_STEP_CAP')

    def test_fingerprint_changes_with_adaptation_text(self):
        import closed_loop.odr_research as odr
        original = odr.ODR_ADAPTATION_NOTE
        before = odr_prompt_fingerprint()
        odr.ODR_ADAPTATION_NOTE = original + ' extra'
        try:
            after = odr_prompt_fingerprint()
        finally:
            odr.ODR_ADAPTATION_NOTE = original
        self.assertNotEqual(before, after)

    def test_terminal_schema_failure_stops_all_later_dispatch(self):
        provider, backend, client, budget, _ = setup(
            plans=[ODRNavigationPlan('WAIT', None, 'bad action', [])])
        candidates = provider.search(task())
        self.assertEqual(len(candidates), 1)
        self.assertTrue(budget.stopped)
        with self.assertRaisesRegex(BudgetStopped, 'ODR_PLAN_SCHEMA_INVALID'):
            provider.search(task())


if __name__ == '__main__':
    unittest.main()


class ODRRuntimeIntegrationTests(unittest.TestCase):
    def _runtime(self,provider,gateway,budget,cache):
        from closed_loop.runtime import ClosedLoopRuntime
        from closed_loop.contracts import CommitteeResult,Decision
        class Lead:
            def select(self,req,gaps):return (task(),)
        class Committee:
            def evaluate(self,view):
                return CommitteeResult(decision=Decision.MORE_DILIGENCE,rationale='Fixture only',
                    essential_gaps=('retention unknown',),fact_revision=view.fact_revision,
                    argument_revision=view.argument_revision,cited_fact_ids=tuple(row['fact_id'] for row in view.qa_pairs))
        return ClosedLoopRuntime(provider.request,gateway,budget,Lead(),Committee(),provider,cache=cache)

    def test_main_runtime_receives_fetched_evidence_and_no_model_invented_facts(self):
        provider,backend,client,budget,gateway=setup(model_cap=10)
        cache={};runtime=self._runtime(provider,gateway,budget,cache);out=runtime.run()
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertTrue(any('ten synthetic units' in f.text for group in cache.values() for f in group))
        self.assertTrue(any(e['event']=='COMMITTEE_REGENERATED' for e in out['trace']))
        self.assertEqual(len(client.calls),4)

    def test_changed_research_component_does_not_hit_previous_cache(self):
        from unittest.mock import patch
        provider,_,client,budget,gateway=setup(model_cap=10)
        cache={};self._runtime(provider,gateway,budget,cache).run();self.assertEqual(len(cache),1)
        provider,_,client,budget,gateway=setup(model_cap=10)
        with patch('closed_loop.odr_research.ODR_ADAPTATION_NOTE','Changed role protocol'):
            self._runtime(provider,gateway,budget,cache).run()
        self.assertEqual(len(cache),2);self.assertEqual(len(client.calls),4)
