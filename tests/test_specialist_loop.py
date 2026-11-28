"""Tests for the model-guided specialist research action loop (not real company research)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.agent_prompts import RESEARCH_PROTOCOL
from closed_loop.contracts import CommitteeResult,Decision,ResearchRequest
from closed_loop.fixtures import request,source
from closed_loop.guards import BudgetStopped,CallBudget,TemporalGateway
from closed_loop.runtime import ClosedLoopRuntime,FactStore
from closed_loop.specialist_loop import SpecialistAction,SpecialistResearchLoop


class LinkHintProvider:
    """Simulated/fixture provider for a synthetic company only; not a real source."""
    def __init__(self):
        self.root,self.root_record=source('root-2024','overview','SYNTHETIC_ROOT_TEXT')
        self.deep,self.deep_record=source('deep-2024','overview','SYNTHETIC_TEAM_TEXT')
        self.ledger={r.source_id:r for r in (self.root_record,self.deep_record)}
        self.search_calls=[]

    def search(self,task):
        self.search_calls.append(task.source_path)
        if task.source_path is None:return (self.root,)
        if task.source_path=='/team':return (self.deep,)
        return ()

    def link_hints(self):
        return ({'subject_id':'SYNTHETIC_COMPANY','url':'https://synthetic.example/team','path':'/team',
            'label':'Team','observed_at':'2024-03-20T00:00:00+00:00','found_in_source_id':'root-2024',
            'target_content_verified':False},)


class ScriptedSpecialistBackend:
    """Simulation-only fake model: labeled fixture, not a real/API-backed decision."""
    def __init__(self,scripted):
        self.scripted=list(scripted);self.messages_seen=[]

    def generate(self,schema,messages,temperature):
        self.messages_seen.append(messages)
        return self.scripted.pop(0)


class SpecialistLoopTests(unittest.TestCase):
    def test_second_action_follows_first_actions_link_hint_and_meters_both_calls(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('FOLLOW_LINK','/team'),SpecialistAction('SUBMIT_FACT')])
        loop=SpecialistResearchLoop(backend,budget)
        trace=[]
        task=ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY')
        facts=loop.run(task,provider,gateway,trace,req.as_of)

        self.assertEqual(provider.search_calls,[None,'/team'])
        self.assertEqual({f.source_id for f in facts},{'root-2024','deep-2024'})
        self.assertEqual(budget.used['search'],2)
        self.assertEqual(budget.used['model'],2)
        steps=[e for e in trace if e['event']=='SPECIALIST_LOOP_STEP']
        self.assertEqual([s['action'] for s in steps],['FOLLOW_LINK','SUBMIT_FACT'])
        self.assertTrue(any(RESEARCH_PROTOCOL in message.content for calls in backend.messages_seen for message in calls))

    def test_stop_action_halts_without_a_second_dispatch(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('STOP',reason='answered scope')])
        loop=SpecialistResearchLoop(backend,budget)
        trace=[]
        task=ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY')
        facts=loop.run(task,provider,gateway,trace,req.as_of)
        self.assertEqual(provider.search_calls,[None])
        self.assertEqual({f.source_id for f in facts},{'root-2024'})
        self.assertEqual(budget.used['model'],1)

    def test_follow_link_to_unobserved_path_is_rejected_as_no_new_lead(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('FOLLOW_LINK','/not-a-real-hint')])
        loop=SpecialistResearchLoop(backend,budget)
        trace=[]
        task=ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY')
        loop.run(task,provider,gateway,trace,req.as_of)
        self.assertEqual(provider.search_calls,[None])
        reasons=[e['reason'] for e in trace if e['event']=='SPECIALIST_LOOP_STEP']
        self.assertIn('NO_NEW_CONCRETE_LEAD',reasons)

    def test_repeating_an_already_tried_path_is_rejected_not_an_infinite_loop(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('FOLLOW_LINK','/team'),SpecialistAction('FOLLOW_LINK','/team')])
        loop=SpecialistResearchLoop(backend,budget)
        trace=[]
        task=ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY')
        loop.run(task,provider,gateway,trace,req.as_of)
        self.assertEqual(provider.search_calls,[None,'/team'])

    def test_invalid_model_action_is_rejected_not_executed(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('DELETE_EVERYTHING')])
        loop=SpecialistResearchLoop(backend,budget)
        with self.assertRaisesRegex(BudgetStopped,'INVALID_SPECIALIST_ACTION'):
            loop.run(ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY'),provider,gateway,[],req.as_of)

    def test_explicit_backend_required_matching_model_lead_pattern(self):
        with self.assertRaisesRegex(ValueError,'explicit specialist model backend required'):
            SpecialistResearchLoop(None,CallBudget(request()))

    def test_bounded_iteration_count_required(self):
        with self.assertRaisesRegex(ValueError,'bounded iteration count required'):
            SpecialistResearchLoop(ScriptedSpecialistBackend([]),CallBudget(request()),max_iterations=0)

    def test_terminates_on_provider_request_cap_like_existing_provider_cap_test(self):
        req=request(max_search_calls=1);budget=CallBudget(req)
        provider=LinkHintProvider();gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('FOLLOW_LINK','/team'),SpecialistAction('SUBMIT_FACT')])
        loop=SpecialistResearchLoop(backend,budget)
        with self.assertRaises(BudgetStopped):
            loop.run(ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY'),provider,gateway,[],req.as_of)

    def test_runtime_research_contract_unchanged_when_specialist_is_none(self):
        from closed_loop.fixtures import FixtureLead,FixtureCommittee,FixtureProvider
        req=request();provider=FixtureProvider()
        runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),
            FixtureLead(),FixtureCommittee(),provider)
        result=runtime.run()
        self.assertEqual(result['decision'],'INVEST')
        self.assertFalse(any(e['event']=='SPECIALIST_LOOP_STEP' for e in result['trace']))

    def test_runtime_wires_specialist_loop_and_emits_steps_in_trace(self):
        req=request();budget=CallBudget(req)
        provider=LinkHintProvider()

        class SingleRoleLead:
            def select(self,req,gaps):
                return (ResearchRequest('team','Who are the founders?','SYNTHETIC_COMPANY'),)

        class OneShotCommittee:
            def evaluate(self,view):
                ids=tuple(row['fact_id'] for row in view.qa_pairs)
                return CommitteeResult(Decision.PASS,'Synthetic one-shot stop; no further research pass.',
                    (),view.fact_revision,view.argument_revision,ids)

        gateway=TemporalGateway(req,provider.ledger)
        backend=ScriptedSpecialistBackend([SpecialistAction('FOLLOW_LINK','/team'),SpecialistAction('SUBMIT_FACT')])
        specialist=SpecialistResearchLoop(backend,budget)
        runtime=ClosedLoopRuntime(req,gateway,budget,SingleRoleLead(),OneShotCommittee(),provider,specialist=specialist)
        result=runtime.run()
        steps=[e for e in result['trace'] if e['event']=='SPECIALIST_LOOP_STEP']
        self.assertEqual(len(steps),2)
        research_events=[e for e in result['trace'] if e['event']=='RESEARCH']
        self.assertEqual(research_events[0]['cache_hit'],False)
        self.assertEqual(len(research_events[0]['admitted_fact_ids']),2)


if __name__=='__main__':unittest.main()
