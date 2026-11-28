"""Offline evidence-support wrapper tests; fixture responses control branching, not quality."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.contracts import CommitteeResult, Decision
from closed_loop.guards import CallBudget, BudgetStopped, TemporalGateway
from closed_loop.fixtures import request, FixtureProvider, FixtureLead
from closed_loop.runtime import ClosedLoopRuntime
from closed_loop.native_committee import NativeDialecticCommittee
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.native_support import ArgumentsOutput, ArgumentOutput
from closed_loop.ragas_faithfulness import (RagasFaithfulnessChecker, FaithfulnessStatements,
    FaithfulnessVerdicts, StatementFaithfulnessVerdict)
from closed_loop.evidence_checked_committee import EvidenceCheckedCommittee, UNVERIFIED_CLAIM_PREFIX
from closed_loop.offline_network import OfflineSocketGuard


def view(**updates):
    base=dict(company_id='C',mandate='M',as_of='2024-04-04T23:59:59+00:00',
        fact_revision=1,argument_revision=1,qa_pairs=[dict(fact_id='f1'),dict(fact_id='f2')])
    base.update(updates)
    return SimpleNamespace(**base)


def final_trace(arguments):
    return [dict(event='NATIVE_COMMITTEE_STAGE',stage='final_aggregation',arguments=arguments)]


def argument(text='Argument text',cited=('f1',),tracking_id='t1'):
    return dict(text=text,cited_fact_ids=list(cited),tracking_id=tracking_id)


class FakeCommittee:
    def __init__(self,budget,result,trace=(),calls=None):
        self.call_budget=budget;self.result=result;self.last_trace=list(trace);self.last_calls=list(calls or [{'c':1}])
    def evaluate(self,v):return self.result


class FakeChecker:
    def __init__(self,budget,verdict_by_text=None,default_verdict=1,raises=None):
        self.call_budget=budget;self.verdict_by_text=verdict_by_text or {}
        self.default_verdict=default_verdict;self.calls=0;self.last_calls=[];self.raises=raises
    def assess(self,v,*,question,response,cited_fact_ids):
        self.calls+=1;self.last_calls=[{'call':self.calls,'response':response}]
        if self.raises is not None:raise self.raises
        verdict=self.verdict_by_text.get(response,self.default_verdict)
        return dict(judgments=[dict(statement=response,reason='fixture reason',verdict=verdict)],
            automatic_entailment_check=True,semantic_support_certified=False,human_review=False)


def result(decision=Decision.INVEST,gaps=(),cited=('f1',)):
    return CommitteeResult(decision,'Fixture rationale.',gaps,1,1,cited)


class FakeGapTriage:
    def __init__(self,budget,questions=()):
        self.call_budget=budget;self.questions=questions;self.last_trace=[{'event':'TRIAGE_STAGE'}];self.last_calls=[{'c':'triage'}];self.calls=0
    def triage(self,view,diagnostics,essential_gaps):
        self.calls+=1;return self.questions


class EvidenceCheckedCommitteeTests(unittest.TestCase):
    def test_failed_checker_stage_trace_survives_before_evaluation_returns(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(),final_trace([argument()]))
        checker=FakeChecker(budget,raises=BudgetStopped('CLI_PROCESS_FAILED'))
        checker.last_trace=[{'stage':'decomposition','output':{'statements':['Original claim']}}]
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaises(BudgetStopped):wrapped.evaluate(view())
        event=wrapped.last_trace[-1]
        self.assertEqual(event['event'],'EVIDENCE_SUPPORT_CHECK_STOPPED')
        self.assertEqual(event['checker_stage_trace'],checker.last_trace)
        self.assertTrue(any(e.get('stage')=='final_aggregation' for e in wrapped.last_trace))

    def test_unsupported_argument_forces_more_diligence_with_gap(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertIn(UNVERIFIED_CLAIM_PREFIX+'Argument text',out.essential_gaps)
        self.assertEqual(checker.calls,1)
        review=[e for e in wrapped.last_trace if e['event']=='EVIDENCE_SUPPORT_REVIEW']
        self.assertEqual(len(review),1)
        self.assertEqual(review[0]['tracking_id'],'t1')
        self.assertEqual(wrapped.last_calls,committee.last_calls+checker.last_calls)

    def test_pass_on_unsupported_argument_also_becomes_more_diligence(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.PASS),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)

    def test_original_more_diligence_is_not_upgraded_by_support(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.MORE_DILIGENCE,gaps=('retention',)),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=1)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(out.essential_gaps,('retention',))

    def test_all_supported_preserves_original_decision(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=1)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.INVEST)
        self.assertEqual(out.essential_gaps,())

    def test_invalid_blank_argument_text_stops_before_checker(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument(text='   ')]))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_SUPPORT_BLANK_ARGUMENT'):wrapped.evaluate(view())
        self.assertEqual(checker.calls,0)

    def test_foreign_citation_stops_before_checker(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument(cited=('foreign',))]))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_SUPPORT_FOREIGN_CITATION'):wrapped.evaluate(view())
        self.assertEqual(checker.calls,0)

    def test_duplicate_citation_stops_before_checker(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument(cited=('f1','f1'))]))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_SUPPORT_DUPLICATE_CITATIONS'):wrapped.evaluate(view())
        self.assertEqual(checker.calls,0)

    def test_empty_final_trace_with_more_diligence_is_preserved(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.MORE_DILIGENCE,gaps=('retention',)),final_trace([]))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out,result(Decision.MORE_DILIGENCE,gaps=('retention',)))
        self.assertEqual(checker.calls,0)

    def test_empty_final_trace_with_substantive_decision_adds_missing_trace_gap(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([]))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertIn('missing_argument_trace',out.essential_gaps)
        self.assertEqual(checker.calls,0)

    def test_cap_exceeded_stops_before_any_checker_call(self):
        budget=CallBudget(request())
        arguments=[argument(text=f'Argument {i}',tracking_id=f't{i}') for i in range(5)]
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace(arguments))
        checker=FakeChecker(budget)
        wrapped=EvidenceCheckedCommittee(committee,checker,budget,max_arguments=4)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_SUPPORT_ARGUMENT_CAP_EXCEEDED'):wrapped.evaluate(view())
        self.assertEqual(checker.calls,0)
        self.assertTrue(budget.stopped)

    def test_checker_budget_mismatch_rejected_at_construction(self):
        budget=CallBudget(request())
        other=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST))
        checker=FakeChecker(other)
        with self.assertRaises(ValueError):EvidenceCheckedCommittee(committee,checker,budget)

    def test_committee_budget_mismatch_rejected_at_construction(self):
        budget=CallBudget(request())
        other=CallBudget(request())
        committee=FakeCommittee(other,result(Decision.INVEST))
        checker=FakeChecker(budget)
        with self.assertRaises(ValueError):EvidenceCheckedCommittee(committee,checker,budget)

    def test_checker_failure_preserves_committee_calls_and_trace(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument()]),calls=[{'c':'committee'}])
        checker=FakeChecker(budget,raises=BudgetStopped('FAITHFULNESS_INVALID_RESPONSE'))
        checker.last_calls=[{'c':'checker-partial'}]
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_INVALID_RESPONSE'):wrapped.evaluate(view())
        self.assertEqual(wrapped.last_calls,[{'c':'committee'},*checker.last_calls])
        self.assertTrue(any(e['event']=='NATIVE_COMMITTEE_STAGE' for e in wrapped.last_trace))
        self.assertTrue(budget.stopped)


    def test_empty_gap_triage_keeps_more_diligence_for_invest_without_fabricated_gaps(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST,gaps=('existing_gap',)),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        triage=FakeGapTriage(budget,questions=())
        wrapped=EvidenceCheckedCommittee(committee,checker,budget,gap_triage=triage)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(out.essential_gaps,('existing_gap',))
        self.assertEqual(out.cited_fact_ids,result(Decision.INVEST).cited_fact_ids)
        self.assertEqual(out.fact_revision,1);self.assertEqual(out.argument_revision,1)
        event=[e for e in wrapped.last_trace if e['event']=='EVIDENCE_SUPPORT_UNRESOLVED']
        self.assertEqual(len(event),1)
        self.assertEqual(event[0],dict(event='EVIDENCE_SUPPORT_UNRESOLVED',automatic=True,
            semantically_certified=False,no_new_research_questions=True))

    def test_empty_gap_triage_keeps_more_diligence_for_pass_without_fabricated_gaps(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.PASS,gaps=('existing_gap',)),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        triage=FakeGapTriage(budget,questions=())
        wrapped=EvidenceCheckedCommittee(committee,checker,budget,gap_triage=triage)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(out.essential_gaps,('existing_gap',))

    def test_original_more_diligence_unchanged_by_empty_gap_triage(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.MORE_DILIGENCE,gaps=('retention',)),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        triage=FakeGapTriage(budget,questions=())
        wrapped=EvidenceCheckedCommittee(committee,checker,budget,gap_triage=triage)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(out.essential_gaps,('retention',))
        self.assertEqual(out,committee.result)

    def test_empty_triage_does_not_invent_a_public_research_gap(self):
        budget=CallBudget(request())
        wrapped=EvidenceCheckedCommittee(FakeCommittee(budget,result(),final_trace([argument()])),
            FakeChecker(budget,default_verdict=0),budget,gap_triage=FakeGapTriage(budget))
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(out.essential_gaps,())
        self.assertIn('Automatic evidence-support check',out.rationale)
        self.assertEqual(budget.used,{'model':0,'search':0})

    def test_runtime_finishes_more_without_thesis_or_repeat_search_for_empty_triage(self):
        from closed_loop.fixtures import FixtureProvider,FixtureLead
        from closed_loop.runtime import ClosedLoopRuntime
        from closed_loop.guards import TemporalGateway
        req=request();budget=CallBudget(req);provider=FixtureProvider()
        class DynamicCommittee:
            call_budget=budget;last_calls=[];last_trace=[]
            def evaluate(self,v):
                self.last_trace=final_trace([argument(cited=(v.qa_pairs[0]['fact_id'],))])
                return CommitteeResult(Decision.INVEST,'Fixture rationale.',(),v.fact_revision,v.argument_revision,(v.qa_pairs[0]['fact_id'],))
        class NoThesis:
            call_budget=budget
            def synthesize(self,*args):raise AssertionError('Unresolved support must not generate a substantive thesis')
        wrapped=EvidenceCheckedCommittee(DynamicCommittee(),FakeChecker(budget,default_verdict=0),budget,gap_triage=FakeGapTriage(budget))
        out=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),wrapped,provider,thesis=NoThesis()).run()
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertIsNone(out['thesis'])
        self.assertEqual(sum(e['event']=='RESEARCH' for e in out['trace']),2)

    def test_all_supported_arguments_never_invoke_gap_triage(self):
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(Decision.INVEST),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=1)
        triage=FakeGapTriage(budget,questions=())
        wrapped=EvidenceCheckedCommittee(committee,checker,budget,gap_triage=triage)
        out=wrapped.evaluate(view())
        self.assertEqual(out.decision,Decision.INVEST)
        self.assertFalse(any(e['event']=='EVIDENCE_SUPPORT_UNRESOLVED' for e in wrapped.last_trace))
        self.assertFalse(any(e['event']=='TRIAGE_STAGE' for e in wrapped.last_trace))
        self.assertEqual(triage.calls,0)


class _RagasFixtureBackend(NativeFixtureBackend):
    """Extends the native argument-generation fixture with Ragas decomposition/NLI schemas."""
    def __init__(self,argument_count=1,support=True):
        super().__init__(argument_count=argument_count)
        self.support=support

    def generate(self,schema,messages,temperature):
        if schema is FaithfulnessStatements:
            answer=messages[-1].content.rsplit('Input JSON: ',1)[1]
            import json as _json
            return FaithfulnessStatements(statements=[_json.loads(answer)['answer']])
        if schema is FaithfulnessVerdicts:
            import json as _json
            payload=_json.loads(messages[-1].content.rsplit('Input JSON: ',1)[1])
            verdict=1 if self.support else 0
            return FaithfulnessVerdicts(statements=[
                StatementFaithfulnessVerdict(s,'fixture faithfulness reason',verdict) for s in payload['statements']])
        return super().generate(schema,messages,temperature)


class _OneExtraPassProvider(FixtureProvider):
    """Reuses the standard good-retention ledger; no additional evidence to admit on a second pass."""
    def search(self,task):return ()


class EvidenceCheckedCommitteeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.network=OfflineSocketGuard().install()
    @classmethod
    def tearDownClass(cls):cls.network.restore()

    def _build(self,support):
        req=request(max_model_calls=60)
        provider=FixtureProvider(good=True)
        budget=CallBudget(req)
        backend=_RagasFixtureBackend(support=support)
        native=NativeDialecticCommittee(backend,budget)
        checker=RagasFaithfulnessChecker(backend,budget)
        wrapped=EvidenceCheckedCommittee(native,checker,budget)
        runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),wrapped,provider)
        return runtime,budget

    def test_supported_final_arguments_never_falsely_downgraded(self):
        runtime,budget=self._build(support=True)
        out=runtime.run()
        self.assertEqual(out['decision'],'INVEST')
        self.assertFalse(any(q.startswith(UNVERIFIED_CLAIM_PREFIX) for e in out['trace'] if e['event']=='EVIDENCE_GAP' for q in e['questions']))

    def test_unsupported_final_argument_triggers_followup_research_gap(self):
        runtime,budget=self._build(support=False)
        out=runtime.run()
        self.assertNotEqual(out['decision'],'INVEST')
        self.assertIn(out['stop_reason'],('NO_NEW_EVIDENCE','RESEARCH_PASS_CAP'))
        gap_events=[e for e in out['trace'] if e['event']=='EVIDENCE_GAP']
        self.assertTrue(gap_events)
        self.assertTrue(any(g.startswith(UNVERIFIED_CLAIM_PREFIX) for e in gap_events for g in e['questions']))
        review_events=[e for e in out['trace'] if e['event']=='EVIDENCE_SUPPORT_REVIEW']
        self.assertTrue(review_events)
        for review in review_events:
            self.assertFalse(review['automatic'] is False)
            self.assertFalse(review['semantically_certified'])


if __name__=='__main__':unittest.main()


class EvidenceWrapperFailureTests(unittest.TestCase):
    def test_later_invalid_argument_rejected_before_any_checker_dispatch(self):
        budget=CallBudget(request());checker=FakeChecker(budget)
        committee=FakeCommittee(budget,result(),final_trace([argument(),argument(cited=('foreign',))]))
        wrapped=EvidenceCheckedCommittee(committee,checker,budget)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_SUPPORT_FOREIGN_CITATION'):wrapped.evaluate(view())
        self.assertEqual(checker.calls,0)
    def test_inner_committee_failure_retains_its_trace_and_call_record(self):
        budget=CallBudget(request())
        class Failed(FakeCommittee):
            def evaluate(self,v):raise BudgetStopped('inner-stop')
        committee=Failed(budget,result(),final_trace([argument()]),calls=[{'c':'partial-inner'}])
        wrapped=EvidenceCheckedCommittee(committee,FakeChecker(budget),budget)
        with self.assertRaisesRegex(BudgetStopped,'inner-stop'):wrapped.evaluate(view())
        self.assertEqual(wrapped.last_calls,[{'c':'partial-inner'}]);self.assertTrue(wrapped.last_trace)
        self.assertEqual(budget.stop_reason,'inner-stop')
    def test_malformed_judgment_is_terminal_not_unhandled_error(self):
        budget=CallBudget(request())
        class Broken(FakeChecker):
            def assess(self,*a,**kw):return {'judgments':['bad']}
        wrapped=EvidenceCheckedCommittee(FakeCommittee(budget,result(),final_trace([argument()])),Broken(budget),budget)
        with self.assertRaisesRegex(BudgetStopped,'INVALID_EVIDENCE_SUPPORT_RESULT'):wrapped.evaluate(view())
        self.assertTrue(budget.stopped)
