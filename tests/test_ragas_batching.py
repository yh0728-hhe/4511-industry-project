"""Mocked-call tests only; verdicts here are fixture doubles, not semantic accuracy claims."""
import json
import unittest

from closed_loop.guards import BudgetStopped
from closed_loop.ragas_faithfulness import (
    RagasFaithfulnessChecker,
    FaithfulnessStatements,
    FaithfulnessVerdicts,
    StatementFaithfulnessVerdict,
)
from test_ragas_faithfulness import setup, FakeFaithfulness


class BatchFakeBackend:
    def __init__(self,statements,verdict_fn=None,stop_after=None,budget=None):
        self.statements=statements
        self.verdict_fn=verdict_fn or (lambda batch:[StatementFaithfulnessVerdict(s,'ok',1) for s in batch])
        self.seen=[]
        self.stop_after=stop_after
        self.budget=budget
        self.nli_calls=0

    def generate(self,schema,messages,temperature):
        self.seen.append((schema,messages))
        if schema is FaithfulnessStatements:
            return FaithfulnessStatements(statements=self.statements)
        self.nli_calls+=1
        payload=json.loads(messages[-1].content.split('Input JSON: ',1)[1])
        batch=payload['statements']
        result=FaithfulnessVerdicts(statements=self.verdict_fn(batch))
        if self.stop_after is not None and self.nli_calls==self.stop_after:
            self.budget.stop('TEST_FORCED_STOP')
        return result


class RagasBatchingTests(unittest.TestCase):
    def test_eighteen_statements_split_into_three_nli_calls(self):
        req,budget,view=setup()
        statements=[f'Statement {i}.' for i in range(18)]
        backend=BatchFakeBackend(statements)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        checker=RagasFaithfulnessChecker(backend,budget)
        out=checker.assess(view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(budget.used['model'],4)
        nli_traces=[t for t in checker.last_trace if t['stage']=='nli']
        self.assertEqual(len(nli_traces),3)
        self.assertEqual([t['batch_index'] for t in nli_traces],[0,1,2])
        self.assertEqual([t['start'] for t in nli_traces],[0,8,16])
        self.assertEqual([t['size'] for t in nli_traces],[8,8,2])
        self.assertEqual([j['statement'] for j in out['judgments']],statements)
        self.assertEqual(out['binding']['nli_batch_count'],3)
        self.assertEqual(out['binding']['nli_batch_size'],8)

    def test_budget_stop_after_first_nli_retains_completed_trace_no_score_no_retry(self):
        req,budget,view=setup()
        statements=[f'Statement {i}.' for i in range(18)]
        backend=BatchFakeBackend(statements,stop_after=1,budget=budget)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        checker=RagasFaithfulnessChecker(backend,budget)
        with self.assertRaises(BudgetStopped):
            checker.assess(view,question='q',response='r',cited_fact_ids=[market_id])
        nli_traces=[t for t in checker.last_trace if t['stage']=='nli']
        self.assertEqual(len(nli_traces),1)
        self.assertEqual(nli_traces[0]['batch_index'],0)
        self.assertEqual(backend.nli_calls,1)
        self.assertEqual(len(checker.last_calls),2)

    def test_later_backend_timeout_preserves_partial_trace_without_returning_score(self):
        req,budget,view=setup()
        statements=[f'Statement {i}.' for i in range(15)]
        class TimeoutBackend(BatchFakeBackend):
            def generate(self,schema,messages,temperature):
                if schema is FaithfulnessVerdicts and self.nli_calls==1:
                    self.seen.append((schema,messages))
                    self.nli_calls+=1
                    raise BudgetStopped('CLI_PROCESS_TIMEOUT')
                return super().generate(schema,messages,temperature)
        backend=TimeoutBackend(statements)
        checker=RagasFaithfulnessChecker(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'CLI_PROCESS_TIMEOUT'):
            checker.assess(view,question='q',response='r',
                cited_fact_ids=[view.qa_pairs[0]['fact_id']])
        self.assertEqual(budget.stop_reason,'CLI_PROCESS_TIMEOUT')
        self.assertEqual(budget.used['model'],3)
        self.assertEqual(backend.nli_calls,2)
        completed=[row for row in checker.last_trace if row['stage']=='nli']
        self.assertEqual(len(completed),1)
        self.assertEqual([j['statement'] for j in completed[0]['output']['statements']],statements[:8])
        self.assertFalse(any('score' in row for row in checker.last_trace))
        self.assertEqual(len(checker.last_calls),3)

    def test_wrong_batch_statement_rejected_even_if_belongs_another_batch(self):
        req,budget,view=setup()
        statements=['A.','B.','C.']
        def verdict_fn(batch):
            if batch==['A.']:return [StatementFaithfulnessVerdict('B.','wrong',1)]
            return [StatementFaithfulnessVerdict(s,'ok',1) for s in batch]
        backend=BatchFakeBackend(statements,verdict_fn=verdict_fn)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        checker=RagasFaithfulnessChecker(backend,budget,max_statements_per_call=1)
        with self.assertRaisesRegex(BudgetStopped,'FAITHFULNESS_VERDICT_STATEMENT_MISMATCH'):
            checker.assess(view,question='q',response='r',cited_fact_ids=[market_id])

    def test_reversed_within_batch_output_reorders_overall_correctly(self):
        req,budget,view=setup()
        statements=['A.','B.','C.','D.']
        def verdict_fn(batch):
            return [StatementFaithfulnessVerdict(s,'ok-'+s,1) for s in reversed(batch)]
        backend=BatchFakeBackend(statements,verdict_fn=verdict_fn)
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        checker=RagasFaithfulnessChecker(backend,budget,max_statements_per_call=2)
        out=checker.assess(view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual([j['statement'] for j in out['judgments']],statements)
        self.assertEqual(budget.used['model'],3)

    def test_small_input_two_calls(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        market_id=next(r['fact_id'] for r in view.qa_pairs if r['source_id']=='market-2024')
        checker=RagasFaithfulnessChecker(backend,budget)
        checker.assess(view,question='q',response='r',cited_fact_ids=[market_id])
        self.assertEqual(budget.used['model'],2)
        self.assertEqual(len(backend.seen),2)

    def test_bad_constructor_zero_rejected(self):
        req,budget,view=setup();backend=FakeFaithfulness()
        with self.assertRaises(ValueError):
            RagasFaithfulnessChecker(backend,budget,max_statements_per_call=0)
        self.assertEqual(backend.seen,[])


if __name__=='__main__':unittest.main()
