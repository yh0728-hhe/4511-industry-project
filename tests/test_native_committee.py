"""Actual adapted upstream stage bodies, deterministic model responses only.

Windows asyncio uses process-owned loopback IPC. Run in a shell that allows
loopback; OfflineSocketGuard blocks external socket traffic before any test.
"""
from pathlib import Path
from dataclasses import replace
import asyncio
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.contracts import Decision
from closed_loop.fixtures import request,FixtureProvider,FixtureLead
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.runtime import ClosedLoopRuntime,FactStore,committee_input
from closed_loop.native_committee import NativeDialecticCommittee,NativeConfig
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.native_support import get_llm,ArgumentsOutput,ArgumentOutput,SingleArgumentScore,CriterionScore
from closed_loop.offline_network import OfflineSocketGuard


def build(good=True,empty=False,cap=40,config=None,backend=None,**updates):
    req=request(max_model_calls=cap,**updates)
    provider=FixtureProvider(good=good,empty=empty)
    budget=CallBudget(req)
    backend=backend or NativeFixtureBackend()
    committee=NativeDialecticCommittee(backend,budget,config)
    runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,FixtureLead(),committee,provider)
    return runtime,budget,backend,committee


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.network=OfflineSocketGuard().install()
    @classmethod
    def tearDownClass(cls):cls.network.restore()

    def test_real_stage_bodies_execute_and_new_facts_reach_second_pass(self):
        runtime,budget,backend,committee=build()
        result=runtime.run()
        self.assertEqual(result['decision'],'INVEST')
        self.assertEqual(budget.used['model'],len(backend.calls)+2) # two fixture lead dispatches
        stages=[x['stage'] for x in result['trace'] if x['event']=='NATIVE_COMMITTEE_STAGE']
        self.assertEqual(stages.count('generation'),2)
        self.assertIn('critique',stages);self.assertIn('refinement',stages)
        argument_stages=[x for x in result['trace'] if x['event']=='NATIVE_COMMITTEE_STAGE']
        for stage in argument_stages:
            self.assertTrue(stage['arguments'])
            for argument in stage['arguments']:
                self.assertTrue(argument['text'])
                self.assertTrue(argument['cited_fact_ids'])
                self.assertTrue(set(argument['cited_fact_ids'])<=set(stage['qa_fact_ids']))
                self.assertTrue(argument['source_support_not_semantically_certified'])
        revisions={c['fact_revision'] for c in backend.calls}
        self.assertEqual(revisions,{1,2})
        first={f for c in backend.calls if c['fact_revision']==1 for f in c['fact_ids']}
        second={f for c in backend.calls if c['fact_revision']==2 for f in c['fact_ids']}
        self.assertTrue(first<second)
        self.assertEqual(budget.active,0)

    def test_poor_observed_retention_is_pass_but_unknown_is_not(self):
        runtime,*_=build(good=False)
        self.assertEqual(runtime.run()['decision'],'PASS')
        runtime,*_=build(empty=True)
        self.assertEqual(runtime.run()['decision'],'MORE_DILIGENCE')

    def test_nested_call_budget_stops_before_backend_not_after(self):
        runtime,budget,backend,_=build(cap=3)
        result=runtime.run()
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'CALL_CAP')
        self.assertEqual(budget.used['model'],3)
        self.assertEqual(len(backend.calls),2) # one fixture lead + two generation calls
        self.assertEqual(budget.active,0)

    def test_invalid_negative_qa_index_fails_before_native_indexing(self):
        class BadCitation(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                value=super().generate(schema,messages,temperature)
                if schema is ArgumentsOutput:return ArgumentsOutput([ArgumentOutput('invalid',[-1])])
                return value
        runtime,_,_,_=build(backend=BadCitation())
        result=runtime.run()
        self.assertEqual(result['stop_reason'],'INVALID_QA_CITATION')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        with self.assertRaisesRegex(RuntimeError,'No explicit'):get_llm()

    def test_original_internal_score_count_retry_is_metered(self):
        class WrongCountOnce(NativeFixtureBackend):
            failed=False
            def generate(self,schema,messages,temperature):
                value=super().generate(schema,messages,temperature)
                if schema is SingleArgumentScore and not self.failed:
                    self.failed=True;return SingleArgumentScore([CriterionScore(3,'fixture')])
                return value
        runtime,budget,backend,_=build(backend=WrongCountOnce())
        result=runtime.run()
        self.assertEqual(result['decision'],'INVEST')
        self.assertTrue(backend.failed)
        self.assertEqual(budget.used['model'],len(backend.calls)+2)

    def test_original_global_topk_and_explicit_balanced_variant_are_distinct(self):
        legacy,*_=build()
        old=legacy.run()
        balanced,*_=build(config=NativeConfig(selection_policy='balanced_per_side'))
        new=balanced.run()
        old_selected=[e['selected_types'] for e in old['trace'] if e.get('stage')=='score_and_select']
        new_selected=[e['selected_types'] for e in new['trace'] if e.get('stage')=='score_and_select']
        self.assertTrue(all(len(x)==1 for x in old_selected))
        self.assertTrue(all(set(x)=={'pro','contra'} for x in new_selected))

    def test_no_implicit_live_backend_or_client_on_import(self):
        with self.assertRaises(ValueError):NativeDialecticCommittee(None,CallBudget(request()))
        with self.assertRaises(RuntimeError):get_llm()

    def test_future_qa_date_is_held_even_on_direct_adapter_call(self):
        runtime,budget,backend,committee=build()
        fact,_=runtime.gateway.admit(runtime.provider.market)
        store=FactStore();store.merge([fact]);view=committee_input(runtime.request,store,1)
        rows=tuple(dict(row,available_by='2025-01-01T00:00:00+00:00') for row in view.qa_pairs)
        with self.assertRaisesRegex(BudgetStopped,'FUTURE_QA_DATE'):committee.evaluate(replace(view,qa_pairs=rows))
        self.assertEqual(backend.calls,[]);self.assertEqual(budget.used['model'],0)

    def test_one_instance_rejects_overlapping_evaluation_without_corrupting_trace(self):
        class Slow(NativeFixtureBackend):
            async def agenerate(self,schema,messages,temperature):
                if not self.waited:
                    self.waited=True;self.started.set();await self.release.wait()
                return await super().agenerate(schema,messages,temperature)
        backend=Slow();backend.started=asyncio.Event();backend.release=asyncio.Event();backend.waited=False
        runtime,_,_,committee=build(backend=backend)
        fact,_=runtime.gateway.admit(runtime.provider.market);store=FactStore();store.merge([fact])
        view=committee_input(runtime.request,store,1)
        async def scenario():
            first=asyncio.create_task(committee.evaluate_async(view))
            try:
                await asyncio.wait_for(backend.started.wait(),1)
                with self.assertRaisesRegex(BudgetStopped,'COMMITTEE_INSTANCE_BUSY'):await committee.evaluate_async(view)
            finally:backend.release.set()
            await first
        asyncio.run(scenario())
        self.assertTrue(committee.last_trace);self.assertTrue(committee.last_calls)

    def test_mid_gather_stop_releases_reserved_siblings(self):
        class StopsDuringScores(NativeFixtureBackend):
            async def agenerate(self,schema,messages,temperature):
                if schema is SingleArgumentScore:
                    self.score_attempts+=1
                    if self.score_attempts==1:
                        await asyncio.sleep(0.01);raise BudgetStopped('FIXTURE_MID_GATHER_STOP')
                    await asyncio.sleep(1)
                return await super().agenerate(schema,messages,temperature)
        backend=StopsDuringScores(argument_count=2);backend.score_attempts=0
        config=NativeConfig(n_pro_arguments=2,n_contra_arguments=2)
        runtime,budget,_,_=build(backend=backend,config=config,concurrency=2)
        result=runtime.run()
        self.assertEqual(result['stop_reason'],'FIXTURE_MID_GATHER_STOP')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(budget.active,0)


if __name__=='__main__':unittest.main()
