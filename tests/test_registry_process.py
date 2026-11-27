"""Process-isolated registry transport fixtures: no external HTTP or model."""
import base64
import json
import io
from types import SimpleNamespace
from unittest.mock import patch
import subprocess
import unittest
from closed_loop.archive_transport import HTTPResponse
from closed_loop.guards import BudgetStopped
from closed_loop.package_registry import RegistryTransportError,RegistryTransportTimeout
from closed_loop.registry_process import IsolatedRegistryHTTPClient
URL='https://registry.npmjs.org/sample-sdk'

def envelope(body=b'raw gzip bytes',status=200,**changes):
    value=dict(status='ok',http_status=status,url=URL,headers={},body_b64=base64.b64encode(body).decode())
    value.update(changes);return json.dumps(value).encode()

class FakeExecutor:
    def __init__(self,response=None,error=None):self.calls=[];self.response=response or envelope();self.error=error
    def run(self,argv,stdin_bytes,timeout_seconds):
        self.calls.append((argv,stdin_bytes,timeout_seconds))
        if self.error:raise self.error
        return 0,self.response,b''

class IsolatedRegistryTests(unittest.TestCase):
    def test_one_child_exact_bytes_and_no_shell_or_fallback(self):
        raw=b'\\x1f\\x8b\\x00raw';executor=FakeExecutor(envelope(raw))
        client=IsolatedRegistryHTTPClient(executor=executor)
        self.assertEqual(executor.calls,[])
        r=client.get(URL,1,100)
        self.assertIsInstance(r,HTTPResponse);self.assertEqual(r.body,raw)
        self.assertEqual(len(executor.calls),1)
        argv,stdin,timeout=executor.calls[0]
        self.assertIsInstance(argv,list);self.assertEqual(timeout,1)
        self.assertEqual(json.loads(stdin),dict(url=URL,timeout=1,max_bytes=100))
    def test_invalid_host_or_bounds_never_starts_child(self):
        executor=FakeExecutor();client=IsolatedRegistryHTTPClient(executor=executor)
        for url,timeout,cap in [('https://evil.test',1,100),(URL,True,100),(URL,float('nan'),100),(URL,61,100),(URL,1,True),(URL,1,8000001)]:
            with self.subTest(url=url,timeout=timeout,cap=cap),self.assertRaises(RegistryTransportError):client.get(url,timeout,cap)
        self.assertEqual(executor.calls,[])
    def test_timeout_drops_partial_output_without_retry(self):
        error=subprocess.TimeoutExpired(['fake'],1,output=b'{"status":"ok"}')
        executor=FakeExecutor(error=error);client=IsolatedRegistryHTTPClient(executor=executor)
        with self.assertRaises(RegistryTransportTimeout):client.get(URL,1,100)
        self.assertEqual(len(executor.calls),1)
    def test_expired_shared_budget_wins_over_process_timeout(self):
        calls=[]
        def check():
            calls.append(1)
            if len(calls)>1:raise BudgetStopped('STOP_OR_DEADLINE')
        executor=FakeExecutor(error=subprocess.TimeoutExpired(['fake'],1))
        with self.assertRaisesRegex(BudgetStopped,'STOP_OR_DEADLINE'):
            IsolatedRegistryHTTPClient(executor=executor).get(URL,1,100,check_deadline=check)
        self.assertEqual(len(executor.calls),1)
    def test_corrupt_or_mismatched_child_output_refused(self):
        for raw in [envelope(body_b64='not base64!'),envelope(url='https://evil.test'),envelope(http_status=True),envelope(headers=[]),envelope(body=b'x'*101),b'{"status":"ok","status":"ok"}',b'x'*132000]:
            with self.subTest(length=len(raw)),self.assertRaises(RegistryTransportError):
                IsolatedRegistryHTTPClient(executor=FakeExecutor(raw)).get(URL,1,100)
    def test_duplicate_fields_refused_even_when_other_fields_are_valid(self):
        raw=envelope().replace(b'"status": "ok"',b'"status": "error", "status": "ok"')
        with self.assertRaises(RegistryTransportError):
            IsolatedRegistryHTTPClient(executor=FakeExecutor(raw)).get(URL,1,100)

    def test_deadline_after_response_validation_cannot_release_response(self):
        count=[]
        def check():
            count.append(1)
            if len(count)==3:raise BudgetStopped('STOP_OR_DEADLINE')
        with self.assertRaisesRegex(BudgetStopped,'STOP_OR_DEADLINE'):
            IsolatedRegistryHTTPClient(executor=FakeExecutor()).get(URL,1,100,check_deadline=check)
        self.assertEqual(len(count),3)

    def test_rate_limit_is_retained_as_http_response_not_retried(self):
        executor=FakeExecutor(envelope(b'',status=429))
        r=IsolatedRegistryHTTPClient(executor=executor).get(URL,1,100)
        self.assertEqual(r.status,429);self.assertEqual(len(executor.calls),1)


class RegistryWorkerTests(unittest.TestCase):
    def test_invalid_or_duplicate_request_never_reaches_raw_transport(self):
        from closed_loop.registry_worker import _read_request
        good=json.dumps(dict(url=URL,timeout=1,max_bytes=100)).encode()
        for raw in [good.replace(b'"timeout": 1',b'"timeout": 1,"timeout": 2'),
                    good.replace(URL.encode(),b'https://evil.test'),b'x'*8193,
                    good.replace(b'"timeout": 1',b'"timeout": NaN')]:
            with self.subTest(raw=raw[:30]),self.assertRaises(ValueError):_read_request(io.BytesIO(raw))

    def run_worker(self,client):
        from closed_loop import registry_worker
        output=io.BytesIO();request=json.dumps(dict(url=URL,timeout=1,max_bytes=100)).encode()
        with patch.object(registry_worker.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(request))),patch.object(registry_worker.sys,'stdout',SimpleNamespace(buffer=output)),patch('closed_loop.package_registry.RegistryHTTPClient',return_value=client):
            code=registry_worker.main()
        return code,json.loads(output.getvalue())

    def test_worker_preserves_raw_gzip_without_network(self):
        raw=bytes([31,139,0,255])
        class Client:
            def get(self,url,timeout,max_bytes,check_deadline):
                check_deadline();return HTTPResponse(200,url,{},raw)
        code,out=self.run_worker(Client());self.assertEqual(code,0)
        self.assertEqual(base64.b64decode(out['body_b64']),raw)

    def test_worker_error_is_sanitized_and_never_an_http_response(self):
        class Client:
            def get(self,*args,**kwargs):raise ValueError('PRIVATE_TRANSPORT_DETAIL')
        code,out=self.run_worker(Client());self.assertEqual(code,2)
        self.assertEqual(out,dict(status='error',error='REGISTRY_WORKER_FAILED'))
        self.assertNotIn('PRIVATE_TRANSPORT_DETAIL',json.dumps(out))

if __name__=='__main__':unittest.main()
