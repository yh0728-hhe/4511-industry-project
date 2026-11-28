"""Optional screen-before-committee wrapper tests; preliminary screen can be wrong."""
from pathlib import Path
from dataclasses import replace
import sys
import json
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.contracts import CommitteeResult, Decision
from closed_loop.guards import CallBudget, BudgetStopped, TemporalGateway
from closed_loop.fixtures import request, FixtureProvider, FixtureLead
from closed_loop.runtime import ClosedLoopRuntime, FactStore, committee_input
from closed_loop.single_analyst import SingleAnalystBaseline, SingleAnalystAssessment
from closed_loop.thesis_synthesis import ThesisSynthesis
from closed_loop.progressive_committee import ProgressiveCommittee


class FakeAnalystBackend:
    def __init__(self, value=None):
        self.value = value
        self.seen = []

    def generate(self, schema, messages, temperature):
        self.seen.append(messages)
        return self.value or SingleAnalystAssessment('MORE_DILIGENCE', 'Fixture source too limited', ['retention'], None)


class FakeCommittee:
    def __init__(self, budget, result, trace=(), calls=None):
        self.call_budget = budget
        self.result = result
        self.last_trace = list(trace)
        self.last_calls = list(calls or [{'c': 1}])
        self.seen = []

    def evaluate(self, view):
        self.seen.append(view)
        return self.result


def result(decision=Decision.INVEST, gaps=(), cited=('f1',)):
    return CommitteeResult(decision, 'Fixture committee rationale.', gaps, 1, 1, cited)


def setup():
    req = request()
    budget = CallBudget(req)
    provider = FixtureProvider()
    gateway = TemporalGateway(req, provider.ledger)
    fact, error = gateway.admit(provider.market)
    assert error is None
    store = FactStore()
    store.merge([fact])
    return req, budget, committee_input(req, store, 1)


class ProgressiveCommitteeTests(unittest.TestCase):
    def test_more_diligence_screen_avoids_native_committee_and_extra_cost(self):
        req, budget, view = setup()
        screen = SingleAnalystBaseline(FakeAnalystBackend(), budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        out = wrapped.evaluate(view)
        self.assertEqual(out.decision, Decision.MORE_DILIGENCE)
        self.assertEqual(committee.seen, [])
        self.assertEqual(budget.used['model'], 1)

    def test_essential_gaps_prevent_substantive_bypass_even_with_invest_label(self):
        req, budget, view = setup()
        thesis = ThesisSynthesis('fixture', [], [], [view.qa_pairs[0]['fact_id']], [], [], [])
        backend = FakeAnalystBackend(SingleAnalystAssessment('INVEST', 'fixture', ['retention'], thesis))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        out = wrapped.evaluate(view)
        self.assertEqual(out.decision, Decision.MORE_DILIGENCE)
        self.assertIn('retention', out.essential_gaps)
        self.assertEqual(committee.seen, [])

    def test_invest_screen_with_no_gaps_escalates_original_unchanged_view(self):
        req, budget, view = setup()
        thesis = ThesisSynthesis('fixture', [], [], [view.qa_pairs[0]['fact_id']], [], [], [])
        backend = FakeAnalystBackend(SingleAnalystAssessment('INVEST', 'fixture', [], thesis))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        out = wrapped.evaluate(view)
        self.assertEqual(out, result(Decision.INVEST))
        self.assertEqual(committee.seen, [view])
        self.assertIs(committee.seen[0],view)

    def test_pass_screen_with_no_gaps_escalates_original_unchanged_view(self):
        req, budget, view = setup()
        thesis = ThesisSynthesis('fixture', [], [], [view.qa_pairs[0]['fact_id']], [], [], [])
        backend = FakeAnalystBackend(SingleAnalystAssessment('PASS', 'fixture', [], thesis))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.PASS))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        out = wrapped.evaluate(view)
        self.assertEqual(out, result(Decision.PASS))
        self.assertEqual(committee.seen, [view])
        self.assertIs(committee.seen[0],view)

    def test_preliminary_screen_claims_never_leak_into_generic_rationale_or_evidence(self):
        req, budget, view = setup()
        backend = FakeAnalystBackend(SingleAnalystAssessment('MORE_DILIGENCE', 'Secret unverified claim text', ['retention'], None))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        out = wrapped.evaluate(view)
        self.assertNotIn('Secret unverified claim text', out.rationale)
        self.assertEqual(out.cited_fact_ids, ())
        self.assertEqual(out.essential_gaps, ('retention',))
        saved=[e for e in wrapped.last_trace if e['event']=='PROGRESSIVE_PRELIMINARY_ASSESSMENT'][0]
        self.assertEqual(saved['untrusted_assessment']['rationale'],'Secret unverified claim text')
        self.assertFalse(saved['semantically_certified'])

    def test_component_budget_mismatch_rejected_at_construction(self):
        req, budget, view = setup()
        other = CallBudget(req)
        screen = SingleAnalystBaseline(FakeAnalystBackend(), budget)
        committee = FakeCommittee(other, result(Decision.INVEST))
        with self.assertRaises(ValueError):
            ProgressiveCommittee(screen, committee, budget)
        committee_ok = FakeCommittee(budget, result(Decision.INVEST))
        screen_other = SingleAnalystBaseline(FakeAnalystBackend(), other)
        with self.assertRaises(ValueError):
            ProgressiveCommittee(screen_other, committee_ok, budget)

    def test_screen_error_retains_calls_and_first_cause_with_no_fallback(self):
        req, budget, view = setup()
        backend = FakeAnalystBackend(SingleAnalystAssessment('MAYBE', 'fixture', [], None))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        with self.assertRaisesRegex(BudgetStopped, 'BASELINE_INVALID_RESPONSE'):
            wrapped.evaluate(view)
        self.assertEqual(budget.stop_reason, 'BASELINE_INVALID_RESPONSE')
        self.assertEqual(len(wrapped.last_calls), 1)
        self.assertEqual(committee.seen, [])
        # a second call does not retry/fallback into the committee
        with self.assertRaises(BudgetStopped):
            wrapped.evaluate(view)
        self.assertEqual(committee.seen, [])

    def test_shared_real_baseline_backend_consumes_one_model_reservation_not_doubled(self):
        req, budget, view = setup()
        backend = FakeAnalystBackend(SingleAnalystAssessment('MORE_DILIGENCE', 'fixture', ['retention'], None))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        wrapped.evaluate(view)
        self.assertEqual(budget.used['model'], 1)
        self.assertEqual(len(backend.seen), 1)

    def test_secondary_screen_exception_preserves_first_stop(self):
        req,budget,v=setup()
        class Screen:
            call_budget=budget;last_calls=[]
            def assess(self,*args):
                budget.stop('FIRST_STOP');raise BudgetStopped('SECONDARY_FAILURE')
        committee=FakeCommittee(budget,result())
        wrapped=ProgressiveCommittee(Screen(),committee,budget)
        with self.assertRaisesRegex(BudgetStopped,'FIRST_STOP'):wrapped.evaluate(v)
        self.assertEqual(committee.seen,[])
    def test_malformed_unhashable_gap_is_typed_invalid_screen(self):
        req,budget,v=setup()
        class Screen:
            call_budget=budget;last_calls=[]
            def assess(self,*args):return dict(decision='MORE_DILIGENCE',essential_gaps=[{}],admitted_fact_ids=[r['fact_id'] for r in v.qa_pairs])
        wrapped=ProgressiveCommittee(Screen(),FakeCommittee(budget,result()),budget)
        with self.assertRaisesRegex(BudgetStopped,'PROGRESSIVE_COMMITTEE_INVALID_SCREEN'):wrapped.evaluate(v)

    def test_more_diligence_screen_with_empty_gaps_stops_without_committee(self):
        req, budget, view = setup()
        backend = FakeAnalystBackend(SingleAnalystAssessment('MORE_DILIGENCE', 'fixture', [], None))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        with self.assertRaisesRegex(BudgetStopped, 'PROGRESSIVE_SCREEN_MISSING_GAPS'):
            wrapped.evaluate(view)
        self.assertEqual(budget.stop_reason, 'PROGRESSIVE_SCREEN_MISSING_GAPS')
        self.assertEqual(committee.seen, [])
        self.assertEqual(budget.used['model'], 1)
        self.assertEqual(len(backend.seen), 1)
        saved = [e for e in wrapped.last_trace if e['event'] == 'PROGRESSIVE_PRELIMINARY_ASSESSMENT'][0]
        self.assertEqual(saved['untrusted_assessment']['decision'], 'MORE_DILIGENCE')
        self.assertEqual(saved['untrusted_assessment']['essential_gaps'], [])

    def test_runtime_integration_screen_gap_then_research_then_escalates(self):
        req = request(max_model_calls=60)
        budget = CallBudget(req)
        provider = FixtureProvider(good=True)
        gateway = TemporalGateway(req, provider.ledger)

        class GapThenCleanBackend:
            def __init__(self):
                self.calls = 0

            def generate(self, schema, messages, temperature):
                self.calls += 1
                if self.calls == 1:
                    return SingleAnalystAssessment('MORE_DILIGENCE', 'Need retention evidence', ['retention'], None)
                context=json.loads(messages[0].content.split('\n',1)[1])
                ids=[row['fact_id'] for row in context['evidence']]
                return SingleAnalystAssessment('INVEST', 'fixture', [], ThesisSynthesis('fixture',[],[],ids,[],[],[]))

        backend = GapThenCleanBackend()
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST, cited=('f1',)))

        class RelabelCommittee:
            call_budget = budget
            last_trace = []
            last_calls = []

            def evaluate(self, v):
                ids = tuple(row['fact_id'] for row in v.qa_pairs)
                return CommitteeResult(Decision.INVEST, 'Escalated committee rationale.', (), v.fact_revision, v.argument_revision, ids)

        wrapped = ProgressiveCommittee(screen, RelabelCommittee(), budget)
        runtime = ClosedLoopRuntime(req, gateway, budget, FixtureLead(), wrapped, provider)
        out = runtime.run()
        self.assertEqual(out['decision'], 'INVEST')
        self.assertGreaterEqual(backend.calls, 2)
        self.assertTrue(any(e['event'] == 'PROGRESSIVE_SCREEN_MORE_DILIGENCE' for e in out['trace']))
        self.assertTrue(any(e['event'] == 'PROGRESSIVE_SCREEN_ESCALATED' for e in out['trace']))

    def test_runtime_stops_on_incomplete_screen_without_false_evidence_review_complete(self):
        req = request(max_model_calls=60)
        budget = CallBudget(req)
        provider = FixtureProvider(good=True)
        gateway = TemporalGateway(req, provider.ledger)

        backend = FakeAnalystBackend(SingleAnalystAssessment('MORE_DILIGENCE', 'fixture', [], None))
        screen = SingleAnalystBaseline(backend, budget)
        committee = FakeCommittee(budget, result(Decision.INVEST))
        wrapped = ProgressiveCommittee(screen, committee, budget)
        runtime = ClosedLoopRuntime(req, gateway, budget, FixtureLead(), wrapped, provider)
        out = runtime.run()
        self.assertEqual(out['decision'], 'MORE_DILIGENCE')
        self.assertEqual(out['stop_reason'], 'PROGRESSIVE_SCREEN_MISSING_GAPS')
        self.assertNotEqual(out['stop_reason'], 'EVIDENCE_REVIEW_COMPLETE')
        self.assertTrue(out['admitted_fact_ids'])
        self.assertEqual(committee.seen, [])


if __name__ == '__main__':
    unittest.main()
