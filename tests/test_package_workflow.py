import copy,json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from closed_loop.package_workflow import execute_workflow,main,_load_strict_config,_verify_subscription_auth
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.ragas_faithfulness import FaithfulnessStatements,FaithfulnessVerdicts,StatementFaithfulnessVerdict
from test_npm_source import tarball
from test_package_registry import FakeHTTP

class Backend(NativeFixtureBackend):
    def generate(self,schema,messages,temperature):
        if schema is FaithfulnessStatements:return FaithfulnessStatements(['Fixture claim.'])
        if schema is FaithfulnessVerdicts:return FaithfulnessVerdicts([StatementFaithfulnessVerdict('Fixture claim.','Fixture unsupported.',0)])
        return super().generate(schema,messages,temperature)

class PackageWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.out=self.root/'run'
        self.config=dict(company=dict(company_id='SYNTHETIC_COMPANY',name='Synthetic Company',domain='synthetic.example'),mandate='Fixture only',as_of='2024-04-04T23:59:59+00:00',package_name='sample-sdk',artifact_format='npm',model='NO_MODEL_FIXTURE',max_model_calls=24,max_seconds=120,check_argument_support=True)
        self.raw,self.meta=tarball();self.payload=dict(name='sample-sdk',time={'1.0.0':self.meta['published']},versions={'1.0.0':dict(name='sample-sdk',version='1.0.0',dist=self.meta['dist'])})
        self.client=FakeHTTP([json.dumps(self.payload).encode(),self.raw]);self.factories=[]
    def factory(self,budget,path):
        self.assertEqual(budget.used['search'],2);self.factories.append((budget,path));return Backend()
    def run_case(self,**kw):
        args=dict(config=self.config,output_dir=self.out,http_client=self.client,backend_factory=self.factory,approved=True);args.update(kw);return execute_workflow(**args)
    def test_source_verifiers_participate_in_package_prompt_fingerprint(self):
        from closed_loop.package_workflow import _parse_config
        before=_parse_config(self.config)[0].prompt_version
        read=Path.read_bytes
        for filename in ['package_registry.py','package_source.py','npm_source.py','npm_names.py','registry_process.py','registry_worker.py']:
            def changed(path):
                value=read(path)
                return value+b'\n# fixture changed dependency' if path.name==filename else value
            with self.subTest(filename=filename),patch.object(Path,'read_bytes',changed):
                self.assertNotEqual(_parse_config(self.config)[0].prompt_version,before)

    def test_explicit_scoped_package_workflow_uses_same_source_first_gate(self):
        from test_scoped_npm_source import scoped_tarball,npm_payload,SCOPE_NAME
        self.raw,self.meta=scoped_tarball()
        self.config['package_name']=SCOPE_NAME
        self.client=FakeHTTP([npm_payload(self.meta),self.raw])
        out=self.run_case()
        self.assertEqual(out['status'],'PACKAGE_WORKFLOW_COMPLETED')
        self.assertEqual(self.client.calls[0],'https://registry.npmjs.org/'+SCOPE_NAME)
        self.assertEqual(len(self.client.calls),2)
        self.assertFalse(out['Y_changed'])

    def test_actual_composition_reuses_source_first_budget_and_support_checker(self):
        out=self.run_case();self.assertEqual(out['status'],'PACKAGE_WORKFLOW_COMPLETED')
        self.assertEqual(len(self.client.calls),2);self.assertEqual(len(self.factories),1)
        self.assertEqual((self.out/'source_artifact.tgz').read_bytes(),self.raw)
        self.assertEqual(json.loads((self.out/'source_metadata.json').read_text()),self.meta)
        self.assertEqual(out['logical_call_budget']['used']['search'],2)
        result=json.loads((self.out/'analysis/result.json').read_text());self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertTrue(result['argument_support_check_enabled']);self.assertTrue(any(x['event']=='EVIDENCE_SUPPORT_REVIEW' for x in result['trace']))
        self.assertFalse(out['Y_changed']);self.assertFalse(out['training_run'])
        self.assertEqual(out['analysis_decision'],'MORE_DILIGENCE')
        self.assertEqual(out['analysis_stop_reason'],result['stop_reason'])
    def test_404_is_unknown_not_negative_and_does_not_construct_backend(self):
        client=FakeHTTP([(404,'https://registry.npmjs.org/sample-sdk',{},b'')]);out=self.run_case(http_client=client)
        self.assertEqual(out['status'],'SOURCE_UNKNOWN');self.assertFalse(self.factories);self.assertNotIn('decision',out)
        self.assertEqual(len(client.calls),1)
    def test_403_stops_after_one_http_without_backend(self):
        client=FakeHTTP([(403,'https://registry.npmjs.org/sample-sdk',{},b'')]);out=self.run_case(http_client=client)
        self.assertEqual(out['status'],'WORKFLOW_STOPPED');self.assertEqual(out['stop_reason'],'REGISTRY_ACCESS_RESTRICTED')
        self.assertFalse(self.factories);self.assertEqual(len(client.calls),1)
    def test_corrupt_artifact_fails_before_model_factory(self):
        client=FakeHTTP([json.dumps(self.payload).encode(),b'corrupt']);out=self.run_case(http_client=client)
        self.assertEqual(out['status'],'WORKFLOW_STOPPED');self.assertFalse(self.factories)
        self.assertEqual(out['stop_reason'],'REGISTRY_ARTIFACT_INVALID')
    def test_bad_config_or_extra_label_never_creates_output_or_calls(self):
        cases=[dict(Y=1),dict(max_model_calls=25),dict(max_seconds=481),dict(check_argument_support=1),dict(as_of='2024-04-04'),dict(as_of='2024-04-05T00:00:00+00:00'),dict(artifact_format='zip')]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.run_case(config=dict(self.config,**changes))
            self.assertFalse(self.out.exists());self.assertFalse(self.client.calls)
    def test_output_collision_no_requests(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):self.run_case()
        self.assertFalse(self.client.calls);self.assertFalse(self.factories)
    def test_approval_missing_no_actions(self):
        with self.assertRaises(PermissionError):self.run_case(approved=False)
        self.assertFalse(self.out.exists());self.assertFalse(self.client.calls)
    def test_child_failure_not_reported_as_workflow_completed(self):
        with patch('closed_loop.package_workflow.execute_package_run',return_value={'status':'PACKAGE_RUN_FAILED'}):out=self.run_case()
        self.assertEqual(out['status'],'WORKFLOW_FAILED');self.assertEqual(out['analysis_status'],'PACKAGE_RUN_FAILED')
    def test_strict_config_rejects_duplicates_nan_and_large_input(self):
        p=self.root/'config.json'
        for content in ('{"model":1,"model":2}','{"x":NaN}','x'*32001):
            p.write_text(content)
            with self.assertRaises(ValueError):_load_strict_config(p)
    def test_missing_cli_approval_does_not_touch_auth_or_network(self):
        with patch('closed_loop.package_workflow.subprocess.run') as auth,patch('closed_loop.package_workflow.RegistryHTTPClient') as http:
            self.assertNotEqual(main(['--config','missing','--output-dir',str(self.out)]),0)
        auth.assert_not_called();http.assert_not_called();self.assertFalse(self.out.exists())
    def test_invalid_cli_config_checked_before_auth(self):
        p=self.root/'bad.json';p.write_text('{}')
        with patch('closed_loop.package_workflow.subprocess.run') as auth,patch('closed_loop.package_workflow.RegistryHTTPClient') as http:
            self.assertNotEqual(main(['--config',str(p),'--output-dir',str(self.out),'--approve-cli']),0)
        auth.assert_not_called();http.assert_not_called()
    def test_auth_command_uses_verified_syntax_and_nonzero_exit_is_not_success(self):
        good=SimpleNamespace(returncode=0,stdout=json.dumps(dict(loggedIn=True,authMethod='claude.ai')).encode())
        with patch('closed_loop.package_workflow.subprocess.run',return_value=good) as run:
            self.assertTrue(_verify_subscription_auth('fixture-exe'))
        self.assertEqual(run.call_args.args[0],['fixture-exe','auth','status'])
        with patch('closed_loop.package_workflow.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=good.stdout)):
            self.assertFalse(_verify_subscription_auth('fixture-exe'))
    def test_cli_failure_receipt_has_nonzero_exit(self):
        p=self.root/'config.json';p.write_text(json.dumps(self.config))
        with patch.dict('os.environ',{},clear=True),patch('closed_loop.package_workflow._resolve_executable',return_value='fake'),patch('closed_loop.package_workflow._verify_subscription_auth',return_value=True),patch('closed_loop.package_workflow.RegistryHTTPClient'),patch('closed_loop.package_workflow.execute_workflow',return_value={'status':'WORKFLOW_FAILED'}):
            self.assertNotEqual(main(['--config',str(p),'--output-dir',str(self.out),'--approve-cli']),0)


    def test_child_invalid_argument_stop_is_not_workflow_success(self):
        child=dict(status='PACKAGE_SOURCE_RUNTIME_EXECUTED',stop_reason='PLACEHOLDER_ARGUMENT',decision='MORE_DILIGENCE')
        with patch('closed_loop.package_workflow.execute_package_run',return_value=child):out=self.run_case()
        self.assertEqual(out['status'],'WORKFLOW_STOPPED')
        self.assertEqual(out['stop_reason'],'PLACEHOLDER_ARGUMENT')

if __name__=='__main__':unittest.main()
