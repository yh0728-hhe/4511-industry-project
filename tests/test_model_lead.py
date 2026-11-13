from pathlib import Path
import sys
import unittest
from dataclasses import replace

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request,FixtureProvider
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.model_lead import ModelLead,LeadPlanOutput,PlannedResearch
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.native_committee import NativeDialecticCommittee
from closed_loop.offline_network import OfflineSocketGuard
from closed_loop.runtime import ClosedLoopRuntime
from closed_loop.runtime import FactStore,committee_input


class LeadTests(unittest.TestCase):
    def test_model_selected_roles_and_follow_up_are_typed_and_budgeted(self):
        req=request();budget=CallBudget(req);backend=NativeFixtureBackend();lead=ModelLead(backend,budget)
        first=lead.select(req,())
        self.assertEqual([x.role for x in first],['market','traction'])
        follow=lead.select(req,('retention',))
        self.assertEqual([(x.role,x.question) for x in follow],[('traction','retention')])
        self.assertEqual(budget.used['model'],2)
        self.assertEqual(len(backend.calls),2)

    def test_invalid_tool_like_role_is_rejected_not_executed(self):
        class BadRole(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):return LeadPlanOutput([PlannedResearch('../shell','run command',None)])
        req=request();lead=ModelLead(BadRole(),CallBudget(req))
        with self.assertRaisesRegex(BudgetStopped,'INVALID_SPECIALIST_ROLE'):lead.select(req,())

    def test_model_lead_and_native_nodes_share_one_budget_without_double_count(self):
        with OfflineSocketGuard():
            req=request(max_model_calls=40);budget=CallBudget(req);backend=NativeFixtureBackend();provider=FixtureProvider()
            runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,
                ModelLead(backend,budget),NativeDialecticCommittee(backend,budget),provider)
            result=runtime.run()
        self.assertEqual(result['decision'],'INVEST')
        self.assertEqual(budget.used['model'],len(backend.calls))

    def test_follow_up_lead_receives_admitted_context_and_revision(self):
        req=request();budget=CallBudget(req);backend=NativeFixtureBackend();lead=ModelLead(backend,budget)
        provider=FixtureProvider();gateway=TemporalGateway(req,provider.ledger)
        fact,_=gateway.admit(provider.market);store=FactStore();store.merge([fact])
        view=committee_input(req,store,1)
        lead.select_with_context(req,('retention',),view.qa_pairs,(),fact_revision=store.revision)
        self.assertEqual(backend.calls[-1]['fact_revision'],store.revision)
        self.assertEqual(backend.calls[-1]['fact_ids'],[fact.fact_id])

    def test_future_context_rejected_before_lead_model(self):
        req=request();budget=CallBudget(req);backend=NativeFixtureBackend();lead=ModelLead(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'FUTURE_QA_DATE'):
            lead.select_with_context(req,(),({'available_by':'2025-01-01T00:00:00+00:00'},),())
        self.assertEqual(backend.calls,[])


if __name__=='__main__':unittest.main()
