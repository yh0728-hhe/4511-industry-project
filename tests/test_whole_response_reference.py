"""Whole-response experiment fixture checks: no real model or network."""
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
from closed_loop.ragas_faithfulness import FaithfulnessVerdicts,StatementFaithfulnessVerdict
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('whole_response_tested',ROOT/'scripts/experiments/whole_response_reference_predict_20261126.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class WholeResponseTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.inputs=self.root/'inputs.json';self.protocol=self.root/'protocol.json';self.out=self.root/'run'
        rows=[dict(case_id='c'+str(i),source_id='s'+str(i),question='Question?',context='Source '+str(i),response='Response '+str(i)) for i in range(6)]
        self.inputs.write_text(json.dumps(rows),encoding='utf-8')
        self.rule=dict(protocol_id=p.PROTOCOL_ID,script_sha256=hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest(),
            prior_predictor_script_sha256=p._PRIOR_PREDICTOR_SHA256,input_sha256=hashlib.sha256(self.inputs.read_bytes()).hexdigest(),
            case_ids=[r['case_id'] for r in rows],code_sha256={n:hashlib.sha256((ROOT/'src/closed_loop'/n).read_bytes()).hexdigest() for n in p._REQUIRED_CODE},
            as_of='2026-11-26T12:00:00+00:00',model='fixture-no-process',max_model_cli_attempts=6,max_seconds=240)
        self.save_rule()
    def save_rule(self):self.protocol.write_text(json.dumps(self.rule),encoding='utf-8')
    def execute(self,*,stop=None,mismatch=False,init_failure=False):
        seen=[]
        class Fake:
            process_count=0
            def generate(self,schema,messages,temperature):
                self.process_count+=1;seen.append([m.content for m in messages])
                if self.process_count==stop:raise BudgetStopped('FIXTURE_STOP')
                payload=json.loads(messages[-1].content.split('Input JSON: ',1)[1])
                self_payload=payload['statements'];assert len(self_payload)==1
                return FaithfulnessVerdicts([StatementFaithfulnessVerdict('wrong' if mismatch else self_payload[0],'Fixture only',1)])
        b=Fake()
        def factory(request,exe):
            def create(budget,out):
                if init_failure:raise ValueError('private initialization detail')
                return b
            return create
        with patch.object(p,'_forbidden_env_present',return_value=False),patch.object(p,'_resolve_executable',return_value='fake'),patch.object(p,'_verify_subscription_auth',return_value=True),patch.object(p,'make_backend_factory',side_effect=factory),contextlib.redirect_stdout(io.StringIO()):
            code=p.run(self.inputs,self.protocol,self.out,True)
        return code,json.loads((self.out/'result.json').read_text()),seen
    def test_six_whole_response_calls_without_gold_or_decomposition(self):
        code,r,seen=self.execute();self.assertEqual(code,0);self.assertEqual(len(seen),6)
        self.assertTrue(r['all_rows_completed']);self.assertEqual(r['model_cli_attempts'],6)
        self.assertEqual(r['logical_call_budget']['used']['model'],6);self.assertIsNone(r['aggregate_accuracy'])
        for call in seen:
            for key in ['expected_supported','original_span_count','implicit_true_span_count']:
                self.assertNotIn('"'+key+'"','\n'.join(call))
        self.assertFalse((self.root/'gold.json').exists())
    def test_later_stop_retains_calls_and_six_case_partition(self):
        code,r,seen=self.execute(stop=3);self.assertEqual(code,2)
        self.assertEqual([len(r[k]) for k in ['completed','failed','not_run']],[2,1,3])
        self.assertEqual(r['stop_reason'],'FIXTURE_STOP');self.assertEqual(len(seen),3)
        calls=json.loads((self.out/'row_02_calls.json').read_text());self.assertEqual(len(calls),1)
        self.assertEqual(r['logical_call_budget']['active'],0)
    def test_exact_copy_mismatch_stops_instead_of_grading(self):
        code,r,seen=self.execute(mismatch=True);self.assertEqual(code,2)
        self.assertEqual(r['stop_reason'],'WHOLE_RESPONSE_STATEMENT_NOT_EXACT_COPY')
        self.assertEqual([len(r[k]) for k in ['completed','failed','not_run']],[0,1,5])
        self.assertEqual(len(json.loads((self.out/'row_00_calls.json').read_text())),1)
    def test_init_failure_preserves_all_not_run(self):
        code,r,seen=self.execute(init_failure=True);self.assertEqual(code,2)
        self.assertEqual(len(r['not_run']),6);self.assertEqual(r['model_cli_attempts'],0)
        self.assertNotIn('private initialization detail',json.dumps(r))
    def test_invalid_caps_or_prior_hash_rejected_before_auth(self):
        for key,value in [('max_model_cli_attempts',6.0),('max_model_cli_attempts',7),('prior_predictor_script_sha256','wrong')]:
            with self.subTest(key=key,value=value):
                old=self.rule[key];self.rule[key]=value;self.save_rule()
                with patch.object(p,'_verify_subscription_auth') as auth,self.assertRaises(ValueError):
                    p.run(self.inputs,self.protocol,self.out,True)
                auth.assert_not_called();self.assertFalse(self.out.exists());self.rule[key]=old
    def test_nonboolean_approval_has_no_side_effect(self):
        with patch.object(p,'_verify_subscription_auth') as auth,contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(p.run(self.inputs,self.protocol,self.out,'yes'),1)
        auth.assert_not_called();self.assertFalse(self.out.exists())

if __name__=='__main__':unittest.main()
