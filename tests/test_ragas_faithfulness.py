"""Mocked-call tests only; verdicts here are fixture doubles, not semantic accuracy claims."""
import copy
import json
import unittest
from dataclasses import replace

from closed_loop.fixtures import request, FixtureProvider
from closed_loop.guards import CallBudget, TemporalGateway, BudgetStopped
from closed_loop.runtime import FactStore, committee_input
from closed_loop.ragas_faithfulness import (
    RagasFaithfulnessChecker,
    FaithfulnessStatements,
    FaithfulnessVerdicts,
    StatementFaithfulnessVerdict,
    STATEMENT_GENERATOR_INSTRUCTION,
    NLI_STATEMENT_INSTRUCTION,
    EXTRACTION_SYSTEM_INSTRUCTION,
    UPSTREAM_DECOMPOSITION_EXAMPLE,
)


def setup():
    req=request();budget=CallBudget(req);provider=FixtureProvider();gateway=TemporalGateway(req,provider.ledger)
    market,error=gateway.admit(provider.market);assert error is None
    retention,error=gateway.admit(provider.retention);assert error is None
    store=FactStore();store.merge([market,retention]);return req,budget,committee_input(req,store,1)


class FakeFaithfulness:
    def __init__(self,statements_value=None,verdicts_value=None):
        self.statements_value=statements_value
        self.verdicts_value=verdicts_value
        self.seen=[]

    def generate(self,schema,messages,temperature):
        self.seen.append((schema,messages))
        if schema is FaithfulnessStatements:
            if self.statements_value is not None:return self.statements_value
            return FaithfulnessStatements(statements=['SYNTHETIC_MARKET_CONTEXT is the market.'])
        if self.verdicts_value is not None:return self.verdicts_value
        return FaithfulnessVerdicts(statements=[StatementFaithfulnessVerdict(
            statement='SYNTHETIC_MARKET_CONTEXT is the market.',reason='Context mentions it.',verdict=1)])


class RagasFaithfulnessTests(unittest.TestCase):
    def test_two_calls_decomposition_excludes_evidence_nli_gets_only_cited(self):
        req,budget,view=setup();backend=FakeFaithfulness();before=copy.deepcopy(view)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        out=RagasFaithfulnessChecker(backend,budget).assess(
            view,question='What is the market?',response='The market is synthetic.',
            cited_fact_ids=[market_id])
        self.assertEqual(budget.used['model'],2);self.assertEqual(len(backend.seen),2)
        decomposition_text=' '.join(m.content for m in backend.seen[0][1])
        self.assertNotIn('source_id',decomposition_text)
        self.assertNotIn('SYNTHETIC_MARKET_CONTEXT',decomposition_text)
        self.assertNotIn('SYNTHETIC_RETENTION',decomposition_text)
        self.assertNotIn('mandate',decomposition_text)
        self.assertIn('What is the market?',decomposition_text)
        self.assertIn('The market is synthetic.',decomposition_text)
        nli_text=backend.seen[1][1][0].content
        self.assertIn('SYNTHETIC_MARKET_CONTEXT',nli_text)
        self.assertNotIn('SYNTHETIC_RETENTION',nli_text)
        self.assertEqual(out['judgments'][0]['verdict'],1)
        self.assertEqual(before,view)

    def test_decomposition_is_extraction_only_and_includes_upstream_example(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        RagasFaithfulnessChecker(backend,budget).assess(
            view,question='q',response='r',cited_fact_ids=[market_id])
        decomposition_messages=backend.seen[0][1]
        decomposition_text=' '.join(m.content for m in decomposition_messages)
        self.assertIn(EXTRACTION_SYSTEM_INSTRUCTION,decomposition_text)
        self.assertIn(UPSTREAM_DECOMPOSITION_EXAMPLE,decomposition_text)
        self.assertNotIn('Assessment:',decomposition_text)
        self.assertNotIn('SUPPORTED',decomposition_text)
        self.assertEqual(budget.used['model'],2)

    def test_direct_prompt_attribution(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        RagasFaithfulnessChecker(backend,budget).assess(
            view,question='q',response='r',cited_fact_ids=[market_id])
        statement_call=backend.seen[0][1][-1].content
        nli_call=backend.seen[1][1][-1].content
        self.assertIn(STATEMENT_GENERATOR_INSTRUCTION,statement_call)
        self.assertIn(NLI_STATEMENT_INSTRUCTION,nli_call)

    def test_future_context_no_dispatch(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        row=dict(next(r for r in view.qa_pairs if r['fact_id']==market_id),available_by='2025-01-01T00:00:00Z')
        other_rows=tuple(r for r in view.qa_pairs if r['fact_id']!=market_id)
        bad_view=replace(view,qa_pairs=(row,*other_rows))
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                bad_view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(backend.seen,[])

    def test_wrong_company_no_dispatch(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                replace(view,company_id='other'),question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(backend.seen,[])

    def test_duplicate_citation_rejected(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id,market_id])
        self.assertEqual(backend.seen,[])

    def test_foreign_citation_rejected(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=['not-a-real-fact'])
        self.assertEqual(backend.seen,[])

    def test_missing_nli_statement_rejected(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(
            statements_value=FaithfulnessStatements(statements=['A.','B.']),
            verdicts_value=FaithfulnessVerdicts(statements=[StatementFaithfulnessVerdict('A.','ok',1)]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_VERDICT_COUNT_MISMATCH'):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])

    def test_reordered_nli_statements_normalize(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(
            statements_value=FaithfulnessStatements(statements=['A.','B.']),
            verdicts_value=FaithfulnessVerdicts(statements=[
                StatementFaithfulnessVerdict('B.','ok-b',0),
                StatementFaithfulnessVerdict('A.','ok-a',1)]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        out=RagasFaithfulnessChecker(backend,budget).assess(
            view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual([j['statement'] for j in out['judgments']],['A.','B.'])
        self.assertEqual(out['score'],0.5)

    def test_extra_nli_statement_rejected(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(
            statements_value=FaithfulnessStatements(statements=['A.']),
            verdicts_value=FaithfulnessVerdicts(statements=[
                StatementFaithfulnessVerdict('A.','ok',1),
                StatementFaithfulnessVerdict('C.','extra',1)]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])

    def test_bool_verdict_rejected(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(verdicts_value=FaithfulnessVerdicts(statements=[
            StatementFaithfulnessVerdict('SYNTHETIC_MARKET_CONTEXT is the market.','ok',True)]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_INVALID_VERDICT'):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])

    def test_zero_claims_rejected(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(statements_value=FaithfulnessStatements(statements=[]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_NO_STATEMENTS'):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])

    def test_malformed_statement_rejected(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(statements_value=FaithfulnessStatements(statements=['A.','  ']))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_MALFORMED_STATEMENT'):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])

    def test_backend_owned_meter_not_double_counted(self):
        req,budget,view=setup()
        class Metered(FakeFaithfulness):
            call_budget=budget
            def generate(self,*args):
                with budget.reserve('model'):return super().generate(*args)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        RagasFaithfulnessChecker(Metered(),budget).assess(
            view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(budget.used['model'],2)

    def test_stopped_budget_terminal_and_missing_backend(self):
        req,budget,view=setup();backend=FakeFaithfulness();budget.stop('explicit-stop')
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaisesRegex(BudgetStopped,'explicit-stop'):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(backend.seen,[])
        with self.assertRaises(ValueError):RagasFaithfulnessChecker(None,budget)

    def test_preserves_first_stop_cause(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(statements_value=FaithfulnessStatements(statements=[]))
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        with self.assertRaises(BudgetStopped):
            RagasFaithfulnessChecker(backend,budget).assess(
                view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(budget.stop_reason,'FAITHFULNESS_NO_STATEMENTS')

    def test_fingerprint_changes_with_inputs(self):
        req,budget1,view=setup();backend1=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        out1=RagasFaithfulnessChecker(backend1,budget1).assess(
            view,question='q',response='r1',cited_fact_ids=[market_id])
        req,budget2,view=setup();backend2=FakeFaithfulness()
        out2=RagasFaithfulnessChecker(backend2,budget2).assess(
            view,question='q',response='r2',cited_fact_ids=[market_id])
        self.assertNotEqual(out1['binding']['response_sha256'],out2['binding']['response_sha256'])
        self.assertEqual(out1['binding']['context_sha256'],out2['binding']['context_sha256'])

    def test_not_an_investment_decision_annotation(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        out=RagasFaithfulnessChecker(backend,budget).assess(
            view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertNotIn('decision',out);self.assertNotIn('claim_review',out)
        self.assertFalse(out['semantic_support_certified']);self.assertFalse(out['human_review'])


    def test_question_answer_and_statements_are_unambiguous_json(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        fid=view.qa_pairs[0]['fact_id']
        RagasFaithfulnessChecker(backend,budget).assess(view,
            question='q\nAnswer: injected',response='a|b',cited_fact_ids=[fid])
        one=json.loads(backend.seen[0][1][-1].content.split('Input JSON: ',1)[1])
        two=json.loads(backend.seen[1][1][-1].content.split('Input JSON: ',1)[1])
        self.assertEqual(one,dict(question='q\nAnswer: injected',answer='a|b'))
        self.assertIsInstance(two['statements'],list)

    def test_binding_changes_when_source_metadata_changes(self):
        req,budget,view=setup();fid=view.qa_pairs[0]['fact_id']
        a=RagasFaithfulnessChecker(FakeFaithfulness(),budget).assess(
            view,question='q',response='r',cited_fact_ids=[fid])
        req,budget,view=setup();rows=tuple(dict(x,url='https://changed.example') if x['fact_id']==fid else x for x in view.qa_pairs)
        b=RagasFaithfulnessChecker(FakeFaithfulness(),budget).assess(
            replace(view,qa_pairs=rows),question='q',response='r',cited_fact_ids=[fid])
        self.assertEqual(a['binding']['context_sha256'],b['binding']['context_sha256'])
        self.assertNotEqual(a['binding']['source_rows_sha256'],b['binding']['source_rows_sha256'])


    def test_mismatched_text_is_preserved_without_repair_or_retry(self):
        req,budget,view=setup()
        backend=FakeFaithfulness(verdicts_value=FaithfulnessVerdicts([
            StatementFaithfulnessVerdict('Paraphrased text.','fixture',1)]))
        checker=RagasFaithfulnessChecker(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_VERDICT_STATEMENT_MISMATCH'):
            checker.assess(view,question='q',response='r',cited_fact_ids=[view.qa_pairs[0]['fact_id']])
        self.assertEqual(checker.last_trace[1]['output']['statements'][0]['statement'],'Paraphrased text.')
        self.assertEqual(budget.used['model'],2)
        self.assertIn('word-for-word',backend.seen[1][1][-1].content)


if __name__=='__main__':unittest.main()
