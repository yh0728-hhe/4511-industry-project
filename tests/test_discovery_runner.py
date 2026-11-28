"""Injected offline composition tests; no real CLI, network, company data or quality claims."""
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.discovery_runner import execute_discovery_run
from closed_loop.guards import BudgetStopped
from closed_loop.single_analyst import SingleAnalystAssessment
from test_discovered_research import DiscoveryHTTP, FakeDiscoveryAgent, discovery_result, GOOD_URL

class DiscoveryRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'run';self.http=DiscoveryHTTP();self.seen=[]
        self.req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),
                         max_model_calls=24,max_search_calls=12,max_research_passes=2)
    def backend(self,budget,root):
        self.seen.append(('backend',budget));return NativeFixtureBackend()
    def discovery(self,task,budget,root):
        self.seen.append(('discovery',budget));return FakeDiscoveryAgent(self.req,budget,discovery_result([GOOD_URL]))
    def run_case(self,**changes):
        args=dict(request=self.req,output_dir=self.root,backend_factory=self.backend,
                  discovery_factory=self.discovery,http_client=self.http,approved=True,check_argument_support=False)
        args.update(changes);return execute_discovery_run(**args)
    def test_real_runtime_archive_composition_and_saved_body(self):
        r=self.run_case()
        self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_EXECUTED')
        self.assertEqual(len(r['admitted_fact_ids']),1)
        self.assertEqual(r['direct_archive_http_attempts'],2)
        self.assertTrue(all(b is self.seen[0][1] for _,b in self.seen))
        self.assertTrue((self.root/'archive_http_002.body').is_file())
        self.assertFalse(r['Y_changed']);self.assertFalse(r['training_run'])
        self.assertIsNone(r['managed_discovery_process_attempts']) # injected agent does not certify a count
    def test_archive_timeout_is_terminal_and_attempt_survives_without_body(self):
        calls=[]
        class HangingClient:
            def get(inner,*args,**kwargs):
                calls.append(1)
                raise BudgetStopped('ARCHIVE_REQUEST_TIMEOUT')
        result=self.run_case(http_client=HangingClient())
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'ARCHIVE_REQUEST_TIMEOUT')
        self.assertEqual(len(calls),1)
        self.assertEqual(result['direct_archive_http_attempts'],1)
        attempt=json.loads((self.root/'archive_http_001.attempt.json').read_text())
        self.assertEqual(attempt['status'],'FAILED')
        self.assertEqual(attempt['error_type'],'BudgetStopped')
        self.assertFalse((self.root/'archive_http_001.body').exists())
        self.assertEqual(result['admitted_fact_ids'],[])

    def test_no_leads_unknown_never_negative(self):
        r=self.run_case(discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([])))
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertEqual(r['admitted_fact_ids'],[])
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_EXECUTED')
        self.assertEqual(r['stop_reason'],'NO_ADMITTED_FACTS')
        self.assertEqual(self.http.calls,[])
    def test_approval_before_side_effects(self):
        with self.assertRaises(PermissionError):self.run_case(approved=False)
        self.assertFalse(self.root.exists());self.assertFalse(self.seen);self.assertFalse(self.http.calls)
    def test_invalid_cutoff_before_side_effects(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):self.run_case(request=replace(self.req,as_of=datetime.now(timezone.utc)))
        self.assertFalse(self.root.exists());self.assertFalse(self.seen)
    def test_exclusive_root(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):self.run_case()
        self.assertFalse(self.seen)
    def test_archive_restriction_not_success(self):
        self.http=DiscoveryHTTP(restrict_path='/pricing')
        r=self.run_case()
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_STOPPED')
        self.assertEqual(r['stop_reason'],'ARCHIVE_RATE_LIMITED')
        self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertEqual(len(self.http.calls),2)
    def test_factory_error_sanitized_and_receipts_saved(self):
        def bad(*args):raise RuntimeError('private auth diagnostic')
        r=self.run_case(backend_factory=bad)
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_FAILED')
        self.assertNotIn('private auth diagnostic',(self.root/'result.json').read_text())
        for name in ('plan.json','provider_trace.json','archive_receipts.json','archive_attempts.json'):
            self.assertTrue((self.root/name).exists())
    def test_factory_stop_preserves_first_cause(self):
        def bad(budget,root):
            budget.stop('QUOTA_STOP');raise BudgetStopped('QUOTA_STOP')
        r=self.run_case(backend_factory=bad)
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_STOPPED');self.assertEqual(r['stop_reason'],'QUOTA_STOP')
    def test_pending_final_review_holds_substantive_proposal(self):
        proposal=dict(decision='INVEST',rationale='Supported fixture claim.',admitted_fact_ids=['fixture-fact'],
                      essential_gaps=[],thesis=None,stop_reason='EVIDENCE_REVIEW_COMPLETE')
        with patch('closed_loop.discovery_runner.ClosedLoopRuntime') as runtime:
            runtime.return_value.run.return_value=proposal
            r=self.run_case()
        self.assertEqual(r['proposed_decision'],'INVEST');self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertIsNone(r['thesis']);self.assertIn('final_analysis_review',r['essential_gaps'])
    def test_partial_committee_trace_saved_on_terminal_evaluation_stop(self):
        class StoppedCommittee:
            def __init__(self,*args,**kwargs):
                self.call_budget=args[1]
                self.last_trace=[{'event':'NATIVE_COMMITTEE_STAGE','stage':'final_aggregation'}]
                self.last_calls=[{'schema':'fixture'}]
            def evaluate(self,view):raise BudgetStopped('CHECKER_STOP')
        with patch('closed_loop.discovery_runner.NativeDialecticCommittee',StoppedCommittee):
            r=self.run_case()
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_STOPPED')
        self.assertEqual(json.loads((self.root/'committee_trace.json').read_text())[0]['stage'],'final_aggregation')
        self.assertEqual(json.loads((self.root/'model_calls.json').read_text())[0]['schema'],'fixture')

    def test_optional_publisher_path_saved_with_distinct_scope_and_shared_budget(self):
        from dataclasses import replace
        from test_archived_publisher import COMPANY,FakeClient,PUBLISHER_URL
        self.req=replace(self.req,company=COMPANY);self.http=FakeClient()
        result=self.run_case(verify_publishers=True,
            discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([PUBLISHER_URL])))
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(len(result['admitted_fact_ids']),1)
        self.assertEqual(result['direct_archive_http_attempts'],2)
        receipts=json.loads((self.root/'publisher_receipts.json').read_text())
        self.assertEqual(receipts[0]['editorial_independence'],'UNKNOWN')
        self.assertEqual(json.loads((self.root/'archive_receipts.json').read_text()),[])
    def test_publisher_restriction_is_terminal_not_an_official_source_fallback(self):
        from dataclasses import replace
        from test_archived_publisher import COMPANY,FakeClient,PUBLISHER_URL
        self.req=replace(self.req,company=COMPANY);self.http=FakeClient(replay_status=429)
        result=self.run_case(verify_publishers=True,
            discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([PUBLISHER_URL])))
        self.assertEqual(result['status'],'DISCOVERY_RUNTIME_STOPPED')
        self.assertEqual(result['stop_reason'],'ARCHIVE_RATE_LIMITED')
        self.assertEqual(result['direct_archive_http_attempts'],2)
        self.assertEqual(result['admitted_fact_ids'],[])

    def test_bounded_publisher_body_limit_reaches_transport_and_plan(self):
        from dataclasses import replace
        from test_archived_publisher import COMPANY,FakeClient,PUBLISHER_URL
        self.req=replace(self.req,company=COMPANY)
        class Sized(FakeClient):
            def __init__(self):super().__init__();self.limits=[]
            def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
                self.limits.append(max_bytes)
                return super().get(url,timeout,max_bytes,check_deadline)
        self.http=Sized()
        self.run_case(verify_publishers=True,publisher_max_body_bytes=1048576,
            discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([PUBLISHER_URL])))
        self.assertEqual(set(self.http.limits),{1048576})
        self.assertEqual(json.loads((self.root/'plan.json').read_text())['publisher_max_body_bytes'],1048576)
    def test_single_specialist_mode_still_researches_and_retains_unknown(self):
        from closed_loop.model_lead import LeadPlanOutput
        class OneTask(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                value=super().generate(schema,messages,temperature)
                return LeadPlanOutput(value.tasks[:1]) if schema is LeadPlanOutput else value
        result=self.run_case(max_specialists=1,backend_factory=lambda b,p:OneTask())
        self.assertEqual(result['status'],'DISCOVERY_RUNTIME_EXECUTED')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(json.loads((self.root/'plan.json').read_text())['max_specialists'],1)
    def test_out_of_range_resource_options_rejected_before_outputs(self):
        for options in ({'max_specialists':0},{'max_specialists':True},{'publisher_max_body_bytes':1048577}):
            with self.assertRaises(ValueError):self.run_case(**options)
        self.assertFalse(self.root.exists());self.assertEqual(self.seen,[])

    def test_plan_hash_and_resource_units_explicit(self):
        self.run_case()
        p=json.loads((self.root/'plan.json').read_text())
        from closed_loop.contracts import digest
        fingerprint=p.pop('fingerprint');self.assertEqual(fingerprint,digest(json.dumps(p,sort_keys=True)))
        self.assertEqual(len(p['component_sha256']),30);self.assertIn('archive_process.py',p['component_sha256']);self.assertIn('archive_worker.py',p['component_sha256']);self.assertIn('registry_process.py',p['component_sha256']);self.assertIn('registry_worker.py',p['component_sha256']);self.assertIn('npm_names.py',p['component_sha256']);self.assertIn('ragas_faithfulness.py',p['component_sha256']);self.assertIn('UNKNOWN',p['resource_units'])
        self.assertIn('cli_limits.py',p['component_sha256'])
        self.assertIn('progressive_committee.py',p['component_sha256']);self.assertIn('single_analyst.py',p['component_sha256'])
        self.assertFalse(p['Y_read'])
        self.assertFalse(p['preliminary_screen_enabled']);self.assertEqual(p['analysis_strategy'],'full_committee')

    def test_preliminary_screen_rejected_when_not_boolean(self):
        with self.assertRaises(ValueError):self.run_case(preliminary_screen=1)
        self.assertFalse(self.root.exists());self.assertFalse(self.seen)

    def test_preliminary_screen_flag_recorded_in_plan_before_execution(self):
        def unavailable(*args):raise RuntimeError('Fixture backend unavailable')
        self.run_case(preliminary_screen=True,backend_factory=unavailable)
        p=json.loads((self.root/'plan.json').read_text())
        self.assertTrue(p['preliminary_screen_enabled']);self.assertEqual(p['analysis_strategy'],'baseline_first')

    def test_future_source_never_reaches_preliminary_screen(self):
        class WatchingBackend(NativeFixtureBackend):
            def __init__(self):super().__init__();self.schemas=[]
            def generate(self,schema,messages,temperature):
                self.schemas.append(schema)
                if schema is SingleAnalystAssessment:raise AssertionError('Future evidence reached screen')
                return super().generate(schema,messages,temperature)
        backend=WatchingBackend()
        result=self.run_case(preliminary_screen=True,http_client=DiscoveryHTTP(future_path='/pricing'),backend_factory=lambda b,p:backend)
        self.assertEqual(result['admitted_fact_ids'],[])
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertNotIn(SingleAnalystAssessment,backend.schemas)
    def test_escalated_screen_keeps_enabled_argument_support_checker(self):
        from closed_loop.ragas_faithfulness import FaithfulnessStatements
        from closed_loop.thesis_synthesis import ThesisSynthesis
        class EscalatingBackend(NativeFixtureBackend):
            def __init__(self):super().__init__();self.schemas=[]
            def generate(self,schema,messages,temperature):
                self.schemas.append(schema)
                if schema is SingleAnalystAssessment:
                    context=json.loads(messages[0].content.split('\n',1)[1])
                    ids=[row['fact_id'] for row in context['evidence']]
                    return SingleAnalystAssessment('INVEST','Fixture screen.',[],ThesisSynthesis('fixture',[],[],ids,[],[],[]))
                if schema is FaithfulnessStatements:raise BudgetStopped('SUPPORT_CHECK_REACHED')
                return super().generate(schema,messages,temperature)
        backend=EscalatingBackend()
        result=self.run_case(preliminary_screen=True,check_argument_support=True,backend_factory=lambda b,p:backend)
        self.assertIn(FaithfulnessStatements,backend.schemas)
        self.assertEqual(result['stop_reason'],'SUPPORT_CHECK_REACHED')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')

    def test_optional_registry_source_reaches_runtime_and_separate_counters(self):
        from test_npm_source import tarball
        from test_package_registry import FakeHTTP
        from test_discovered_package import npm_payload, NPM_URL
        raw,meta=tarball();registry=FakeHTTP([npm_payload(meta),raw])
        r=self.run_case(verify_packages=True,registry_http_client=registry,
            discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([NPM_URL])))
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_EXECUTED')
        self.assertEqual(len(r['admitted_fact_ids']),1)
        self.assertEqual(r['direct_registry_http_attempts'],2)
        self.assertEqual(r['direct_archive_http_attempts'],0)
        self.assertEqual(r['direct_source_http_attempts'],2)
        self.assertEqual(r['logical_call_budget']['used']['search'],2)
        self.assertEqual(self.http.calls,[])
        self.assertTrue((self.root/'registry_http_002.body').exists())
        self.assertTrue(json.loads((self.root/'registry_receipts.json').read_text()))
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertTrue(plan['package_verification_enabled'])
        self.assertIn('package_registry.py',plan['component_sha256'])

    def test_registry_rate_limit_stops_without_archive_fallback(self):
        from test_package_registry import FakeHTTP
        from test_discovered_package import NPM_URL
        registry=FakeHTTP([(429,'https://registry.npmjs.org/sample-sdk',{},b'')])
        r=self.run_case(verify_packages=True,registry_http_client=registry,
            discovery_factory=lambda t,b,p:FakeDiscoveryAgent(self.req,b,discovery_result([NPM_URL])))
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_STOPPED')
        self.assertEqual(r['stop_reason'],'REGISTRY_RATE_LIMITED')
        self.assertEqual(r['direct_registry_http_attempts'],1)
        self.assertEqual(r['direct_archive_http_attempts'],0)
        self.assertEqual(r['admitted_fact_ids'],[])
        self.assertEqual(self.http.calls,[])

    def test_registry_flag_and_client_must_be_explicit_before_output(self):
        from test_package_registry import FakeHTTP
        for changes in [dict(verify_packages=1),dict(verify_packages=True),
                dict(registry_http_client=FakeHTTP([]))]:
            with self.assertRaises(ValueError):self.run_case(**changes)
        self.assertFalse(self.root.exists());self.assertFalse(self.seen)

    def test_incomplete_screen_is_saved_as_stopped_with_sources_and_raw_assessment(self):
        class EmptyGapScreen(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                if schema is SingleAnalystAssessment:
                    return SingleAnalystAssessment('MORE_DILIGENCE','No specified gap.',[],None)
                return super().generate(schema,messages,temperature)
        r=self.run_case(preliminary_screen=True,backend_factory=lambda b,p:EmptyGapScreen())
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_STOPPED')
        self.assertEqual(r['stop_reason'],'PROGRESSIVE_SCREEN_MISSING_GAPS')
        self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertEqual(len(r['admitted_fact_ids']),1)
        trace=json.loads((self.root/'committee_trace.json').read_text())
        assessment=next(row for row in trace if row['event']=='PROGRESSIVE_PRELIMINARY_ASSESSMENT')
        self.assertEqual(assessment['untrusted_assessment']['essential_gaps'],[])
        self.assertTrue(json.loads((self.root/'model_calls.json').read_text()))
        self.assertFalse(any(row.get('event')=='NATIVE_COMMITTEE_STAGE' for row in trace))

    def test_preliminary_screen_optin_skips_native_stages_on_more_diligence(self):
        class ScreenBackend(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                if schema is SingleAnalystAssessment:
                    return SingleAnalystAssessment('MORE_DILIGENCE','Preliminary gap found.',
                        ['needs_more_research'],None)
                return super().generate(schema,messages,temperature)
        r=self.run_case(preliminary_screen=True,backend_factory=lambda b,p:ScreenBackend())
        self.assertEqual(r['status'],'DISCOVERY_RUNTIME_EXECUTED')
        self.assertEqual(r['decision'],'MORE_DILIGENCE')
        self.assertEqual(len(r['admitted_fact_ids']),1)
        trace=json.loads((self.root/'committee_trace.json').read_text())
        events=[row['event'] for row in trace]
        self.assertIn('PROGRESSIVE_SCREEN_MORE_DILIGENCE',events)
        self.assertNotIn('NATIVE_COMMITTEE_STAGE',events)
if __name__=='__main__':unittest.main()
