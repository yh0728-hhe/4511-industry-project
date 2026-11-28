"""Offline allowance allocation regressions; no live model-quality assertions."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from closed_loop.fixtures import request,source
from closed_loop.guards import BudgetStopped
from closed_loop.equal_allowance_pair import execute_equal_allowance_pair
from test_paired_evaluation import PairBackend


class MeteredPair(PairBackend):
    def __init__(self,budget):
        super().__init__();self.call_budget=budget;self.model_id=budget.bound_request.model_version
        self.process_count=0;self.max_process_count=budget.bound_request.max_model_calls
    def generate(self,*args):
        with self.call_budget.reserve('model'):
            self.process_count+=1
            return super().generate(*args)


class EqualAllowanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'pair';self.backends=[]
    def factory(self,budget,root):
        backend=MeteredPair(budget);self.backends.append(backend);return backend
    def run_pair(self,**updates):
        args=dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=300),
            max_model_calls=24,max_search_calls=0),source_items=(source('market','market','SYNTHETIC_MARKET_CONTEXT'),),
            output_dir=self.root,backend_factory=self.factory,per_arm_calls=12,
            per_arm_seconds=120,approved=True)
        args.update(updates);return execute_equal_allowance_pair(**args)
    def test_same_evidence_and_separate_equal_unborrowed_allocations(self):
        result=self.run_pair()
        self.assertEqual(len(self.backends),2)
        a,b=self.backends
        self.assertIsNot(a.call_budget,b.call_budget)
        self.assertEqual(a.call_budget.caps,b.call_budget.caps)
        self.assertEqual(a.baseline_inputs[0]['evidence'],b.committee_inputs[0]['evidence'])
        self.assertEqual(result['arms'][0]['model_reservations'],1)
        self.assertGreater(result['arms'][1]['model_reservations'],1)
        self.assertEqual(result['model_reservations'],sum(x.process_count for x in self.backends))
        self.assertEqual(result['arms'][1]['budget_snapshot']['caps']['model'],12)
        self.assertTrue(result['fairness']['equal_per_arm_logical_call_ceiling'])
        self.assertFalse(result['fairness']['equal_actual_tokens'])
        self.assertEqual(result['invoice'],'UNKNOWN')
        self.assertFalse(result['predictive_accuracy_evaluated'])
        self.assertEqual(json.loads((self.root/'result.json').read_text()),result)
    def test_committee_cap_does_not_starve_baseline(self):
        req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=300),max_model_calls=2,max_search_calls=0)
        result=self.run_pair(request=req,per_arm_calls=1,arm_order=('committee','single_analyst'))
        self.assertEqual([a['model_reservations'] for a in result['arms']],[1,1])
        self.assertEqual(result['arms'][0]['status'],'STOPPED_NO_RETRY')
        self.assertEqual(result['arms'][0]['reason'],'CALL_CAP')
        self.assertEqual(result['arms'][1]['status'],'EXECUTED_REVIEW_PENDING')
        self.assertIsNone(result['global_stop_reason'])
        self.assertTrue((self.root/'committee'/'committee_draft_trace.json').exists())
    def test_account_quota_aborts_second_arm_without_factory_or_reset(self):
        class Quota(MeteredPair):
            def generate(self,*args):
                with self.call_budget.reserve('model'):
                    self.process_count+=1;self.call_budget.stop('CLI_QUOTA_EXHAUSTED')
                    raise BudgetStopped('secondary error must not replace quota')
        def factory(budget,root):
            backend=Quota(budget);self.backends.append(backend);return backend
        result=self.run_pair(backend_factory=factory)
        self.assertEqual(result['global_stop_reason'],'CLI_QUOTA_EXHAUSTED')
        self.assertEqual(result['arms'][1]['status'],'NOT_RUN_GLOBAL_STOP')
        self.assertEqual(len(self.backends),1)
        self.assertEqual(result['model_reservations'],1)
    def test_local_deadline_does_not_extend_or_reset_either_arm(self):
        def factory(budget,root):
            backend=self.factory(budget,root)
            if len(self.backends)==1:budget.clock=lambda:budget.deadline
            return backend
        result=self.run_pair(backend_factory=factory)
        self.assertEqual(result['arms'][0]['reason'],'STOP_OR_DEADLINE')
        self.assertEqual(result['arms'][0]['model_reservations'],0)
        self.assertEqual(result['arms'][1]['status'],'EXECUTED_REVIEW_PENDING')
    def test_setup_failure_persisted_and_pair_stopped_no_secret(self):
        def factory(*args):raise RuntimeError('SECRET_CREDENTIAL')
        result=self.run_pair(backend_factory=factory)
        self.assertEqual(result['arms'][0]['status'],'SETUP_FAILED_NO_RETRY')
        self.assertEqual(result['arms'][1]['status'],'NOT_RUN_GLOBAL_STOP')
        self.assertNotIn('SECRET_CREDENTIAL',(self.root/'result.json').read_text())
    def test_model_or_budget_mismatch_fails_closed(self):
        def factory(budget,root):
            backend=self.factory(budget,root);backend.model_id='DIFFERENT_MODEL';return backend
        result=self.run_pair(backend_factory=factory)
        self.assertEqual(result['model_reservations'],0)
        self.assertEqual(result['global_stop_reason'],'EQUAL_ALLOWANCE_BACKEND_SETUP_FAILED')
    def test_unbound_backend_is_not_accepted(self):
        result=self.run_pair(backend_factory=lambda *a:PairBackend())
        self.assertEqual(result['global_stop_reason'],'EQUAL_ALLOWANCE_BACKEND_SETUP_FAILED')
    def test_invalid_bounds_and_approval_refused_before_side_effects(self):
        bads=[dict(approved=False),dict(per_arm_calls=True),dict(per_arm_calls=13),
            dict(per_arm_seconds=True),dict(per_arm_seconds=181),
            dict(arm_order=['committee','single_analyst']),dict(arm_order=('committee','committee')),
            dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=300),max_model_calls=23,max_search_calls=0)),
            dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=30),max_model_calls=24,max_search_calls=0))]
        for changes in bads:
            with self.subTest(changes=changes):
                with self.assertRaises((ValueError,PermissionError)):self.run_pair(**changes)
                self.assertFalse(self.root.exists());self.assertEqual(self.backends,[])
    def test_future_or_corrupt_evidence_never_reaches_factory(self):
        candidate,record=source('market','market','SYNTHETIC_MARKET_CONTEXT')
        for item in [(candidate,replace(record,content_sha256='0'*64)),
                     source('late','market','FUTURE',available='2025-01-01T00:00:00Z')]:
            with self.assertRaises(ValueError):self.run_pair(source_items=(item,))
            self.assertFalse(self.root.exists());self.assertEqual(self.backends,[])
    def test_existing_run_cannot_be_overwritten(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):self.run_pair()
        self.assertEqual(self.backends,[])
    def test_global_deadline_prevents_unequal_clipped_second_allocation(self):
        origin=datetime.now(timezone.utc);values=iter([origin,origin,origin+timedelta(seconds=290)])
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return next(values)
        req=request(deadline=origin+timedelta(seconds=300),max_model_calls=24,max_search_calls=0)
        with patch('closed_loop.equal_allowance_pair.datetime',Clock):result=self.run_pair(request=req)
        self.assertEqual(len(self.backends),1)
        self.assertEqual(result['arms'][1]['reason'],'GLOBAL_TIME_ALLOWANCE_UNAVAILABLE')
    def test_reusing_backend_cannot_reset_state_for_second_arm(self):
        backend=None
        def factory(budget,root):
            nonlocal backend
            if backend is None:backend=self.factory(budget,root)
            backend.call_budget=budget
            return backend
        result=self.run_pair(backend_factory=factory)
        self.assertEqual(result['arms'][0]['status'],'EXECUTED_REVIEW_PENDING')
        self.assertEqual(result['arms'][1]['status'],'SETUP_FAILED_NO_RETRY')
        self.assertEqual(result['arms'][1]['model_reservations'],0)
    def test_unknown_or_different_physical_ceiling_refused(self):
        for value in (None,True,1,24):
            with self.subTest(cap=value):
                def factory(budget,root):
                    backend=self.factory(budget,root);backend.max_process_count=value;return backend
                result=self.run_pair(output_dir=self.root/str(value),backend_factory=factory)
                self.assertEqual(result['model_reservations'],0)
                self.assertEqual(result['global_stop_reason'],'EQUAL_ALLOWANCE_BACKEND_SETUP_FAILED')
    def test_request_and_sources_unchanged(self):
        req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=300),max_model_calls=24,max_search_calls=0)
        self.run_pair(request=req)
        self.assertEqual(req.max_model_calls,24)
        self.assertEqual(self.backends[0].call_budget.bound_request.max_model_calls,12)


if __name__=='__main__':unittest.main()
