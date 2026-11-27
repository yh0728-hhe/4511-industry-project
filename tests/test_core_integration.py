"""Core component integration, not fixture committee shortcuts or live model tests."""
import unittest
from closed_loop.integration_debug import run_debug_case
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,BudgetStopped


class CoreIntegrationTests(unittest.TestCase):
    def test_full_pipeline_researches_gap_rebuilds_native_debate_and_synthesizes(self):
        r=run_debug_case()
        self.assertEqual(r['decision'],'INVEST');self.assertIsNotNone(r['thesis'])
        self.assertEqual(len(r['archive_receipts']),2)
        committees=[x for x in r['trace'] if x['event']=='COMMITTEE_REGENERATED']
        self.assertEqual([x['proposed_decision'] for x in committees],['MORE_DILIGENCE','INVEST'])
        self.assertGreater(committees[1]['fact_revision'],committees[0]['fact_revision'])
        schemas={x['schema'] for x in r['backend_calls']}
        self.assertTrue({'LeadPlanOutput','ResearchNavigationPlan','ArgumentsOutput','ArgumentCritique',
                         'SingleArgumentScore','IndividualRefinedArgumentOutput','EvidenceReviewOutput','ThesisSynthesis'}<=schemas)
        self.assertEqual(r['logical_call_budget']['used'],{'model':r['injected_backend_calls'],'search':r['injected_http_calls']})
        self.assertEqual(r['actual_model_calls'],0);self.assertEqual(r['actual_network_calls'],0)

    def test_future_target_is_never_replayed_or_seen_by_models(self):
        r=run_debug_case('future_capture')
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertIsNone(r['thesis'])
        self.assertEqual(r['injected_http_calls'],3)
        self.assertFalse(any('SYNTHETIC_RETENTION_GOOD' in c['text_seen'] for c in r['backend_calls']))
        self.assertEqual(len(r['archive_receipts']),1)

    def test_forbidden_capture_remains_unknown_with_earlier_facts(self):
        r=run_debug_case('unreadable_capture')
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertEqual(len(r['admitted_fact_ids']),1)
        self.assertEqual(r['stop_reason'],'ARCHIVE_ACCESS_RESTRICTED');self.assertIsNone(r['thesis'])

    def test_unobserved_path_stops_with_original_cause(self):
        r=run_debug_case('unobserved_navigation')
        self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertEqual(r['stop_reason'],'RESEARCH_PLAN_NOT_OBSERVED')
        self.assertFalse(any(x['schema']=='ArgumentsOutput' for x in r['backend_calls']))
        self.assertEqual(len(r['admitted_fact_ids']),1)

    def test_bad_thesis_preserves_two_fact_revisions(self):
        r=run_debug_case('invalid_thesis')
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertIsNone(r['thesis'])
        self.assertEqual(r['stop_reason'],'THESIS_CITED_UNAVAILABLE_FACT')
        self.assertEqual(len(r['admitted_fact_ids']),2)
        self.assertTrue(any(x['event']=='NATIVE_COMMITTEE_STAGE' for x in r['trace']))

    def test_tiny_cap_blocks_without_overdispatch(self):
        r=run_debug_case('model_cap')
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertEqual(r['stop_reason'],'CALL_CAP')
        self.assertEqual(r['injected_backend_calls'],3)

    def test_24_call_plan_cannot_be_claimed_full_stack_complete(self):
        r=run_debug_case('full_stack_cap24')
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertEqual(r['stop_reason'],'CALL_CAP')
        self.assertEqual(r['injected_backend_calls'],24);self.assertIsNone(r['thesis'])

    def test_first_stop_cause_survives_later_generic_stops(self):
        b=CallBudget(request());b.stop('ORIGINAL_PROVIDER_FAILURE');b.stop()
        with self.assertRaisesRegex(BudgetStopped,'ORIGINAL_PROVIDER_FAILURE'):b.check()
        with self.assertRaisesRegex(BudgetStopped,'ORIGINAL_PROVIDER_FAILURE'):
            with b.reserve('model'):self.fail('must not reserve')

    def test_component_bound_to_different_request_rejected(self):
        from dataclasses import replace
        from closed_loop.fixtures import FixtureLead,FixtureCommittee,FixtureProvider
        from closed_loop.guards import TemporalGateway
        from closed_loop.runtime import ClosedLoopRuntime
        req=request();budget=CallBudget(req);provider=FixtureProvider()
        provider.request=replace(req,mandate='Different research mandate')
        with self.assertRaisesRegex(ValueError,'component request'):
            ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),FixtureCommittee(),provider)


if __name__=='__main__':unittest.main()
