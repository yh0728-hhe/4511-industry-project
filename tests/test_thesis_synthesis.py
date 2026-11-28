"""Tests for the optional final thesis synthesis stage (T2_thesis_synthesis_stage).

All scenarios here are offline, deterministic, scripted-backend fixtures over a
synthetic company (`SYNTHETIC_COMPANY`); none of this is the real, sealed, paid
Abel pilot (`results/candidates/closed_loop_offline/approved_api_pilot_closeout.json`
/ `live_one_company_result.json`), which is NOT re-run or touched by this file.
"""
import dataclasses
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.agent_prompts import THESIS_SYNTHESIS_INSTRUCTION
from closed_loop.contracts import CommitteeResult,Decision
from closed_loop.fixtures import request,run_case
from closed_loop.guards import BudgetStopped,CallBudget,TemporalGateway
from closed_loop.runtime import FactStore,committee_input
from closed_loop.thesis_synthesis import ThesisSynthesis,ThesisSynthesizer


class ScriptedThesisBackend:
    """Simulation-only fake model: labeled fixture, not a real/API-backed decision."""
    def __init__(self,scripted):
        self.scripted=list(scripted);self.messages_seen=[]

    def generate(self,schema,messages,temperature):
        self.messages_seen.append(messages)
        return self.scripted.pop(0)


def _good_thesis(cited_fact_ids):
    return ThesisSynthesis('Synthetic retention supports investment.',
        ['Market context and strong retention are both supported.'],
        ['No contradicting evidence admitted.'],list(cited_fact_ids),
        ['Pricing is unknown; not treated as negative.'],
        ['Would a poor-retention cohort reverse this?'],['Verify pricing before closing.'])


class SchemaTests(unittest.TestCase):
    def test_no_numeric_score_or_probability_field(self):
        for f in dataclasses.fields(ThesisSynthesis):
            self.assertNotIn(f.type,('float','int'),f'{f.name} must not be a numeric score/probability field')

    def test_explicit_backend_required_matching_model_lead_pattern(self):
        with self.assertRaisesRegex(ValueError,'explicit synthesis model backend required'):
            ThesisSynthesizer(None,CallBudget(request()))


class SynthesizerGatingTests(unittest.TestCase):
    def _store_with_two_facts(self):
        req=request()
        gateway=TemporalGateway(req,{})
        from closed_loop.fixtures import source
        market,market_record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        retention,retention_record=source('retention-2024','retention','SYNTHETIC_RETENTION_GOOD')
        gateway=TemporalGateway(req,{'market-2024':market_record,'retention-2024':retention_record})
        store=FactStore()
        for candidate in (market,retention):
            fact,_=gateway.admit(candidate)
            store.merge([fact])
        return req,store

    def test_never_invoked_for_more_diligence(self):
        req,store=self._store_with_two_facts()
        budget=CallBudget(req)
        synthesizer=ThesisSynthesizer(ScriptedThesisBackend([]),budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=store)
        gap_result=CommitteeResult(Decision.MORE_DILIGENCE,'Retention not yet established.',
            ('retention',),store.revision,0,tuple(f.fact_id for f in store.facts))
        with self.assertRaisesRegex(ValueError,'MORE_DILIGENCE'):
            synthesizer.synthesize(req,context,gap_result)
        self.assertEqual(synthesizer.last_calls,[])

    def test_input_view_limited_to_committee_cited_facts_only(self):
        req,store=self._store_with_two_facts()
        budget=CallBudget(req)
        market_id=next(f.fact_id for f in store.facts if f.topic=='market')
        backend=ScriptedThesisBackend([_good_thesis([market_id])])
        synthesizer=ThesisSynthesizer(backend,budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=store)
        result=CommitteeResult(Decision.INVEST,'Market context alone cited.',(),
            store.revision,1,(market_id,))
        synthesizer.synthesize(req,context,result)
        import json as _json
        sys_msg=[m for messages in backend.messages_seen for m in messages if m.role=='system'][0]
        evidence=_json.loads(sys_msg.content[len(sys_msg.content.split('{',1)[0]):])['evidence']
        self.assertEqual({row['fact_id'] for row in evidence},{market_id})

    def test_cited_fact_ids_must_be_subset_of_store_facts(self):
        req,store=self._store_with_two_facts()
        budget=CallBudget(req)
        cited=tuple(f.fact_id for f in store.facts)
        backend=ScriptedThesisBackend([_good_thesis(['NOT_A_REAL_FACT_ID'])])
        synthesizer=ThesisSynthesizer(backend,budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=store)
        result=CommitteeResult(Decision.INVEST,'Synthetic retention criterion met.',(),store.revision,1,cited)
        with self.assertRaisesRegex(BudgetStopped,'THESIS_CITED_UNAVAILABLE_FACT'):
            synthesizer.synthesize(req,context,result)

    def test_future_dated_evidence_is_blocked_by_the_shared_cutoff_guard(self):
        """Source-cutoff guard: a fact somehow available after as_of cannot reach the model."""
        req,store=self._store_with_two_facts()
        budget=CallBudget(req)
        from dataclasses import replace
        future_fact=replace(next(iter(store.facts)),
            availability_upper_bound=req.as_of.replace(year=req.as_of.year+1),fact_id='FUTURE_FACT')
        bad_store=FactStore();bad_store.merge(list(store.facts)+[future_fact])
        backend=ScriptedThesisBackend([_good_thesis([future_fact.fact_id])])
        synthesizer=ThesisSynthesizer(backend,budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=bad_store)
        result=CommitteeResult(Decision.INVEST,'Synthetic.',(),bad_store.revision,1,(future_fact.fact_id,))
        with self.assertRaisesRegex(BudgetStopped,'FUTURE_QA_DATE'):
            synthesizer.synthesize(req,context,result)

    def test_budget_stop_is_visible_before_any_call(self):
        """Bounded/stopping behavior: an exhausted model budget stops the single call, no retry."""
        from dataclasses import replace
        req,store=self._store_with_two_facts()
        zero_budget_req=replace(req,max_model_calls=0)
        store2=FactStore()
        for fact in store.facts:store2.merge([fact])
        budget=CallBudget(zero_budget_req)
        cited=tuple(f.fact_id for f in store2.facts)
        backend=ScriptedThesisBackend([_good_thesis(cited)])
        synthesizer=ThesisSynthesizer(backend,budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=store2)
        result=CommitteeResult(Decision.INVEST,'x',(),store2.revision,1,cited)
        with self.assertRaises(BudgetStopped):
            synthesizer.synthesize(zero_budget_req,context,result)
        self.assertEqual(backend.messages_seen,[])

    def test_rejects_cited_id_beyond_committees_own_citation_scope(self):
        """Model may not expand citation scope beyond the committee's own basis facts."""
        req,store=self._store_with_two_facts()
        budget=CallBudget(req)
        market_id=next(f.fact_id for f in store.facts if f.topic=='market')
        retention_id=next(f.fact_id for f in store.facts if f.topic=='retention')
        backend=ScriptedThesisBackend([_good_thesis([market_id,retention_id])])
        synthesizer=ThesisSynthesizer(backend,budget)
        from closed_loop.runtime import RunContext
        context=RunContext(store=store)
        result=CommitteeResult(Decision.INVEST,'Market only.',(),store.revision,1,(market_id,))
        with self.assertRaisesRegex(BudgetStopped,'THESIS_CITED_OUTSIDE_COMMITTEE_SCOPE'):
            synthesizer.synthesize(req,context,result)



class RuntimeFinishWiringTests(unittest.TestCase):
    def test_finish_identical_when_no_thesis_backend_injected(self):
        result=run_case()
        self.assertEqual(result['decision'],'INVEST')
        self.assertIsNone(result['thesis'])
        self.assertFalse(any(e['event']=='THESIS_SYNTHESIZED' for e in result['trace']))

    def test_thesis_skipped_for_more_diligence_even_when_backend_injected(self):
        calls=[]
        def factory(budget):
            backend=ScriptedThesisBackend([_good_thesis(['unused'])])
            calls.append(backend)
            return ThesisSynthesizer(backend,budget)
        result=run_case(empty=True,thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertIsNone(result['thesis'])
        self.assertEqual(calls[0].scripted,[_good_thesis(['unused'])])  # never consumed

    def test_thesis_attached_citing_only_committee_basis_facts_on_substantive_decision(self):
        captured={}
        def factory(budget):
            def backend_factory(cited_fact_ids):
                backend=ScriptedThesisBackend([_good_thesis(cited_fact_ids)])
                captured['backend']=backend
                return backend
            captured['budget']=budget
            # Deferred: real cited ids known only after the committee runs; use a
            # backend that echoes whatever fact ids it is actually shown.
            class EchoingBackend:
                def generate(self,schema,messages,temperature):
                    import json as _json
                    sys_msg=[m for m in messages if m.role=='system'][0]
                    evidence=_json.loads(sys_msg.content[len(sys_msg.content.split('{',1)[0]):])['evidence']
                    return _good_thesis([row['fact_id'] for row in evidence])
            captured['backend']=EchoingBackend()
            return ThesisSynthesizer(captured['backend'],budget)
        result=run_case(thesis_factory=factory)
        self.assertEqual(result['decision'],'INVEST')
        self.assertIsNotNone(result['thesis'])
        self.assertTrue(result['thesis']['summary'])
        self.assertEqual(set(result['thesis']['cited_fact_ids']),set(result['admitted_fact_ids']))
        self.assertTrue(any(e['event']=='THESIS_SYNTHESIZED' for e in result['trace']))

    def test_final_model_budget_exhaustion_returns_trace_not_exception(self):
        captured=[]
        def factory(budget):
            backend=ScriptedThesisBackend([_good_thesis(['unused'])]);captured.append(backend)
            return ThesisSynthesizer(backend,budget)
        result=run_case(max_model_calls=4,thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'CALL_CAP')
        self.assertIn('final_thesis_unverified',result['essential_gaps'])
        self.assertEqual(len(result['admitted_fact_ids']),2)
        self.assertTrue(any(e['event']=='THESIS_STOPPED' for e in result['trace']))
        self.assertEqual(len(captured[0].messages_seen),0)

    def test_invalid_final_citation_preserves_prior_debate(self):
        captured={}
        def factory(budget):
            captured['budget']=budget
            return ThesisSynthesizer(ScriptedThesisBackend([_good_thesis(['invented'])]),budget)
        result=run_case(thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'THESIS_CITED_UNAVAILABLE_FACT')
        self.assertEqual(captured['budget'].stop_reason,'THESIS_CITED_UNAVAILABLE_FACT')
        self.assertIsNone(result['thesis'])
        self.assertTrue(any(e['event']=='COMMITTEE_REGENERATED' for e in result['trace']))
        self.assertEqual(len(result['admitted_fact_ids']),2)

    def test_empty_final_citations_cannot_approve(self):
        def factory(budget):return ThesisSynthesizer(ScriptedThesisBackend([_good_thesis([])]),budget)
        result=run_case(thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'THESIS_MISSING_CITATIONS')
        self.assertIsNone(result['thesis'])


class EndToEndRegressionScenarioTests(unittest.TestCase):
    """Meaningful offline regression: missing fact -> targeted research -> new
    admissible fact -> recomputed decision -> gated thesis synthesis, plus the
    blocked-future-evidence and budget-stop cases, all reusing the existing
    `fixtures.run_case` committee/provider/lead harness (no new provider/network)."""

    def test_missing_retention_then_targeted_research_recomputes_decision_and_synthesizes(self):
        def factory(budget):
            class EchoingBackend:
                def generate(self,schema,messages,temperature):
                    import json as _json
                    sys_msg=[m for m in messages if m.role=='system'][0]
                    evidence=_json.loads(sys_msg.content[len(sys_msg.content.split('{',1)[0]):])['evidence']
                    return _good_thesis([row['fact_id'] for row in evidence])
            return ThesisSynthesizer(EchoingBackend(),budget)
        result=run_case(good=True,thesis_factory=factory)
        committees=[x for x in result['trace'] if x['event']=='COMMITTEE_REGENERATED']
        # First pass: only market admitted -> MORE_DILIGENCE on missing retention.
        self.assertEqual(committees[0]['proposed_decision'],'MORE_DILIGENCE')
        # Second pass: targeted research admits the retention fact -> recomputed INVEST.
        self.assertEqual(committees[-1]['proposed_decision'],'INVEST')
        self.assertGreater(len(committees[-1]['cited_fact_ids']),len(committees[0]['cited_fact_ids']))
        self.assertEqual(result['decision'],'INVEST')
        self.assertIsNotNone(result['thesis'])
        self.assertEqual(set(result['thesis']['cited_fact_ids']),set(result['admitted_fact_ids']))

    def test_exhausted_research_budget_stays_more_diligence_without_thesis(self):
        calls=[]
        def factory(budget):
            backend=ScriptedThesisBackend([_good_thesis(['unused'])])
            calls.append(backend)
            return ThesisSynthesizer(backend,budget)
        result=run_case(max_search_calls=1,thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertIsNone(result['thesis'])
        self.assertEqual(calls[0].scripted,[_good_thesis(['unused'])])

    def test_already_expired_deadline_stops_before_any_synthesis_attempt(self):
        from closed_loop.fixtures import stamp
        calls=[]
        def factory(budget):
            backend=ScriptedThesisBackend([_good_thesis(['unused'])])
            calls.append(backend)
            return ThesisSynthesizer(backend,budget)
        result=run_case(deadline=stamp('2020-01-01T00:00:00Z'),thesis_factory=factory)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'STOP_OR_DEADLINE')
        self.assertIsNone(result['thesis'])
        self.assertEqual(calls[0].scripted,[_good_thesis(['unused'])])


if __name__=='__main__':unittest.main()
