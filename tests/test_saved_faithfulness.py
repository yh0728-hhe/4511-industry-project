import hashlib,json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from dataclasses import replace
from closed_loop.fixtures import request,FixtureProvider
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.runtime import FactStore,committee_input
from closed_loop.saved_faithfulness import assess_saved_rationale
from closed_loop.ragas_faithfulness import RagasFaithfulnessChecker,FaithfulnessStatements,FaithfulnessVerdicts,StatementFaithfulnessVerdict

class Checker:
    def __init__(self,budget,fail=False):self.call_budget=budget;self.calls=[];self.fail=fail
    def assess(self,view,**kw):
        self.calls.append((view,kw))
        if self.fail:raise BudgetStopped('fixture-stop')
        return dict(score=0,semantic_support_certified=False)

class SavedFaithfulnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir();self.target=self.root/'target'
        self.req=request();self.budget=CallBudget(self.req);provider=FixtureProvider();gate=TemporalGateway(self.req,provider.ledger)
        fact,error=gate.admit(provider.market);assert not error
        store=FactStore();store.merge([fact]);self.view=committee_input(self.req,store,1)
        row=self.view.qa_pairs[0]
        self.plan=dict(status='SOURCE_ADMITTED_BEFORE_MODEL_CONSTRUCTION',company=dict(company_id=self.view.company_id),
            as_of=self.view.as_of,mandate=self.view.mandate,source_id=row['source_id'],source_sha256=hashlib.sha256(row['answer'].encode()).hexdigest())
        self.proposal=dict(decision='MORE_DILIGENCE',rationale='Saved rationale.',essential_gaps=['retention'],thesis=None,admitted_fact_ids=[row['fact_id']])
        self.saveplan();self.saveproposal();self.checker=Checker(self.budget)
    def saveplan(self):
        self.plan.pop('fingerprint',None);self.plan['fingerprint']=hashlib.sha256(json.dumps(self.plan,sort_keys=True).encode()).hexdigest()
        (self.source/'plan.json').write_text(json.dumps(self.plan))
    def saveproposal(self):(self.source/'proposal.json').write_text(json.dumps(self.proposal))
    def runcheck(self,**kw):return assess_saved_rationale(self.source,self.target,view=self.view,checker=self.checker,**kw)
    def test_rationale_only_and_original_bytes_unchanged(self):
        before={p.name:p.read_bytes() for p in self.source.iterdir()};out=self.runcheck()
        self.assertEqual(self.checker.calls[0][1]['response'],'Saved rationale.')
        self.assertEqual(out['unreviewed'],['thesis','essential_gaps','draft_trace'])
        self.assertNotIn('decision',out);self.assertEqual(before,{p.name:p.read_bytes() for p in self.source.iterdir()})
    def test_bad_plan_no_dispatch(self):
        self.plan['source_sha256']='changed';(self.source/'plan.json').write_text(json.dumps(self.plan))
        with self.assertRaises(ValueError):self.runcheck()
        self.assertFalse(self.checker.calls);self.assertFalse(self.target.exists())
    def test_context_mismatches_no_dispatch(self):
        for field,value in [('company_id','other'),('mandate','other'),('as_of','2024-04-03T00:00:00+00:00')]:
            with self.subTest(field=field):
                view=replace(self.view,**{field:value})
                with self.assertRaises(ValueError):assess_saved_rationale(self.source,self.target,view=view,checker=self.checker)
        self.assertFalse(self.checker.calls)
    def test_source_hash_mismatch_no_dispatch(self):
        self.plan['source_sha256']='0'*64;self.saveplan()
        with self.assertRaises(ValueError):self.runcheck()
        self.assertFalse(self.checker.calls)
    def test_foreign_fact_no_dispatch(self):
        self.proposal['admitted_fact_ids']=['foreign'];self.saveproposal()
        with self.assertRaises(ValueError):self.runcheck()
        self.assertFalse(self.checker.calls)
    def test_future_source_no_dispatch(self):
        self.view=replace(self.view,qa_pairs=(dict(self.view.qa_pairs[0],available_by='2025-01-01T00:00:00+00:00'),))
        with self.assertRaises(ValueError):self.runcheck()
        self.assertFalse(self.checker.calls);self.assertFalse(self.target.exists())
    def test_output_collision_and_inside_source_no_dispatch(self):
        self.target.mkdir()
        with self.assertRaises(ValueError):self.runcheck()
        with self.assertRaises(ValueError):assess_saved_rationale(self.source,self.source/'bad',view=self.view,checker=self.checker)
        self.assertFalse(self.checker.calls)
    def test_stopped_budget_no_output_or_dispatch(self):
        self.budget.stop('already-stopped')
        with self.assertRaisesRegex(BudgetStopped,'already-stopped'):self.runcheck()
        self.assertFalse(self.checker.calls);self.assertFalse(self.target.exists())
    def test_failed_attempt_preserved_and_no_retry(self):
        self.checker.fail=True
        with self.assertRaisesRegex(BudgetStopped,'fixture-stop'):self.runcheck()
        out=json.loads((self.target/'faithfulness_result.json').read_text());self.assertEqual(out['reason'],'fixture-stop')
        with self.assertRaises(ValueError):self.runcheck()
        self.assertEqual(len(self.checker.calls),1)
    def test_legacy_requires_explicit_choice(self):
        (self.source/'result.json').write_bytes((self.source/'proposal.json').read_bytes());(self.source/'proposal.json').unlink()
        with self.assertRaises(ValueError):self.runcheck()
        self.assertFalse(self.checker.calls);self.runcheck(proposal_name='result.json')
        intent=json.loads((self.target/'intent.json').read_text());self.assertTrue(intent['legacy_source_explicit'])
    def test_real_ragas_adapter_two_metered_fixture_calls(self):
        class Backend:
            def generate(self,schema,messages,temperature):
                if schema is FaithfulnessStatements:return FaithfulnessStatements(['Saved rationale.'])
                return FaithfulnessVerdicts([StatementFaithfulnessVerdict('Saved rationale.','Fixture unsupported.',0)])
        self.checker=RagasFaithfulnessChecker(Backend(),self.budget);out=self.runcheck()
        self.assertEqual(self.budget.used['model'],2);self.assertEqual(out['automatic_diagnostics']['score'],0)
        self.assertFalse(out['semantic_support_certified'])

if __name__=='__main__':unittest.main()
