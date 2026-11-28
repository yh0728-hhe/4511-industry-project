"""No-source research is a normal unknown, not an invitation to fabricate debate citations."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request,FixtureLead
from closed_loop.guards import CallBudget,TemporalGateway
from closed_loop.runtime import ClosedLoopRuntime
class NoFactResearchTests(unittest.TestCase):
    def build(self,restriction=None,passes=1):
        req=request(max_research_passes=passes);budget=CallBudget(req);gateway=TemporalGateway(req,[])
        class Provider:
            call_budget=budget
            def search(self,task):
                if restriction:budget.stop(restriction)
                return ()
        class Committee:
            calls=0
            def evaluate(self,view):
                self.calls+=1;raise AssertionError('No evidence must not reach debate')
        committee=Committee()
        runtime=ClosedLoopRuntime(req,gateway,budget,FixtureLead(),committee,Provider())
        return runtime,committee,budget
    def test_empty_bounded_research_returns_unknown_with_targeted_questions(self):
        runtime,committee,budget=self.build();out=runtime.run()
        self.assertEqual(out['stop_reason'],'NO_ADMITTED_FACTS')
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertEqual(out['essential_gaps'],['market','traction'])
        self.assertEqual(out['admitted_fact_ids'],[])
        self.assertEqual(committee.calls,0)
        self.assertEqual(budget.used['model'],1)
    def test_empty_first_pass_keeps_authorized_second_pass(self):
        runtime,committee,budget=self.build(passes=2);out=runtime.run()
        self.assertEqual(out['stop_reason'],'NO_ADMITTED_FACTS')
        self.assertEqual(committee.calls,0)
        self.assertEqual(budget.used['model'],2)
        self.assertEqual(sum(x['event']=='EMPTY_EVIDENCE_REVIEW' for x in out['trace']),1)

    def test_second_pass_can_admit_evidence_and_reach_committee(self):
        from closed_loop.fixtures import source
        from closed_loop.contracts import CommitteeResult,Decision
        runtime,_,budget=self.build(passes=2)
        candidate,record=source('second-pass','market','Historical evidence')
        runtime.gateway=TemporalGateway(runtime.request,[record])
        class ChangingLead:
            calls=0
            def select(self,req,gaps):
                from closed_loop.contracts import ResearchRequest
                self.calls+=1
                return (ResearchRequest('market','new source '+str(self.calls),req.company.company_id),)
        class LaterProvider:
            call_budget=budget
            calls=0
            def search(self,task):
                self.calls+=1
                return (candidate,) if self.calls==2 else ()
        class Committee:
            calls=0
            def evaluate(self,view):
                self.calls+=1
                return CommitteeResult(Decision.MORE_DILIGENCE,'More facts needed',('retention',),view.fact_revision,view.argument_revision,(view.qa_pairs[0]['fact_id'],))
        runtime.lead=ChangingLead();runtime.provider=LaterProvider();runtime.committee=Committee()
        out=runtime.run()
        self.assertEqual(len(out['admitted_fact_ids']),1)
        self.assertEqual(runtime.committee.calls,1)
        self.assertEqual(runtime.provider.calls,2)
        self.assertEqual(out['decision'],'MORE_DILIGENCE')

    def test_transport_restriction_not_mislabeled_normal_no_facts(self):
        runtime,committee,budget=self.build('ARCHIVE_ACCESS_RESTRICTED');out=runtime.run()
        self.assertEqual(out['stop_reason'],'ARCHIVE_ACCESS_RESTRICTED')
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertEqual(committee.calls,0)
    def test_no_fact_stop_keeps_source_research_trace(self):
        runtime,committee,budget=self.build();out=runtime.run()
        self.assertEqual(sum(e['event']=='RESEARCH' for e in out['trace']),2)
        self.assertEqual(out['trace'][-1]['event'],'RESEARCH_WITHOUT_ADMITTED_FACTS')
if __name__=='__main__':unittest.main()
