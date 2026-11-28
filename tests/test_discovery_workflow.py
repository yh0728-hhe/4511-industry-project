"""Command assembly and rejection tests; no actual auth, process or network calls."""
import json
from pathlib import Path
import sys,tempfile,unittest
from contextlib import ExitStack,redirect_stdout
from io import StringIO
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop import discovery_workflow as cli
from closed_loop.guards import CallBudget
from closed_loop.contracts import ResearchRequest

def config():
    return dict(company=dict(company_id='SYNTHETIC_COMPANY',name='Synthetic Company',domain='synthetic.example'),
        mandate='Synthetic research mandate.',as_of='2024-04-04T23:59:59Z',model='fixture-model',
        max_model_calls=24,max_search_reservations=12,max_seconds=120,max_research_passes=2,
        max_specialists=1,max_sources=3,check_argument_support=False,verify_publishers=False,
        publisher_max_body_bytes=524288)
class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.cfg=self.root/'config.json';self.out=self.root/'output'
        self.cfg.write_text(json.dumps(config()),encoding='utf-8')
    def args(self,approval=True):
        return ['--config',str(self.cfg),'--output-dir',str(self.out)]+(['--approve-cli'] if approval else [])
    def mocks(self,**changes):
        stack=ExitStack();self.addCleanup(stack.close);m={}
        defaults={'_forbidden_env_present':False,'_resolve_executable':'fake-cli','_verify_subscription_auth':True}
        defaults.update(changes)
        for name,value in defaults.items():m[name]=stack.enter_context(patch.object(cli,name,return_value=value))
        self.output=StringIO();stack.enter_context(redirect_stdout(self.output));return m
    def test_help_dispatches_nothing(self):
        with patch.object(cli,'_verify_subscription_auth') as auth,redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit) as e:cli.main(['--help'])
        self.assertEqual(e.exception.code,0);auth.assert_not_called()
    def test_missing_usage_flag_never_authenticates_or_creates_outputs(self):
        m=self.mocks();self.assertEqual(cli.main(self.args(False)),1)
        m['_verify_subscription_auth'].assert_not_called();self.assertFalse(self.out.exists())
    def test_extra_label_fields_rejected_before_auth(self):
        c=config();c['funding_y']='YES';self.cfg.write_text(json.dumps(c),encoding='utf-8')
        m=self.mocks();self.assertEqual(cli.main(self.args()),1);m['_verify_subscription_auth'].assert_not_called()
    def test_naive_cutoff_and_boolean_number_rejected(self):
        for delta in ({'as_of':'2024-04-04T23:59:59'},{'max_model_calls':True},{'verify_publishers':1}):
            c=config();c.update(delta)
            with self.assertRaises(ValueError):cli._parse_config(c)

    def test_package_optin_defaults_false_and_boolean_subset_options_are_valid(self):
        _,extra=cli._parse_config(config());self.assertIs(extra['verify_packages'],False)
        for options in ({'verify_packages':True},{'preliminary_screen':True},
                {'preliminary_screen':True,'verify_packages':True}):
            c=config();c.update(options);_,extra=cli._parse_config(c)
            for key,value in options.items():self.assertIs(extra[key],value)
        c=config();c['verify_packages']='true'
        with self.assertRaises(ValueError):cli._parse_config(c)

    def test_cli_package_optin_supplies_explicit_registry_client_without_cap_change(self):
        self.mocks();c=config();c['verify_packages']=True
        self.cfg.write_text(json.dumps(c),encoding='utf-8')
        value=dict(status='DISCOVERY_RUNTIME_EXECUTED',decision='MORE_DILIGENCE',stop_reason='NO_NEW_EVIDENCE')
        with patch.object(cli,'execute_discovery_run',return_value=value) as execute:
            self.assertEqual(cli.main(self.args()),0)
        passed=execute.call_args.kwargs
        self.assertIsInstance(passed['http_client'],cli.ArchiveHTTPClient)
        self.assertEqual(type(passed['http_client']).__name__,'IsolatedArchiveHTTPClient')
        self.assertIs(passed['verify_packages'],True)
        self.assertIsInstance(passed['registry_http_client'],cli.IsolatedRegistryHTTPClient)
        self.assertEqual(passed['request'].max_search_calls,c['max_search_reservations'])
        self.assertEqual(passed['request'].max_model_calls,c['max_model_calls'])

    def test_package_capability_forwarded_to_managed_agent_factory(self):
        req,_=cli._parse_config(config());budget=CallBudget(req)
        with tempfile.TemporaryDirectory() as root:
            factory=cli.make_discovery_factory(req,'fixture',verify_packages=True)
            agent=factory(ResearchRequest('product','question',req.company.company_id),budget,Path(root))
            self.assertIs(agent.package_leads,True)
            self.assertEqual(budget.used,{'model':0,'search':0})

    def test_legacy_config_without_preliminary_screen_defaults_false(self):
        request,extra=cli._parse_config(config())
        self.assertFalse(extra['preliminary_screen'])

    def test_explicit_preliminary_screen_true_passed_through(self):
        c=config();c['preliminary_screen']=True
        request,extra=cli._parse_config(c)
        self.assertTrue(extra['preliminary_screen'])

    def test_cli_explicit_screen_true_reaches_runner_without_new_caps(self):
        self.mocks();c=config();c['preliminary_screen']=True
        self.cfg.write_text(json.dumps(c),encoding='utf-8')
        value=dict(status='DISCOVERY_RUNTIME_EXECUTED',decision='MORE_DILIGENCE',stop_reason='NO_NEW_EVIDENCE')
        with patch.object(cli,'execute_discovery_run',return_value=value) as execute:
            self.assertEqual(cli.main(self.args()),0)
        passed=execute.call_args.kwargs
        self.assertIs(passed['preliminary_screen'],True)
        self.assertEqual(passed['request'].max_model_calls,c['max_model_calls'])
        self.assertEqual(passed['request'].max_search_calls,c['max_search_reservations'])

    def test_nonboolean_or_unknown_preliminary_screen_keys_rejected_before_auth(self):
        c=config();c['preliminary_screen']=1
        with self.assertRaises(ValueError):cli._parse_config(c)
        m=self.mocks()
        c=config();c['preliminary_screen']='yes'
        self.cfg.write_text(json.dumps(c),encoding='utf-8')
        self.assertEqual(cli.main(self.args()),1);m['_verify_subscription_auth'].assert_not_called()
        m=self.mocks()
        c=config();c['screening_mode']='baseline_first'
        self.cfg.write_text(json.dumps(c),encoding='utf-8')
        self.assertEqual(cli.main(self.args()),1);m['_verify_subscription_auth'].assert_not_called()
    def test_duplicate_nan_and_oversize_json_rejected_before_auth(self):
        m=self.mocks()
        for text in ('{"company":1,"company":2}','{"number":NaN}',' '*32769):
            self.cfg.write_text(text,encoding='utf-8')
            self.assertEqual(cli.main(self.args()),1)
        m['_verify_subscription_auth'].assert_not_called()
    def test_existing_output_rejected_before_auth(self):
        self.out.mkdir();m=self.mocks();self.assertEqual(cli.main(self.args()),1)
        m['_verify_subscription_auth'].assert_not_called()
    def test_forbidden_route_or_missing_auth_never_executes_research(self):
        for changes in ({'_forbidden_env_present':True},{'_verify_subscription_auth':False}):
            self.mocks(**changes)
            with patch.object(cli,'execute_discovery_run') as run:
                self.assertEqual(cli.main(self.args()),1);run.assert_not_called()
    def test_factory_assembly_binds_same_request_budget_and_unique_source_dirs(self):
        m=self.mocks();seen={}
        def execute(**kwargs):
            req=kwargs['request'];b=CallBudget(req);self.out.mkdir()
            seen.update(kwargs)
            backend=kwargs['backend_factory'](b,self.out)
            self.assertIs(backend.call_budget,b)
            self.assertEqual(backend.per_call_timeout_seconds,60)
            t=ResearchRequest('research','Synthetic question',req.company.company_id)
            a=kwargs['discovery_factory'](t,b,self.out);z=kwargs['discovery_factory'](t,b,self.out)
            self.assertIs(a.request,req);self.assertIs(a.call_budget,b)
            self.assertNotEqual(a.output_dir,z.output_dir)
            return dict(status='DISCOVERY_RUNTIME_EXECUTED',decision='MORE_DILIGENCE',stop_reason='NO_NEW_EVIDENCE')
        with patch.object(cli,'execute_discovery_run',side_effect=execute):self.assertEqual(cli.main(self.args()),0)
        self.assertEqual(seen['max_specialists'],1);self.assertEqual(seen['publisher_max_body_bytes'],524288)
        self.assertNotIn('source_urls',seen)
        self.assertEqual(json.loads((self.out/'config_snapshot.json').read_text(encoding='utf-8')),config())
    def test_stopped_result_is_nonzero(self):
        self.mocks()
        with patch.object(cli,'execute_discovery_run',return_value={'status':'DISCOVERY_RUNTIME_STOPPED','decision':'MORE_DILIGENCE'}):
            self.assertEqual(cli.main(self.args()),2)
    def test_cli_executes_actual_injected_runtime_without_external_calls(self):
        from closed_loop.native_fixture import NativeFixtureBackend
        from closed_loop.model_lead import LeadPlanOutput
        from test_discovered_research import DiscoveryHTTP,FakeDiscoveryAgent,discovery_result,GOOD_URL
        class OneTask(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                value=super().generate(schema,messages,temperature)
                return LeadPlanOutput(value.tasks[:1]) if schema is LeadPlanOutput else value
        def sources(req,exe,*,verify_packages=False):
            self.assertIs(verify_packages,False)
            return lambda t,b,p:FakeDiscoveryAgent(req,b,discovery_result([GOOD_URL]))
        self.mocks()
        with patch.object(cli,'make_backend_factory',return_value=lambda b,p:OneTask()),patch.object(cli,'make_discovery_factory',side_effect=sources),patch.object(cli,'ArchiveHTTPClient',return_value=DiscoveryHTTP()):
            self.assertEqual(cli.main(self.args()),0)
        r=json.loads((self.out/'result.json').read_text(encoding='utf-8'))
        self.assertEqual(r['decision'],'MORE_DILIGENCE');self.assertEqual(len(r['admitted_fact_ids']),1)
    def test_recording_executor_saves_intent_and_raw_bytes(self):
        recorder=cli.RecordingExecutor(self.root/'wire')
        class Inner:
            def run(self,argv,stdin,timeout):
                meta=json.loads((recorder.capture_dir/'call_001.json').read_text(encoding='utf-8'))
                self.assert_intent=meta['status']=='DISPATCHING'
                return 0,b'output',b'error'
        inner=Inner();recorder._inner=inner;recorder.run(['fake'],b'input',3)
        self.assertTrue(inner.assert_intent)
        self.assertEqual((recorder.capture_dir/'call_001.stdout').read_bytes(),b'output')
    def test_recording_failure_type_only_no_secret_message(self):
        recorder=cli.RecordingExecutor(self.root/'wire')
        class Inner:
            def run(self,*args):raise RuntimeError('SECRET_PROVIDER_DETAIL')
        recorder._inner=Inner()
        with self.assertRaises(RuntimeError):recorder.run(['fake'],b'input',3)
        text=(recorder.capture_dir/'call_001.json').read_text(encoding='utf-8')
        self.assertNotIn('SECRET_PROVIDER_DETAIL',text);self.assertEqual(json.loads(text)['error_type'],'RuntimeError')
    def test_partial_capture_write_failure_preserves_timeout(self):
        import subprocess
        recorder=cli.RecordingExecutor(self.root/'wire')
        timeout=subprocess.TimeoutExpired('fixture',3,output=b'partial')
        class Inner:
            def run(self,*args):raise timeout
        recorder._inner=Inner();original=Path.write_bytes
        def write(path,data):
            if path.suffix=='.stdout':raise OSError('PRIVATE_DISK_FAILURE')
            return original(path,data)
        with patch.object(Path,'write_bytes',write):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                recorder.run(['fake'],b'input',3)
        self.assertIs(caught.exception,timeout)
        text=(recorder.capture_dir/'call_001.json').read_text(encoding='utf-8')
        self.assertNotIn('PRIVATE_DISK_FAILURE',text)
        self.assertEqual(json.loads(text)['capture_error_type'],'OSError')
        self.assertFalse(json.loads(text)['partial'])

    def test_recording_timeout_saves_private_partial_bytes_without_secret_in_metadata(self):
        import subprocess
        recorder=cli.RecordingExecutor(self.root/'wire')
        class Inner:
            def run(self,*args):
                raise subprocess.TimeoutExpired(cmd='claude',timeout=3,
                    output=b'SECRET_PARTIAL_OUT',stderr=b'SECRET_PARTIAL_ERR')
        recorder._inner=Inner()
        with self.assertRaises(subprocess.TimeoutExpired):
            recorder.run(['fake'],b'input',3)
        meta_text=(recorder.capture_dir/'call_001.json').read_text(encoding='utf-8')
        self.assertNotIn('SECRET_PARTIAL',meta_text)
        meta=json.loads(meta_text)
        self.assertEqual(meta['error_type'],'TimeoutExpired')
        self.assertTrue(meta['partial'])
        self.assertEqual((recorder.capture_dir/'call_001.stdout').read_bytes(),b'SECRET_PARTIAL_OUT')
        self.assertEqual((recorder.capture_dir/'call_001.stderr').read_bytes(),b'SECRET_PARTIAL_ERR')
if __name__=='__main__':unittest.main()
