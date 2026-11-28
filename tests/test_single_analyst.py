import copy
import json
from dataclasses import replace
import unittest
from closed_loop.fixtures import request,FixtureProvider
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.runtime import FactStore,committee_input
from closed_loop.model_identity import present_payload
from closed_loop.single_analyst import SingleAnalystBaseline,SingleAnalystAssessment
from closed_loop.thesis_synthesis import ThesisSynthesis


class FakeAnalyst:
    def __init__(self,value=None):self.value=value;self.seen=[]
    def generate(self,schema,messages,temperature):
        self.seen.append(messages)
        return self.value or SingleAnalystAssessment('MORE_DILIGENCE','Fixture source too limited',['retention'],None)


def setup():
    req=request();budget=CallBudget(req);provider=FixtureProvider();gateway=TemporalGateway(req,provider.ledger)
    fact,error=gateway.admit(provider.market);assert error is None
    store=FactStore();store.merge([fact]);return req,budget,committee_input(req,store,1)


class SingleAnalystTests(unittest.TestCase):
    def test_one_call_same_evidence_guard_and_mandate(self):
        req,budget,view=setup();backend=FakeAnalyst();before=copy.deepcopy(view)
        result=SingleAnalystBaseline(backend,budget).assess(view)
        self.assertEqual(budget.used['model'],1);self.assertEqual(len(backend.seen),1)
        context=json.loads(backend.seen[0][0].content.split('\n',1)[1])
        self.assertEqual(context['evidence'],present_payload(list(view.qa_pairs),view.company_id));self.assertEqual(context['mandate'],req.mandate)
        self.assertEqual(result['decision'],'MORE_DILIGENCE');self.assertEqual(before,view)

    def test_empty_sources_no_call(self):
        req,budget,view=setup();backend=FakeAnalyst()
        out=SingleAnalystBaseline(backend,budget).assess(replace(view,qa_pairs=()))
        self.assertEqual(out['admitted_fact_ids'],[]);self.assertEqual(backend.seen,[])

    def test_wrong_company_or_date_no_call(self):
        for changes in [dict(company_id='other'),dict(as_of='2024-04-03T00:00:00Z')]:
            req,budget,view=setup();backend=FakeAnalyst()
            with self.assertRaises(BudgetStopped):SingleAnalystBaseline(backend,budget).assess(replace(view,**changes))
            self.assertEqual(backend.seen,[])

    def test_future_qa_no_call(self):
        req,budget,view=setup();backend=FakeAnalyst();row=dict(view.qa_pairs[0],available_by='2025-01-01T00:00:00Z')
        with self.assertRaises(BudgetStopped):SingleAnalystBaseline(backend,budget).assess(replace(view,qa_pairs=(row,)))
        self.assertEqual(budget.used['model'],0)

    def test_invalid_decision_terminal(self):
        req,budget,view=setup();backend=FakeAnalyst(SingleAnalystAssessment('MAYBE','fixture',[],None))
        with self.assertRaises(BudgetStopped):SingleAnalystBaseline(backend,budget).assess(view)
        self.assertTrue(budget.stopped);self.assertEqual(budget.used['model'],1)

    def test_missing_thesis_rejected(self):
        req,budget,view=setup();backend=FakeAnalyst(SingleAnalystAssessment('INVEST','fixture',[],None))
        with self.assertRaisesRegex(BudgetStopped,'BASELINE_MISSING_THESIS'):SingleAnalystBaseline(backend,budget).assess(view)

    def test_unavailable_citation_rejected(self):
        req,budget,view=setup();thesis=ThesisSynthesis('fixture',[],[],['unavailable'],[],[],[])
        backend=FakeAnalyst(SingleAnalystAssessment('INVEST','fixture',[],thesis))
        with self.assertRaises(BudgetStopped):SingleAnalystBaseline(backend,budget).assess(view)

    def test_gaps_override_without_losing_raw_proposal(self):
        req,budget,view=setup();thesis=ThesisSynthesis('fixture',[],[],[view.qa_pairs[0]['fact_id']],[],[],[])
        backend=FakeAnalyst(SingleAnalystAssessment('INVEST','fixture',['retention'],thesis))
        out=SingleAnalystBaseline(backend,budget).assess(view)
        self.assertEqual(out['decision'],'MORE_DILIGENCE');self.assertEqual(out['untrusted_proposed_decision'],'INVEST')
        self.assertIsNone(out['thesis']);self.assertIsNotNone(out['raw_assessment']['thesis'])

    def test_stopped_budget_and_missing_backend(self):
        req,budget,view=setup();backend=FakeAnalyst();budget.stop('explicit-stop')
        with self.assertRaisesRegex(BudgetStopped,'explicit-stop'):SingleAnalystBaseline(backend,budget).assess(view)
        self.assertEqual(backend.seen,[])
        with self.assertRaises(ValueError):SingleAnalystBaseline(None,budget)

    def test_backend_owned_meter_not_double_counted(self):
        req,budget,view=setup()
        class Metered(FakeAnalyst):
            call_budget=budget
            def generate(self,*args):
                with budget.reserve('model'):return super().generate(*args)
        SingleAnalystBaseline(Metered(),budget).assess(view)
        self.assertEqual(budget.used['model'],1)


if __name__=='__main__':unittest.main()
