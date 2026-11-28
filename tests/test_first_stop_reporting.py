"""Preserve the first terminal stop in result reporting, not only budget state."""
import unittest
from closed_loop.fixtures import request,FixtureLead,FixtureProvider,FixtureCommittee
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.runtime import ClosedLoopRuntime

class FirstStopReportingTests(unittest.TestCase):
    def run_provider(self,first,secondary):
        req=request();budget=CallBudget(req)
        class Provider:
            call_budget=budget
            def search(self,task):
                if first:budget.stop(first)
                raise BudgetStopped(secondary)
        class Committee:
            def evaluate(self,*args):raise AssertionError('No evidence reached committee')
        return ClosedLoopRuntime(req,TemporalGateway(req,[]),budget,FixtureLead(),Committee(),Provider()).run(),budget
    def test_secondary_exception_does_not_replace_first_provider_stop(self):
        out,budget=self.run_provider('ARCHIVE_RATE_LIMITED','SECONDARY_EXCEPTION')
        self.assertEqual(out['stop_reason'],'ARCHIVE_RATE_LIMITED')
        self.assertEqual(budget.stop_reason,'ARCHIVE_RATE_LIMITED')
    def test_secondary_normal_stop_cannot_mask_restriction(self):
        out,budget=self.run_provider('ARCHIVE_ACCESS_RESTRICTED','NO_NEW_EVIDENCE')
        self.assertEqual(out['stop_reason'],'ARCHIVE_ACCESS_RESTRICTED')
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
    def test_unrecorded_budget_exception_keeps_its_specific_reason(self):
        out,budget=self.run_provider(None,'CALL_CAP')
        self.assertEqual(out['stop_reason'],'CALL_CAP')
        self.assertFalse(budget.stopped)
    def test_final_thesis_preserves_existing_first_stop(self):
        req=request();budget=CallBudget(req);provider=FixtureProvider(good=True)
        class Thesis:
            call_budget=budget
            def synthesize(self,*args):
                budget.stop('FIRST_THESIS_STOP')
                raise BudgetStopped('SECONDARY_THESIS_ERROR')
        out=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),FixtureCommittee(),provider,thesis=Thesis()).run()
        self.assertEqual(out['stop_reason'],'FIRST_THESIS_STOP')
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertIn('final_thesis_unverified',out['essential_gaps'])
if __name__=='__main__':unittest.main()
