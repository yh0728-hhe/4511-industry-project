import json
from dataclasses import replace
from pathlib import Path
from datetime import datetime,timedelta,timezone
from tempfile import TemporaryDirectory
import unittest
from closed_loop.fixtures import request,source
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.single_analyst import SingleAnalystAssessment
from closed_loop.paired_evaluation import execute_fixed_evidence_pair,execute_verified_evidence_pair
from test_package_source import wheel


class PairBackend(NativeFixtureBackend):
    def __init__(self):super().__init__();self.baseline_inputs=[];self.committee_inputs=[];self.arm_events=[]
    def generate(self,schema,messages,temperature):
        context=json.loads(messages[0].content.split('\n',1)[1])
        if schema is SingleAnalystAssessment:
            self.arm_events.append('single_analyst')
            self.baseline_inputs.append(context)
            return SingleAnalystAssessment('MORE_DILIGENCE','Fixture unknown',['retention'],None)
        self.arm_events.append('committee')
        self.committee_inputs.append(context)
        return super().generate(schema,messages,temperature)


class PairedEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'pair'
        self.raw,self.meta=wheel();self.backend=PairBackend();self.factories=[]
    def run_case(self,**updates):
        def factory(budget,root):self.factories.append(budget);return self.backend
        args=dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_model_calls=24,max_search_calls=0),artifact_bytes=self.raw,file_metadata=self.meta,expected_package='sample-sdk',artifact_format='wheel',output_dir=self.root,backend_factory=factory,approved=True)
        args.update(updates);return execute_fixed_evidence_pair(**args)
    def test_exact_same_evidence_and_shared_budget(self):
        result=self.run_case()
        self.assertEqual(len(self.factories),1)
        self.assertEqual(self.backend.baseline_inputs[0]['evidence'],self.backend.committee_inputs[0]['evidence'])
        for key in ('company_id','as_of','mandate'):
            self.assertEqual(self.backend.baseline_inputs[0][key],self.backend.committee_inputs[0][key])
        self.assertTrue((self.root/'single_analyst_raw.json').is_file())
        self.assertTrue((self.root/'committee_draft_trace.json').is_file())
        self.assertEqual(result['arms'][0]['evidence_sha256'],result['arms'][1]['evidence_sha256'])
        self.assertEqual(result['arms'][0]['model_reservations'],1)
        self.assertGreater(result['arms'][1]['model_reservations'],1)
        self.assertEqual(sum(a['model_reservations'] for a in result['arms']),result['logical_call_budget']['used']['model'])
        self.assertTrue(all(a['acceptance']['decision']=='MORE_DILIGENCE' for a in result['arms']))
    def test_no_retrieval_does_not_claim_zero_managed_cli_network_requests(self):
        result=self.run_case()
        self.assertIsNone(result['actual_network_calls'])
        self.assertEqual(result['actual_source_http_requests'],0)
        self.assertEqual(result['managed_network_requests'],'UNKNOWN')
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertIn('source retrieval only',plan['http_budget_scope'])

    def test_backend_failure_is_retained_without_secret(self):
        def failing(budget,root):raise ValueError('SECRET_BACKEND_DETAIL')
        result=self.run_case(backend_factory=failing)
        self.assertEqual(result['status'],'PAIRED_BACKEND_SETUP_FAILED')
        self.assertEqual(len(result['arms']),2)
        self.assertNotIn('SECRET_BACKEND_DETAIL',(self.root/'result.json').read_text())

    def test_source_fail_blocks_backend(self):
        self.meta['digests']['sha256']='0'*64
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(self.factories,[])
    def test_shared_cap_preserves_failed_arm(self):
        result=self.run_case(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_model_calls=1,max_search_calls=0))
        self.assertEqual(len(result['arms']),2)
        self.assertEqual(result['arms'][1]['status'],'STOPPED_NO_RETRY')
        self.assertEqual(result['logical_call_budget']['used']['model'],1)
    def test_existing_pair_cannot_be_replayed(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):self.run_case()
        self.assertEqual(self.factories,[])
    def test_no_execution_approval_refuses(self):
        with self.assertRaises(PermissionError):self.run_case(approved=False)
        self.assertEqual(self.factories,[])

    def test_reverse_order_executes_committee_first_same_evidence(self):
        result=self.run_case(arm_order=('committee','single_analyst'))
        self.assertEqual(result['arm_order'],['committee','single_analyst'])
        self.assertEqual(self.backend.arm_events[0],'committee')
        self.assertEqual(self.backend.arm_events[-1],'single_analyst')
        self.assertEqual(result['arms'][0]['arm'],'committee')
        self.assertEqual(result['arms'][1]['arm'],'single_analyst')
        self.assertEqual(self.backend.baseline_inputs[0]['evidence'],self.backend.committee_inputs[0]['evidence'])
        self.assertEqual(result['arms'][0]['evidence_sha256'],result['arms'][1]['evidence_sha256'])

    def test_invalid_arm_orders_fail_before_dirs_and_backend(self):
        for bad in (('single_analyst','single_analyst'),('single_analyst','committee','extra'),
                    ['single_analyst','committee'],('single_analyst','unknown_arm')):
            with self.assertRaises(ValueError):self.run_case(arm_order=bad)
            self.assertEqual(self.factories,[])
            self.assertFalse(self.root.exists())

    def test_shared_cap_reverse_order_preserves_second_arm_failed(self):
        result=self.run_case(arm_order=('committee','single_analyst'),
            request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_model_calls=1,max_search_calls=0))
        self.assertEqual(len(result['arms']),2)
        self.assertEqual(result['arms'][0]['arm'],'committee')
        self.assertEqual(result['arms'][1]['arm'],'single_analyst')
        self.assertEqual(result['arms'][1]['status'],'STOPPED_NO_RETRY')
        self.assertEqual(result['logical_call_budget']['used']['model'],1)
        self.assertEqual(result['arms'][0]['reason'],result['arms'][1]['reason'])
        self.assertEqual(result['arms'][1]['model_reservations'],0)

    def test_fairness_metadata_and_remaining_reservations_reconcile(self):
        result=self.run_case()
        self.assertEqual(result['fairness'],dict(shared_budget=True,equal_per_arm_allowance=False,
            equal_cost=False,randomized_order=False,
            note='order must be frozen by caller; changed order alone cannot establish superiority'))
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertEqual(plan['fairness'],result['fairness'])
        cap=result['logical_call_budget']['caps']['model']
        for arm in result['arms']:
            self.assertEqual(arm['remaining_model_reservations_before']-arm['model_reservations'],
                arm['remaining_model_reservations_after'])
        self.assertEqual(result['arms'][0]['remaining_model_reservations_before'],cap)
        self.assertEqual(result['arms'][1]['remaining_model_reservations_before'],
            result['arms'][0]['remaining_model_reservations_after'])
        self.assertEqual(result['arms'][1]['remaining_model_reservations_after'],
            cap-result['logical_call_budget']['used']['model'])


class VerifiedEvidencePairTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'pair'
        self.backend=PairBackend();self.factories=[]
    def run_case(self,**updates):
        def factory(budget,root):self.factories.append(budget);return self.backend
        market=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        args=dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_model_calls=24,max_search_calls=0),
            source_items=(market,),output_dir=self.root,backend_factory=factory,approved=True)
        args.update(updates);return execute_verified_evidence_pair(**args)

    def test_multiple_verified_sources_reach_both_arms(self):
        items=(source('market-2024','market','SYNTHETIC_MARKET_CONTEXT'),source('tech-2024','technology','SYNTHETIC_TECH_CONTEXT'))
        result=self.run_case(source_items=items)
        self.assertEqual(len(self.backend.baseline_inputs[0]['evidence']),2)
        self.assertEqual(self.backend.baseline_inputs[0]['evidence'],self.backend.committee_inputs[0]['evidence'])
        self.assertEqual(len(json.loads((self.root/'plan.json').read_text())['source_proofs']),2)
    def test_any_bad_source_rejects_entire_input_not_just_bad_subset(self):
        items=(source('market-2024','market','SYNTHETIC_MARKET_CONTEXT'),source('future','technology','future',available='2025-01-01T00:00:00Z'))
        with self.assertRaises(ValueError):self.run_case(source_items=items)
        self.assertFalse(self.root.exists());self.assertEqual(self.factories,[])
    def test_source_container_bounds_and_types_before_dispatch(self):
        item=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        for bad in ((),[item],(item,)*9,([item[0],item[1]],)):
            with self.assertRaises(ValueError):self.run_case(source_items=bad)
            self.assertFalse(self.root.exists());self.assertEqual(self.factories,[])
    def test_first_stop_during_backend_does_not_become_secondary_arm_error(self):
        from closed_loop.guards import BudgetStopped
        def factory(budget,root):
            class FirstStopBackend(PairBackend):
                def generate(self,*args):
                    budget.stop('FIRST_STOP_CAUSE');raise BudgetStopped('SECONDARY_FAILURE')
            return FirstStopBackend()
        result=self.run_case(backend_factory=factory)
        self.assertEqual(result['stop_reason'],'FIRST_STOP_CAUSE')
        self.assertEqual([a['reason'] for a in result['arms']],['FIRST_STOP_CAUSE','FIRST_STOP_CAUSE'])
        self.assertEqual([a['model_reservations'] for a in result['arms']],[1,0])

    def test_valid_typed_record_reaches_both_arms_with_same_evidence(self):
        result=self.run_case()
        self.assertEqual(len(self.factories),1)
        self.assertEqual(self.backend.baseline_inputs[0]['evidence'],self.backend.committee_inputs[0]['evidence'])
        self.assertEqual(result['arms'][0]['evidence_sha256'],result['arms'][1]['evidence_sha256'])
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertTrue(plan['trusted_verifier_input'])
        self.assertIsNone(result['stop_reason'])
        self.assertEqual(plan['assessment_scope'],'fixed_evidence_analysis_only_not_research')
        self.assertEqual(plan['source_proofs'][0]['source_id'],'market-2024')

    def test_future_mismatched_wrong_company_and_unread_body_all_rejected_before_backend(self):
        candidate,record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT',available='2024-05-01T00:00:00Z')
        with self.assertRaises(ValueError):self.run_case(source_items=((candidate,record),))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())
        candidate,record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        record=replace(record,content_sha256='0'*64)
        with self.assertRaises(ValueError):self.run_case(source_items=((candidate,record),))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())
        candidate,record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        candidate=replace(candidate,company_id='OTHER_COMPANY')
        with self.assertRaises(ValueError):self.run_case(source_items=((candidate,record),))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())
        candidate,record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        record=replace(record,body_read=False)
        with self.assertRaises(ValueError):self.run_case(source_items=((candidate,record),))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())

    def test_fake_dict_records_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case(source_items=(({'source_id':'x'},{'content_sha256':'y'}),))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())

    def test_truthy_nonboolean_body_proof_is_not_a_verified_read(self):
        candidate,record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        for bad in ('true','false',1,None):
            with self.assertRaises(ValueError):
                self.run_case(source_items=((candidate,replace(record,body_read=bad)),))
            self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())

    def test_duplicate_fact_ids_rejected(self):
        market=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        with self.assertRaises(ValueError):self.run_case(source_items=(market,market))
        self.assertEqual(self.factories,[]);self.assertFalse(self.root.exists())

    def test_reversed_order_works_on_new_path(self):
        result=self.run_case(arm_order=('committee','single_analyst'))
        self.assertEqual(result['arm_order'],['committee','single_analyst'])
        self.assertEqual(self.backend.arm_events[0],'committee')
        self.assertEqual(self.backend.arm_events[-1],'single_analyst')

    def test_shared_cap_first_stop_persists_on_new_path(self):
        result=self.run_case(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_model_calls=1,max_search_calls=0))
        self.assertEqual(len(result['arms']),2)
        self.assertEqual(result['arms'][1]['status'],'STOPPED_NO_RETRY')
        self.assertEqual(result['logical_call_budget']['used']['model'],1)


if __name__=='__main__':unittest.main()
