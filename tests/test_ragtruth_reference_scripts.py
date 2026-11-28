"""Reference harness tests use invented cases and fake model responses only."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from closed_loop.guards import BudgetStopped
from closed_loop.ragas_faithfulness import FaithfulnessStatements,FaithfulnessVerdicts,StatementFaithfulnessVerdict

ROOT=Path(__file__).resolve().parents[1]

def load_script(name):
    path=ROOT/'scripts'/'experiments'/('ragtruth_reference_'+name+'_20261126.py')
    spec=importlib.util.spec_from_file_location('reference_'+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

predictor=load_script('predict');grader=load_script('grade');preparer=load_script('prepare')

class ReferencePredictionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.inputs=self.root/'inputs.json';self.protocol=self.root/'protocol.json';self.out=self.root/'run'
        rows=[dict(case_id='case'+str(i),source_id='source'+str(i),question='Question?',context='Context '+str(i),response='Answer '+str(i)) for i in range(6)]
        self.inputs.write_text(json.dumps(rows),encoding='utf-8')
        self.p=dict(protocol_id=predictor.PROTOCOL_ID,script_sha256=hashlib.sha256(Path(predictor.__file__).read_bytes()).hexdigest(),
            input_sha256=hashlib.sha256(self.inputs.read_bytes()).hexdigest(),case_ids=[x['case_id'] for x in rows],
            code_sha256={name:hashlib.sha256((ROOT/'src/closed_loop'/name).read_bytes()).hexdigest() for name in predictor._REQUIRED_CODE},
            as_of='2026-11-26T12:00:00+00:00',model='fixture-not-launched',max_model_cli_attempts=18,max_seconds=360,nli_batch_size=8)
        self.save_protocol()
    def save_protocol(self):self.protocol.write_text(json.dumps(self.p),encoding='utf-8')
    def execute(self,stop=None,factory_error=False):
        seen=[]
        class FakeBackend:
            process_count=0
            def generate(self,schema,messages,temperature):
                self.process_count+=1;seen.append([m.content for m in messages])
                if self.process_count==stop:raise BudgetStopped('FIXTURE_STOP_NO_PROCESS')
                data=json.loads(messages[-1].content.split('Input JSON: ',1)[1])
                if schema is FaithfulnessStatements:return FaithfulnessStatements([data['answer']])
                return FaithfulnessVerdicts([StatementFaithfulnessVerdict(s,'Fixture only',1) for s in data['statements']])
        backend=FakeBackend()
        def factory(req,exe):
            def create(budget,root):
                if factory_error:raise RuntimeError('private init detail')
                return backend
            return create
        with patch.object(predictor,'_forbidden_env_present',return_value=False),patch.object(predictor,'_resolve_executable',return_value='fixture'),patch.object(predictor,'_verify_subscription_auth',return_value=True),patch.object(predictor,'make_backend_factory',side_effect=factory),contextlib.redirect_stdout(io.StringIO()):
            code=predictor.run(self.inputs,self.protocol,self.out,True)
        return code,json.loads((self.out/'result.json').read_text()),seen
    def test_prediction_runs_without_any_gold_file_and_withholds_reference_fields(self):
        code,result,seen=self.execute()
        self.assertEqual(code,0);self.assertTrue(result['all_rows_completed'])
        self.assertEqual(len(result['completed']),6);self.assertEqual(result['model_cli_attempts'],12)
        self.assertEqual(result['logical_call_budget']['used']['model'],12)
        self.assertIsNone(result['aggregate_accuracy'])
        self.assertNotIn('reference_matches',result)
        flat='\n'.join(message for call in seen for message in call)
        for name in ['expected_supported','gold_label','labels']:
            self.assertNotIn('"'+name+'"',flat)
        self.assertFalse((self.root/'gold.json').exists())
    def test_partial_failure_keeps_every_case_without_group_score_or_retry(self):
        code,result,seen=self.execute(stop=4)
        self.assertEqual(code,2)
        self.assertEqual([len(result[k]) for k in ['completed','failed','not_run']],[1,1,4])
        self.assertEqual(len(seen),4);self.assertEqual(result['stop_reason'],'FIXTURE_STOP_NO_PROCESS')
        self.assertFalse(result['all_rows_completed']);self.assertIsNone(result['aggregate_accuracy'])
        self.assertEqual(result['logical_call_budget']['active'],0)
    def test_initialization_failure_keeps_all_cases_not_run(self):
        code,result,seen=self.execute(factory_error=True)
        self.assertEqual(code,2);self.assertEqual(len(result['not_run']),6)
        self.assertEqual(result['model_cli_attempts'],0);self.assertEqual(seen,[])
        self.assertNotIn('private init detail',json.dumps(result))
    def test_truthy_nonboolean_approval_does_not_authenticate(self):
        with patch.object(predictor,'_verify_subscription_auth') as auth,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(predictor.run(self.inputs,self.protocol,self.out,'yes'),1)
        auth.assert_not_called();self.assertFalse(self.out.exists())

    def test_invalid_label_fields_and_budget_rejected_before_auth_or_output(self):
        with patch.object(predictor,'_verify_subscription_auth') as auth:
            rows=json.loads(self.inputs.read_text());rows[0]['labels']=[];self.inputs.write_text(json.dumps(rows))
            with self.assertRaises(ValueError):predictor.run(self.inputs,self.protocol,self.out,True)
            self.p['max_model_cli_attempts']=19;self.save_protocol()
            with self.assertRaises(ValueError):predictor.run(self.inputs,self.protocol,self.out,True)
            auth.assert_not_called();self.assertFalse(self.out.exists())

class ReferenceGradingTests(unittest.TestCase):
    def fixtures(self):
        ids=['c'+str(i) for i in range(6)]
        gold=[dict(case_id=cid,expected_supported=int(i<3),original_span_count=int(i>=3),implicit_true_span_count=0) for i,cid in enumerate(ids)]
        guesses=[1,1,0,0,0,1]
        result=dict(completed=[dict(case_id=cid,score=guesses[i],prediction=guesses[i]) for i,cid in enumerate(ids)],failed=[],not_run=[],all_rows_completed=True)
        return result,gold,dict(case_ids=ids)
    def test_reference_confusion_is_relative_to_frozen_labels_not_general_accuracy(self):
        predictions,gold,protocol=self.fixtures();r=grader.grade(predictions,gold,protocol)
        self.assertEqual(r['reference_matches'],4)
        self.assertEqual(r['confusion_counts'],dict(true_positive=2,true_negative=2,false_positive=1,false_negative=1))
        self.assertIsNone(r['aggregate_accuracy']);self.assertFalse(r['company_quality_gold'])
    def test_failure_not_mapped_to_negative_or_included_in_group_agreement(self):
        predictions,gold,protocol=self.fixtures();predictions.update(completed=predictions['completed'][:1],failed=[{'case_id':'c1'}],not_run=[{'case_id':'c'+str(i)} for i in range(2,6)],all_rows_completed=False)
        r=grader.grade(predictions,gold,protocol)
        self.assertIsNone(r['reference_matches']);self.assertIsNone(r['sample_agreement'])
        self.assertEqual(len(r['cases']),6);self.assertIsNone(r['cases'][1]['prediction'])
    def test_dropped_or_duplicate_case_is_rejected(self):
        predictions,gold,protocol=self.fixtures();predictions['completed'].pop();predictions['all_rows_completed']=False
        with self.assertRaises(ValueError):grader.grade(predictions,gold,protocol)
        predictions,gold,protocol=self.fixtures();predictions['completed'][1]=dict(predictions['completed'][0])
        with self.assertRaises(ValueError):grader.grade(predictions,gold,protocol)
    def test_invalid_reference_mapping_and_nonfinite_prediction_rejected(self):
        predictions,gold,protocol=self.fixtures();gold[0]['expected_supported']=True
        with self.assertRaises(ValueError):grader.grade(predictions,gold,protocol)
        predictions,gold,protocol=self.fixtures();predictions['completed'][0]['score']=float('nan')
        with self.assertRaises(ValueError):grader.grade(predictions,gold,protocol)
    def test_cli_requires_matching_frozen_gold_and_prediction_protocol(self):
        predictions,gold,protocol=self.fixtures()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);g=root/'gold.json';p=root/'protocol.json';r=root/'predictions.json';out=root/'report.json'
            g.write_text(json.dumps(gold));protocol['gold_sha256']=hashlib.sha256(g.read_bytes()).hexdigest()
            protocol['grader_sha256']=hashlib.sha256(Path(grader.__file__).read_bytes()).hexdigest();p.write_text(json.dumps(protocol))
            predictions['protocol_sha256']='mismatch';r.write_text(json.dumps(predictions))
            with self.assertRaisesRegex(ValueError,'PROTOCOL_MISMATCH'):
                grader.main(['--predictions',str(r),'--gold',str(g),'--protocol',str(p),'--output',str(out)])
            self.assertFalse(out.exists())

    def test_valid_cli_grade_binds_grader_inputs_and_retains_case_denominator(self):
        predictions,gold,protocol=self.fixtures()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);g=root/'gold.json';p=root/'protocol.json';r=root/'predictions.json';out=root/'report.json'
            g.write_text(json.dumps(gold));protocol.update(gold_sha256=hashlib.sha256(g.read_bytes()).hexdigest(),
                grader_sha256=hashlib.sha256(Path(grader.__file__).read_bytes()).hexdigest(),input_sha256='1'*64)
            p.write_text(json.dumps(protocol));predictions.update(protocol_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),input_sha256='1'*64)
            r.write_text(json.dumps(predictions))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(grader.main(['--predictions',str(r),'--gold',str(g),'--protocol',str(p),'--output',str(out)]),0)
            result=json.loads(out.read_text());self.assertEqual(result['sample_agreement']['denominator'],6)
            self.assertEqual(result['reference_matches'],4);self.assertEqual(result['model_calls'],0)

class ReferencePreparationTests(unittest.TestCase):
    def test_source_unique_balanced_selection_ignores_low_quality_and_separates_labels(self):
        sources=[];responses=[]
        for i in range(6):
            sources.append(dict(source_id=str(i),task_type='QA',source_info=dict(question='question',passages='context')))
            responses.append(dict(id=str(i),source_id=str(i),split='test',quality='good',response='candidate',
                labels=[] if i<3 else [dict(implicit_true=i==3)]))
        responses.insert(0,dict(responses[0],quality='incorrect_refusal',id='skipped'))
        responses.insert(2,dict(responses[1],id='duplicate-source-skipped'))
        inputs,gold=preparer.select_cases(responses,sources)
        self.assertEqual(len(inputs),6);self.assertEqual(len({x['source_id'] for x in inputs}),6)
        self.assertEqual(sum(x['expected_supported'] for x in gold),3)
        self.assertTrue(all(set(x)=={'case_id','source_id','question','context','response'} for x in inputs))
        self.assertEqual(sum(x['implicit_true_span_count'] for x in gold),1)
    def test_bad_pinned_bytes_rejected_and_canonical_output_is_lf(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.jsonl';path.write_bytes(b'{}')
            with self.assertRaises(ValueError):preparer._read_verified_jsonl(path,'0'*40,2,100)
        raw=preparer._canonical_json_bytes([{'case_id':'fixture'}])
        self.assertNotIn(b'\r',raw);self.assertTrue(raw.endswith(b'\n'))

class ReferenceFingerprintTests(unittest.TestCase):
    def test_scripts_are_in_existing_readiness_resume_fingerprint(self):
        from workflow_automation.readiness import plan
        hashes=plan()['source_sha256']
        for name in ['prepare','predict','grade']:
            self.assertIn('scripts/experiments/ragtruth_reference_'+name+'_20261126.py',hashes)

if __name__=='__main__':unittest.main()
