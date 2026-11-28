"""Offline, mocked tests for EvidenceGapTriage; fixture responses control branching, not quality."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
import json

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.guards import CallBudget, BudgetStopped
from closed_loop.fixtures import request
from closed_loop.native_support import EvidenceReviewOutput
from closed_loop.evidence_gap_triage import EvidenceGapTriage


def view(**updates):
    base=dict(company_id='SYNTHETIC_COMPANY',mandate='M',as_of='2024-04-04T23:59:59+00:00',
        fact_revision=1,argument_revision=1,qa_pairs=[dict(fact_id='f1',answer='a1',available_by='2024-01-01T00:00:00+00:00')])
    base.update(updates)
    return SimpleNamespace(**base)


def diagnostic(statements_verdicts):
    return dict(judgments=[dict(statement=s,reason='fixture reason',verdict=v) for s,v in statements_verdicts])


class FakeBackend:
    def __init__(self,gaps,rationale='Fixture rationale.',calls_log=None):
        self.gaps=gaps;self.rationale=rationale;self.invocations=[];self.calls_log=calls_log

    def generate(self,schema,messages,temperature):
        self.invocations.append(dict(schema=schema.__name__,messages=[m.content for m in messages]))
        if self.calls_log is not None:self.calls_log.append(1)
        return EvidenceReviewOutput(list(self.gaps),self.rationale)


class EvidenceGapTriageTests(unittest.TestCase):
    def test_constructor_rejects_bad_bounds_before_any_call(self):
        budget=CallBudget(request())
        with self.assertRaises(ValueError):EvidenceGapTriage(FakeBackend([]),budget,max_questions=0)
        with self.assertRaises(ValueError):EvidenceGapTriage(FakeBackend([]),budget,max_questions=5)
        with self.assertRaises(ValueError):EvidenceGapTriage(None,budget)
        other=CallBudget(request())
        bad_backend=FakeBackend([]);bad_backend.call_budget=other
        with self.assertRaises(ValueError):EvidenceGapTriage(bad_backend,budget)

    def test_only_unsupported_rows_are_sent_and_one_reservation_used(self):
        budget=CallBudget(request())
        backend=FakeBackend(['What is the company stated headcount as of the filing date?'])
        triager=EvidenceGapTriage(backend,budget,max_questions=4)
        diagnostics=[diagnostic([('Supported fact.',1),('Unsupported opinion-derived claim.',0)])]
        before=budget.snapshot()['used']['model']
        out=triager.triage(view(),diagnostics,())
        after=budget.snapshot()['used']['model']
        self.assertEqual(after-before,1)
        self.assertEqual(len(backend.invocations),1)
        sent=backend.invocations[0]['messages'][-1]
        self.assertIn('Unsupported opinion-derived claim.',sent)
        self.assertEqual(json.loads(sent)['max_new_questions'],4)
        self.assertIn('Return at most 4',json.loads(sent)['question_limit_instruction'])
        self.assertNotIn('Supported fact.',sent)
        self.assertEqual(out,('What is the company stated headcount as of the filing date?',))

    def test_all_unsupported_rows_are_advice_yields_empty_result(self):
        budget=CallBudget(request())
        backend=FakeBackend([])
        triager=EvidenceGapTriage(backend,budget)
        diagnostics=[diagnostic([('Supported fact.',1)])]
        out=triager.triage(view(),diagnostics,())
        self.assertEqual(out,())
        self.assertEqual(len(backend.invocations),0)

    def test_factual_question_merged_with_original_gaps_by_caller(self):
        budget=CallBudget(request())
        backend=FakeBackend(['What is the current ARR figure cited in the filing?'])
        triager=EvidenceGapTriage(backend,budget)
        diagnostics=[diagnostic([('We should invest heavily in this company.',0)])]
        existing=('retention',)
        new_questions=triager.triage(view(),diagnostics,existing)
        self.assertEqual(new_questions,('What is the current ARR figure cited in the filing?',))
        merged=tuple(dict.fromkeys((*existing,*new_questions)))
        self.assertEqual(merged,('retention','What is the current ARR figure cited in the filing?'))

    def test_duplicate_with_existing_gap_is_dropped_not_returned_again(self):
        budget=CallBudget(request())
        backend=FakeBackend(['retention'])
        triager=EvidenceGapTriage(backend,budget)
        diagnostics=[diagnostic([('Unsupported claim.',0)])]
        out=triager.triage(view(),diagnostics,('retention',))
        self.assertEqual(out,())

    def test_question_cap_rejected_before_merge(self):
        budget=CallBudget(request())
        backend=FakeBackend(['q1','q2','q3','q4','q5'])
        triager=EvidenceGapTriage(backend,budget,max_questions=4)
        diagnostics=[diagnostic([('Unsupported claim.',0)])]
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_GAP_TRIAGE_QUESTION_CAP_EXCEEDED'):
            triager.triage(view(),diagnostics,())
        self.assertTrue(budget.stopped)

    def test_invalid_verdict_in_diagnostics_rejected_before_any_call(self):
        budget=CallBudget(request())
        backend=FakeBackend(['q1'])
        triager=EvidenceGapTriage(backend,budget)
        diagnostics=[dict(judgments=[dict(statement='s',reason='r',verdict=2)])]
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_GAP_TRIAGE_INVALID_VERDICT'):
            triager.triage(view(),diagnostics,())
        self.assertEqual(len(backend.invocations),0)

    def test_empty_diagnostics_list_rejected(self):
        budget=CallBudget(request())
        backend=FakeBackend(['q1'])
        triager=EvidenceGapTriage(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_GAP_TRIAGE_EMPTY_DIAGNOSTICS'):
            triager.triage(view(),[],())
        self.assertEqual(len(backend.invocations),0)

    def test_call_history_and_trace_retained_after_a_stopped_triage(self):
        budget=CallBudget(request())
        class DuplicateBackend(FakeBackend):
            def generate(self,schema,messages,temperature):
                super().generate(schema,messages,temperature)
                return EvidenceReviewOutput(['same','same'],'Fixture rationale.')
        backend=DuplicateBackend([])
        triager=EvidenceGapTriage(backend,budget)
        diagnostics=[diagnostic([('Unsupported claim.',0)])]
        with self.assertRaisesRegex(BudgetStopped,'EVIDENCE_GAP_TRIAGE_DUPLICATE_QUESTION'):
            triager.triage(view(),diagnostics,())
        self.assertEqual(len(backend.invocations),1)
        self.assertTrue(any(e['event']=='EVIDENCE_GAP_TRIAGE_REVIEW' for e in triager.last_trace))
        self.assertTrue(triager.last_calls)



class WrapperTriageIntegrationTests(unittest.TestCase):
    def setup_wrapper(self,questions=(),gaps=(),decision=None,raises=None):
        from test_evidence_checked_committee import FakeCommittee,FakeChecker,result,final_trace,argument
        from closed_loop.contracts import Decision
        from closed_loop.evidence_checked_committee import EvidenceCheckedCommittee
        budget=CallBudget(request())
        committee=FakeCommittee(budget,result(decision or Decision.INVEST,gaps=gaps),final_trace([argument()]))
        checker=FakeChecker(budget,default_verdict=0)
        class Triage:
            call_budget=budget
            last_calls=[]
            last_trace=[{'event':'EVIDENCE_GAP_TRIAGE_REVIEW','automatic':True,'semantically_certified':False}]
            calls=0
            def triage(self,v,diagnostics,existing_gaps):
                self.calls+=1
                if raises:raise raises
                return questions
        triage=Triage()
        return EvidenceCheckedCommittee(committee,checker,budget,gap_triage=triage),triage
    def test_advice_only_no_literal_research_question_added(self):
        from test_evidence_checked_committee import view as wrapper_view
        wrapped,triage=self.setup_wrapper()
        out=wrapped.evaluate(wrapper_view())
        self.assertEqual(out.essential_gaps,())
        self.assertEqual(triage.calls,1)
        self.assertFalse(wrapped.last_trace[-1]['semantically_certified'])
    def test_material_questions_merge_existing_gaps_without_raw_diagnostics(self):
        from test_evidence_checked_committee import view as wrapper_view
        wrapped,triage=self.setup_wrapper(('What independent adoption evidence was public?',),('retention',))
        out=wrapped.evaluate(wrapper_view())
        self.assertEqual(out.essential_gaps,('retention','What independent adoption evidence was public?'))
        self.assertEqual(out.decision.value,'MORE_DILIGENCE')
    def test_original_unknown_not_upgraded_when_triager_finds_no_new_questions(self):
        from test_evidence_checked_committee import view as wrapper_view
        from closed_loop.contracts import Decision
        wrapped,triage=self.setup_wrapper(decision=Decision.MORE_DILIGENCE)
        self.assertEqual(wrapped.evaluate(wrapper_view()).decision,Decision.MORE_DILIGENCE)
    def test_triage_stop_preserves_completed_support_and_debate(self):
        from test_evidence_checked_committee import view as wrapper_view
        wrapped,triage=self.setup_wrapper(raises=BudgetStopped('TRIAGE_STOP'))
        with self.assertRaisesRegex(BudgetStopped,'TRIAGE_STOP'):wrapped.evaluate(wrapper_view())
        self.assertTrue(any(e.get('stage')=='final_aggregation' for e in wrapped.last_trace))
        self.assertTrue(any(e.get('event')=='EVIDENCE_SUPPORT_REVIEW' for e in wrapped.last_trace))
        self.assertEqual(wrapped.last_trace[-1]['event'],'EVIDENCE_GAP_TRIAGE_STOPPED')
        self.assertEqual(triage.calls,1)
    def test_invalid_triage_string_not_silently_split_into_questions(self):
        from test_evidence_checked_committee import view as wrapper_view
        wrapped,triage=self.setup_wrapper(questions='not a tuple')
        with self.assertRaisesRegex(BudgetStopped,'INVALID_GAP_TRIAGE_QUESTIONS'):wrapped.evaluate(wrapper_view())
    def test_cross_company_triage_rejected_before_dispatch(self):
        budget=CallBudget(request());backend=FakeBackend([])
        triager=EvidenceGapTriage(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'CONTEXT_MISMATCH'):
            triager.triage(view(company_id='OTHER'),[diagnostic([('x',0)])],())
        self.assertEqual(backend.invocations,[])

if __name__=='__main__':unittest.main()
