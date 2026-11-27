import io
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from closed_loop.archive_transport import HTTPResponse
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,BudgetStopped
from closed_loop.package_registry import PackageRegistryCollector,RegistryHTTPClient,registry_url_allowed
from closed_loop.package_runner import execute_package_run
from closed_loop.native_fixture import NativeFixtureBackend
from test_npm_source import tarball


class FakeHTTP:
    def __init__(self,responses,callback=None):self.responses=list(responses);self.calls=[];self.callback=callback
    def get(self,url,timeout,max_bytes,check_deadline):
        check_deadline();self.calls.append(url)
        if self.callback:self.callback(len(self.calls))
        value=self.responses.pop(0)
        if isinstance(value,Exception):raise value
        return HTTPResponse(*value) if isinstance(value,tuple) else HTTPResponse(200,url,{},value)


class RegistryCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),max_search_calls=2,max_model_calls=24,max_research_passes=2)
        self.budget=CallBudget(self.req);self.raw,self.meta=tarball()
        self.payload={'name':'sample-sdk','time':{'1.0.0':self.meta['published']},'versions':{'1.0.0':{'name':'sample-sdk','version':'1.0.0','dist':self.meta['dist']}}}
    def collector(self,client):
        obj=PackageRegistryCollector(self.req,self.budget,client,self.root/'http.jsonl')
        self.addCleanup(obj.close);return obj
    def body(self):return json.dumps(self.payload).encode()

    def test_two_gets_verify_then_share_budget_with_runtime(self):
        client=FakeHTTP([self.body(),self.raw]);collector=self.collector(client)
        collected=collector.collect('sample-sdk','npm')
        self.assertEqual(self.budget.used['search'],2)
        self.assertEqual(collected['artifact_bytes'],self.raw)
        seen=[]
        def factory(budget,root):seen.append(budget);return NativeFixtureBackend()
        result=execute_package_run(request=self.req,call_budget=self.budget,output_dir=self.root/'run',backend_factory=factory,approved=True,**collected)
        self.assertIs(seen[0],self.budget)
        self.assertEqual(result['registry_transport_attempts'],2)
        self.assertEqual(result['logical_call_budget']['used']['search'],2)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')

    def test_expired_budget_no_dispatch(self):
        self.budget.stop('STOP_OR_DEADLINE');client=FakeHTTP([])
        with self.assertRaises(BudgetStopped):self.collector(client).collect('sample-sdk','npm')
        self.assertEqual(client.calls,[])

    def test_restrictions_stop_after_one_attempt(self):
        for status,reason in [(403,'REGISTRY_ACCESS_RESTRICTED'),(429,'REGISTRY_RATE_LIMITED')]:
            with self.subTest(status=status):
                self.budget=CallBudget(self.req)
                path=self.root/'http.jsonl'
                if path.exists():path.unlink()
                client=FakeHTTP([(status,'https://registry.npmjs.org/sample-sdk',{},b'')])
                with self.assertRaisesRegex(BudgetStopped,reason):self.collector(client).collect('sample-sdk','npm')
                self.assertEqual(len(client.calls),1);self.assertTrue(self.budget.stopped)

    def test_404_is_unknown_not_second_request(self):
        client=FakeHTTP([(404,'https://registry.npmjs.org/sample-sdk',{},b'')])
        self.assertIsNone(self.collector(client).collect('sample-sdk','npm'))
        self.assertEqual(len(client.calls),1)

    def test_future_version_not_downloaded(self):
        self.payload['time']['1.0.0']='2025-01-01T00:00:00Z'
        client=FakeHTTP([self.body()])
        self.assertIsNone(self.collector(client).collect('sample-sdk','npm'))
        self.assertEqual(len(client.calls),1)

    def test_hostile_artifact_url_no_download_or_older_fallback(self):
        self.payload['versions']['0.1.0']=dict(self.payload['versions']['1.0.0'],version='0.1.0')
        self.payload['time']['0.1.0']='2024-01-01T00:00:00Z'
        self.payload['versions']['1.0.0']['dist']=dict(self.meta['dist'],tarball='https://evil.test/x')
        client=FakeHTTP([self.body()])
        with self.assertRaises(BudgetStopped):self.collector(client).collect('sample-sdk','npm')
        self.assertEqual(len(client.calls),1)

    def test_isolated_request_timeout_retains_first_cause_without_retry(self):
        from closed_loop.package_registry import RegistryTransportTimeout
        client=FakeHTTP([RegistryTransportTimeout('REGISTRY_REQUEST_TIMEOUT')])
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_REQUEST_TIMEOUT'):
            self.collector(client).collect('sample-sdk','npm')
        self.assertEqual(len(client.calls),1)
        self.assertEqual(self.budget.stop_reason,'REGISTRY_REQUEST_TIMEOUT')
        self.assertEqual(self.budget.active,0)

    def test_corrupt_artifact_stops(self):
        client=FakeHTTP([self.body(),self.raw[:-1]+bytes([self.raw[-1]^1])])
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_ARTIFACT_INVALID'):self.collector(client).collect('sample-sdk','npm')
        self.assertEqual(len(client.calls),2)

    def test_redirected_response_is_terminal(self):
        client=FakeHTTP([(200,'https://elsewhere.test',{},b'{}')])
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_RESPONSE_URL_MISMATCH'):self.collector(client).collect('sample-sdk','npm')

    def test_repeated_collect_cannot_repeat_requests(self):
        client=FakeHTTP([self.body(),self.raw]);obj=self.collector(client);obj.collect('sample-sdk','npm')
        with self.assertRaises(RuntimeError):obj.collect('sample-sdk','npm')
        self.assertEqual(len(client.calls),2)

    def test_existing_journal_refuses_before_dispatch(self):
        (self.root/'http.jsonl').write_text('existing')
        client=FakeHTTP([])
        with self.assertRaises(ValueError):self.collector(client)
        self.assertEqual(client.calls,[])

    def test_journal_intent_is_persisted_before_http(self):
        def callback(count):
            rows=[json.loads(line) for line in (self.root/'http.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['event'],'intent')
        self.collector(FakeHTTP([self.body(),self.raw],callback)).collect('sample-sdk','npm')

    def test_deadline_stop_after_metadata_no_artifact(self):
        client=FakeHTTP([self.body()],lambda _count:self.budget.stop('STOP_OR_DEADLINE'))
        with self.assertRaises(BudgetStopped):self.collector(client).collect('sample-sdk','npm')
        self.assertEqual(len(client.calls),1)

    def test_unexpected_exception_is_sanitized(self):
        client=FakeHTTP([ValueError('SECRET_PROVIDER_DETAIL')])
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_TRANSPORT_ERROR'):self.collector(client).collect('sample-sdk','npm')
        self.assertNotIn('SECRET_PROVIDER_DETAIL',(self.root/'http.jsonl').read_text())

    def test_strict_json_rejects_duplicate_and_nonfinite(self):
        client=FakeHTTP([b'{"name":1,"name":2}'])
        with self.assertRaises(BudgetStopped):self.collector(client).collect('sample-sdk','npm')

    def test_transport_rejects_host_path_before_network(self):
        for url in ['https://evil.test/x','https://pypi.org/admin','https://registry.npmjs.org/a?secret=x','https://files.pythonhosted.org/packages/../x']:
            self.assertFalse(registry_url_allowed(url))
        self.assertTrue(registry_url_allowed('https://registry.npmjs.org/sample-sdk'))
        with patch('urllib.request.build_opener') as opener:
            with self.assertRaises(Exception):RegistryHTTPClient().get('https://evil.test',1,100)
            opener.assert_not_called()

    def test_transport_preserves_tarball_gzip_bytes(self):
        raw=self.raw
        class Response:
            status=200;headers={}
            def __init__(self):self.stream=io.BytesIO(raw)
            def read1(self,n):return self.stream.read(n)
            def geturl(self):return 'https://registry.npmjs.org/sample-sdk/-/sample-sdk-1.0.0.tgz'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=Response()
            response=RegistryHTTPClient().get(Response().geturl(),1,len(raw)+1)
        self.assertEqual(response.body,raw)


if __name__=='__main__':unittest.main()
