"""Fake SDK client only. Never import/create a real authenticated client."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,BudgetStopped
from closed_loop.native_support import ArgumentCritique,HumanMessage
from closed_loop.model_lead import LeadPlanOutput,PlannedResearch
from closed_loop.openai_backend import OpenAIModelBackend,APISpendEnvelope,schema_for,decode_as,create_live_backend


class FakeSDK:
    def __init__(self,refusal=False,incomplete=False,fail=False):
        self.calls=[];self.refusal=refusal;self.incomplete=incomplete;self.fail=fail;self.max_retries=0
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self,**kwargs):
        self.calls.append(kwargs)
        if self.fail:raise RuntimeError('SECRET_PROVIDER_ERROR_SHOULD_NOT_BE_ECHOED')
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100,completion_tokens=20),
            choices=[SimpleNamespace(finish_reason='length' if self.incomplete else 'stop',
                message=SimpleNamespace(refusal='policy' if self.refusal else None,
                    content=json.dumps({'critique':'fixture critique'})))])


def setup(client=None,cap='0.20',model_calls=20):
    req=request(max_model_calls=model_calls)
    budget=CallBudget(req);sdk=client or FakeSDK();money=APISpendEnvelope(cap)
    return OpenAIModelBackend(sdk,money,budget),sdk,money,budget


class BackendTests(unittest.TestCase):
    def test_no_live_client_or_credential_loading_without_approval(self):
        with self.assertRaises(PermissionError):
            create_live_backend(approved=False,limit_usd='0.20',call_budget=CallBudget(request()),env_file='MUST_NOT_BE_READ')

    def test_strict_schema_and_typed_decode_including_nullable_peer(self):
        schema=schema_for(LeadPlanOutput)
        self.assertFalse(schema['additionalProperties'])
        value=decode_as(LeadPlanOutput,{'tasks':[{'role':'market','question':'market size','subject_id':None,'source_path':None}]})
        self.assertIsInstance(value.tasks[0],PlannedResearch)
        with self.assertRaises(ValueError):decode_as(LeadPlanOutput,{'tasks':[],'funding_total':10})

    def test_fake_sdk_request_is_metered_and_capped(self):
        backend,sdk,money,budget=setup()
        output=backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(output.critique,'fixture critique')
        self.assertEqual(budget.used['model'],1)
        call=sdk.calls[0]
        self.assertEqual(call['max_completion_tokens'],1000)
        self.assertFalse(call['store']);self.assertTrue(call['response_format']['json_schema']['strict'])
        self.assertNotIn('tools',call)
        self.assertGreater(money.reserved,0)
        self.assertLessEqual(money.reserved,money.limit)

    def test_tiny_dollar_cap_stops_before_sdk(self):
        backend,sdk,money,_=setup(cap='0.00000001')
        with self.assertRaisesRegex(BudgetStopped,'API_DOLLAR'):backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(sdk.calls,[]);self.assertEqual(money.reserved,0)

    def test_direct_backend_cannot_bypass_model_call_cap(self):
        backend,sdk,_,_=setup(model_calls=1)
        backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        with self.assertRaises(BudgetStopped):backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(sdk.calls),1)

    def test_failed_attempt_keeps_reservation_and_redacts_provider_error(self):
        backend,sdk,money,budget=setup(FakeSDK(fail=True))
        with self.assertRaises(BudgetStopped) as caught:backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertGreater(money.reserved,0);self.assertEqual(budget.used['model'],1)
        self.assertEqual(budget.active,0)

    def test_incomplete_or_refused_response_never_becomes_argument(self):
        for sdk in (FakeSDK(refusal=True),FakeSDK(incomplete=True)):
            backend,*_=setup(sdk)
            with self.assertRaises(BudgetStopped):backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)

    def test_oversize_prompt_and_hidden_retries_fail_before_send(self):
        backend,sdk,money,budget=setup()
        with self.assertRaises(BudgetStopped):backend.generate(ArgumentCritique,[HumanMessage('x'*40000)],0)
        self.assertEqual(sdk.calls,[]);self.assertEqual(money.reserved,0);self.assertEqual(budget.used['model'],0)
        sdk.max_retries=2
        with self.assertRaises(ValueError):OpenAIModelBackend(sdk,money,budget)

    def test_parallel_dollar_reservations_never_exceed_cap(self):
        envelope=APISpendEnvelope('0.002')
        def reserve(_):
            try:envelope.reserve(9000,1000);return True
            except BudgetStopped:return False
        with ThreadPoolExecutor(max_workers=8) as pool:success=list(pool.map(reserve,range(8)))
        self.assertEqual(sum(success),1)
        self.assertLessEqual(envelope.reserved,Decimal('0.002'))

    def test_persistent_budget_and_request_cap_survive_restart(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pilot.jsonl'
            first=APISpendEnvelope('0.20',path,request_cap=1)
            first.reserve(1000,1000);reserved=first.reserved;first.close()
            second=APISpendEnvelope('0.20',path,request_cap=1)
            try:
                self.assertEqual(second.reserved,reserved)
                self.assertEqual(second.request_count,1)
                with self.assertRaisesRegex(BudgetStopped,'PILOT_REQUEST_CAP'):second.reserve(1000,1000)
            finally:second.close()

    def test_exclusive_pilot_lease_prevents_two_budget_owners(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pilot.jsonl'
            first=APISpendEnvelope('0.20',path)
            try:
                with self.assertRaisesRegex(BudgetStopped,'LEASE_ALREADY_HELD'):APISpendEnvelope('0.20',path)
            finally:first.close()

    def test_corrupt_budget_journal_fails_closed_and_releases_lease(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pilot.jsonl';path.write_text('truncated invalid journal')
            with self.assertRaises(ValueError):APISpendEnvelope('0.20',path)
            self.assertFalse(path.with_suffix('.jsonl.lock').exists())

    def test_completed_pilot_cannot_be_reopened_with_unused_balance(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'pilot.jsonl'
            first=APISpendEnvelope('0.20',path);first.seal_completed();first.close()
            with self.assertRaisesRegex(BudgetStopped,'ALREADY_COMPLETED'):APISpendEnvelope('0.20',path)


if __name__=='__main__':unittest.main()
