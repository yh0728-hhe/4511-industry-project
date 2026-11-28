"""Fake-only follow-up reference selection and grading checks."""
import importlib.util,json,tempfile,unittest,hashlib,contextlib,io
from unittest.mock import patch
from closed_loop.guards import BudgetStopped
from closed_loop.ragas_faithfulness import FaithfulnessVerdicts,StatementFaithfulnessVerdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(name):
    path=ROOT/'scripts/experiments'/('ragtruth_followup_'+name+'_20261126.py')
    spec=importlib.util.spec_from_file_location('followup_'+name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
prep=load('prepare');grader=load('grade')
class FollowupSelectionTests(unittest.TestCase):
    def test_two_balanced_batches_exclude_previous_sources_without_resampling(self):
        old,_=prep._load_prior_module()
        responses=[dict(id=i,source_id='s'+str(i),split='test',quality='good',response='Answer',labels=[] if i%2==0 else [{}]) for i in range(20)]
        sources=[dict(source_id='s'+str(i),task_type='QA',source_info=dict(question='Question',passages='Source')) for i in range(20)]
        a,ag,b,bg=prep.select_followup(responses,sources,{'s'+str(i) for i in range(6)},old)
        self.assertEqual([r['case_id'] for r in a+b],['ragtruth-response-'+str(i) for i in range(6,18)])
        self.assertEqual(len({r['source_id'] for r in a+b}),12)
        self.assertEqual(sum(r['expected_supported'] for r in ag),3);self.assertEqual(sum(r['expected_supported'] for r in bg),3)
    def test_previous_reference_fields_or_duplicate_source_rejected(self):
        rows=[dict(case_id='c'+str(i),source_id='s'+str(i),question='q',context='c',response='r') for i in range(6)]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'previous.json'
            rows[0]['labels']=[];path.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):prep._read_previous_inputs(path)
            del rows[0]['labels'];rows[1]['source_id']=rows[0]['source_id'];path.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):prep._read_previous_inputs(path)
class FollowupGradeTests(unittest.TestCase):
    def data(self):
        ids=['c'+str(i) for i in range(12)]
        gold=[dict(case_id=c,expected_supported=int(i%2==0),original_span_count=int(i%2!=0),implicit_true_span_count=0) for i,c in enumerate(ids)]
        pred=dict(completed=[dict(case_id=c,score=float(i%2==0),prediction=int(i%2==0)) for i,c in enumerate(ids)],failed=[],not_run=[],all_rows_completed=True)
        return pred,gold,dict(case_ids=ids)
    def test_twelve_case_reference_metrics_not_general_accuracy(self):
        pred,gold,p=self.data();r=grader.grade(pred,gold,p)
        self.assertEqual(r['reference_matches'],12);self.assertEqual(r['sample_agreement']['denominator'],12)
        self.assertEqual(r['constant_not_supported_matches'],6);self.assertIsNone(r['aggregate_accuracy'])
    def test_incomplete_later_batch_retains_denominator_and_null_group_metric(self):
        pred,gold,p=self.data();pred.update(completed=pred['completed'][:7],failed=[dict(case_id='c7')],not_run=[dict(case_id='c'+str(i)) for i in range(8,12)],all_rows_completed=False)
        r=grader.grade(pred,gold,p);self.assertEqual(len(r['cases']),12);self.assertIsNone(r['sample_agreement']);self.assertIsNone(r['confusion_counts'])
    def test_missing_or_duplicated_case_refused(self):
        pred,gold,p=self.data();pred['completed'].pop()
        with self.assertRaises(ValueError):grader.grade(pred,gold,p)
        pred,gold,p=self.data();pred['completed'][1]=pred['completed'][0]
        with self.assertRaises(ValueError):grader.grade(pred,gold,p)
    def test_cli_hash_binding_and_exclusive_output(self):
        pred,gold,protocol=self.data()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);gp=root/'gold.json';pp=root/'protocol.json';rp=root/'prediction.json';out=root/'grade.json'
            gp.write_text(json.dumps(gold))
            protocol.update(protocol_id='RAGTRUTH-SOURCE-DISJOINT-12-20261126-001',
                gold_sha256=hashlib.sha256(gp.read_bytes()).hexdigest(),
                grader_sha256=hashlib.sha256(Path(grader.__file__).read_bytes()).hexdigest(),
                legacy_grader_sha256=hashlib.sha256(grader.OLD.read_bytes()).hexdigest(),input_sha256='1'*64)
            pp.write_text(json.dumps(protocol));pred.update(protocol_sha256='wrong',input_sha256='1'*64);rp.write_text(json.dumps(pred))
            args=['--predictions',str(rp),'--gold',str(gp),'--protocol',str(pp),'--output',str(out)]
            with self.assertRaises(ValueError):grader.main(args)
            self.assertFalse(out.exists())
            pred['protocol_sha256']=hashlib.sha256(pp.read_bytes()).hexdigest();rp.write_text(json.dumps(pred))
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(grader.main(args),0)
            self.assertEqual(json.loads(out.read_text())['sample_agreement']['denominator'],12)
            with self.assertRaises(ValueError):grader.main(args)

    def test_invalid_reference_mapping_refused(self):
        pred,gold,p=self.data();gold[0]['expected_supported']=True
        with self.assertRaises(ValueError):grader.grade(pred,gold,p)



predictor=load('predict')
class FollowupPredictionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.inputs=self.root/'inputs.json';self.protocol=self.root/'protocol.json';self.out=self.root/'run'
        self.rows=[dict(case_id='new'+str(i),source_id='new-source'+str(i),question='Question?',context='Source '+str(i),response='Response '+str(i)) for i in range(12)]
        self.inputs.write_text(json.dumps(self.rows),encoding='utf-8')
        self.rule=dict(protocol_id=predictor.PROTOCOL_ID,script_sha256=hashlib.sha256(Path(predictor.__file__).read_bytes()).hexdigest(),
            whole_response_script_sha256=predictor._WHOLE_RESPONSE_SHA256,
            prior_predictor_script_sha256=hashlib.sha256((ROOT/'scripts/experiments/ragtruth_reference_predict_20261126.py').read_bytes()).hexdigest(),
            input_sha256=hashlib.sha256(self.inputs.read_bytes()).hexdigest(),case_ids=[r['case_id'] for r in self.rows],
            excluded_source_ids=['old-source'+str(i) for i in range(6)],
            code_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'src/closed_loop').glob('*.py')},
            as_of='2026-11-26T12:00:00+00:00',model='fixture-no-process',max_model_cli_attempts=12,max_seconds=240)
        self.save_rule()
    def save_rule(self):self.protocol.write_text(json.dumps(self.rule),encoding='utf-8')
    def execute(self,stop=None):
        seen=[]
        class Fake:
            process_count=0
            def generate(self,schema,messages,temperature):
                self.process_count+=1;seen.append([m.content for m in messages])
                if self.process_count==stop:raise BudgetStopped('FIXTURE_STOP')
                payload=json.loads(messages[-1].content.split('Input JSON: ',1)[1])
                assert len(payload['statements'])==1
                return FaithfulnessVerdicts([StatementFaithfulnessVerdict(payload['statements'][0],'Fixture',1)])
        backend=Fake()
        with patch.object(predictor,'_forbidden_env_present',return_value=False),patch.object(predictor,'_resolve_executable',return_value='fixture'),patch.object(predictor,'_verify_subscription_auth',return_value=True),patch.object(predictor,'make_backend_factory',return_value=lambda budget,out:backend),contextlib.redirect_stdout(io.StringIO()):
            code=predictor.run(self.inputs,self.protocol,self.out,True)
        return code,json.loads((self.out/'result.json').read_text()),seen
    def test_twelve_calls_no_gold_file_or_reference_fields(self):
        code,r,seen=self.execute();self.assertEqual(code,0);self.assertEqual(r['model_cli_attempts'],12)
        self.assertEqual(r['logical_call_budget']['used']['model'],12);self.assertTrue(r['all_rows_completed'])
        self.assertIsNone(r['aggregate_accuracy']);self.assertFalse((self.root/'gold.json').exists())
        for key in ['expected_supported','original_span_count','implicit_true_span_count']:
            self.assertNotIn('"'+key+'"','\n'.join(m for call in seen for m in call))
    def test_later_failure_preserves_all_twelve_and_failed_call(self):
        code,r,seen=self.execute(stop=8);self.assertEqual(code,2)
        self.assertEqual([len(r[k]) for k in ['completed','failed','not_run']],[7,1,4])
        self.assertEqual(len(json.loads((self.out/'row_07_calls.json').read_text())),1)
        self.assertEqual(r['stop_reason'],'FIXTURE_STOP');self.assertEqual(r['logical_call_budget']['active'],0)
    def test_old_source_or_label_field_refused_before_auth(self):
        for key,value in [('source_id','old-source0'),('labels',[])]:
            rows=[dict(r) for r in self.rows];rows[0][key]=value;self.inputs.write_text(json.dumps(rows))
            with patch.object(predictor,'_verify_subscription_auth') as auth,self.assertRaises(ValueError):
                predictor.run(self.inputs,self.protocol,self.out,True)
            auth.assert_not_called();self.assertFalse(self.out.exists())
    def test_extra_cap_or_incomplete_source_hashes_refused_before_auth(self):
        for key,value in [('max_model_cli_attempts',13),('code_sha256',{}),('prior_predictor_script_sha256','wrong')]:
            old=self.rule[key];self.rule[key]=value;self.save_rule()
            with patch.object(predictor,'_verify_subscription_auth') as auth,self.assertRaises(ValueError):
                predictor.run(self.inputs,self.protocol,self.out,True)
            auth.assert_not_called();self.rule[key]=old
    def test_nonboolean_approval_starts_nothing(self):
        with patch.object(predictor,'_verify_subscription_auth') as auth,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(predictor.run(self.inputs,self.protocol,self.out,'yes'),1)
        auth.assert_not_called();self.assertFalse(self.out.exists())

if __name__=='__main__':unittest.main()
