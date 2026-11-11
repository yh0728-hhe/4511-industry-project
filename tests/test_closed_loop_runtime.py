"""Adversarial behavior tests for the offline prototype, not real predictions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.contracts import CompanySeed, Decision, ResearchRequest
from closed_loop.fixtures import request, source, stamp, run_case, FixtureLead, FixtureCommittee, FixtureProvider
from closed_loop.guards import BudgetStopped, CallBudget, TemporalGateway, WorkspaceReader
from closed_loop.runtime import ClosedLoopRuntime, FactStore, committee_input


class TemporalTests(unittest.TestCase):
    def check(self, candidate, record):
        return TemporalGateway(request(),{candidate.source_id:record}).admit(candidate)

    def test_readable_matching_archive_is_admitted(self):
        candidate,record=source('archive','traction','historical snippet')
        fact,rejection=self.check(candidate,record)
        self.assertIsNone(rejection)
        self.assertEqual(fact.text,'historical snippet')
        self.assertEqual(fact.availability_upper_bound,record.served_capture)

    def test_cdx_without_body_is_not_evidence(self):
        candidate,record=source('index-only','traction','unread body',body_read=False)
        self.assertEqual(self.check(candidate,record)[1]['reason'],'BODY_NOT_VERIFIED')

    def test_archive_substitution_rejected(self):
        candidate,record=source('wrong-replay','traction','text',served_capture=stamp('2024-03-21T00:00:00Z'))
        self.assertEqual(self.check(candidate,record)[1]['reason'],'SUBSTITUTED_CAPTURE')

    def test_missing_replay_capture_is_held(self):
        candidate,record=source('no-replay','team','unread capture',served_capture=None)
        self.assertEqual(self.check(candidate,record)[1]['reason'],'MISSING_CAPTURE_PROOF')

    def test_shared_raw_source_ids_are_namespaced_in_ledger(self):
        candidate,record=source('shared','team','target evidence')
        peer_candidate=replace(candidate,company_id='PEER')
        peer_record=replace(record,company_id='PEER')
        gateway=TemporalGateway(request(),[record,peer_record])
        self.assertIsNotNone(gateway.admit(candidate)[0])
        self.assertIsNotNone(gateway.admit(peer_candidate,subject_id='PEER')[0])
        self.assertIsNone(gateway.admit(peer_candidate)[0])

    def test_current_page_founding_date_does_not_establish_availability(self):
        candidate,_=source('founded-2023','team','Founded in 2023')
        fact,rejection=TemporalGateway(request(),{}).admit(candidate)
        self.assertIsNone(fact)
        self.assertEqual(rejection['reason'],'UNVERIFIED_SOURCE')

    def test_future_outcome_and_url_never_appear_in_rejection(self):
        candidate,record=source('FUTURE_SECRET_2025_FUNDING','funding','SECRET_OUTCOME_10M','2025-01-01T00:00:00Z')
        fact,rejection=self.check(candidate,record)
        self.assertIsNone(fact)
        text=json.dumps(rejection)
        self.assertNotIn('SECRET',text);self.assertNotIn(candidate.url,text)

    def test_old_url_updated_content_fails_hash_binding(self):
        candidate,record=source('2020/article','market','old body')
        self.assertEqual(self.check(replace(candidate,text='updated future facts'),record)[1]['reason'],'CONTENT_MISMATCH')

    def test_same_name_other_entity_does_not_match(self):
        candidate,record=source('same-name','team','other company')
        candidate=replace(candidate,company_id='OTHER')
        self.assertIsNone(self.check(candidate,record)[0])

    def test_old_relevant_founder_history_has_no_one_year_floor(self):
        candidate,record=source('founder-2020','team','historical founder evidence','2020-01-01T00:00:00Z')
        self.assertIsNotNone(self.check(candidate,record)[0])

    def test_naive_date_cannot_bypass_cutoff(self):
        candidate,record=source('undated','team','unverified date',availability_upper_bound=datetime(2024,1,1))
        self.assertEqual(self.check(candidate,record)[1]['reason'],'UNVERIFIED_DATE')

    def test_source_type_cannot_self_certify(self):
        candidate,record=source('self-verified','team','asserted fact',proof_kind='LLM_VERIFIED_TRUE')
        self.assertEqual(self.check(candidate,record)[1]['reason'],'UNSUPPORTED_PROOF')

    def test_peer_company_history_requires_requested_subject_and_stays_labeled(self):
        candidate,record=source('peer-company','traction','Peer retention, not target retention')
        candidate=replace(candidate,company_id='PEER')
        record=replace(record,company_id='PEER')
        gateway=TemporalGateway(request(),{candidate.source_id:record})
        self.assertIsNone(gateway.admit(candidate)[0])
        fact,rejection=gateway.admit(candidate,subject_id='PEER')
        self.assertIsNone(rejection)
        store=FactStore();store.merge([fact])
        view=committee_input(request(),store,1)
        self.assertEqual(view.qa_pairs[0]['subject_id'],'PEER')
        self.assertIn('PEER',view.qa_pairs[0]['question'])

    def test_qa_row_carries_gateway_verified_reliability_tier_not_a_fabricated_score(self):
        candidate,record=source('reliability-check','traction','reliability-bearing fact')
        gateway=TemporalGateway(request(),{candidate.source_id:record})
        fact,rejection=gateway.admit(candidate)
        self.assertIsNone(rejection)
        store=FactStore();store.merge([fact])
        view=committee_input(request(),store,1)
        self.assertEqual(view.qa_pairs[0]['reliability'],'READABLE_ARCHIVE')
        self.assertEqual(view.qa_pairs[0]['reliability'],fact.proof_kind)


class ContractAndCacheTests(unittest.TestCase):
    def test_modern_profile_fields_forbidden_in_seed(self):
        seed=dict(company_id='S',name='S',domain='synthetic.example',funding_total=10,description='2026 product')
        with self.assertRaises(ValueError):CompanySeed.from_dict(seed)

    def test_required_inputs_no_company_demo_or_naive_cutoff_fallback(self):
        for updates in ({'mandate':''},{'as_of':datetime(2024,4,4)},{'company':None},{'max_search_calls':True}):
            with self.subTest(updates=updates),self.assertRaises(ValueError):request(**updates)

    def test_malformed_seed_domains_rejected(self):
        for domain in ('a..com','-a.com','a-.com','a/b.com','http://a.com','127.0.0.1'):
            with self.subTest(domain=domain),self.assertRaises(ValueError):CompanySeed('S','S',domain)

    def test_cache_separates_context_and_company(self):
        baseline=request();key=baseline.cache_key('traction','retention')
        variants=[replace(baseline,as_of=baseline.as_of-timedelta(days=1)),
            replace(baseline,mandate='Different mandate'),replace(baseline,source_policy='v2'),
            replace(baseline,model_version='m2'),replace(baseline,prompt_version='p2'),
            replace(baseline,company=CompanySeed('OTHER','Other','other.example'))]
        for variant in variants:self.assertNotEqual(variant.cache_key('traction','retention'),key)

    def test_equivalent_utc_instant_uses_same_cache_context(self):
        req=request();other=replace(req,as_of=req.as_of.astimezone(timezone(timedelta(hours=-5))))
        self.assertEqual(req.cache_key('market','q'),other.cache_key('market','q'))

    def test_peer_research_cache_does_not_collide_under_same_question(self):
        req=request()
        self.assertNotEqual(req.cache_key('competition','retention','PEER_A'),req.cache_key('competition','retention','PEER_B'))


class BudgetTests(unittest.TestCase):
    def test_parallel_reservations_cannot_overspend_last_call(self):
        budget=CallBudget(request(max_model_calls=1,concurrency=8));barrier=Barrier(8)
        def attempt(_):
            barrier.wait(timeout=3)
            try:
                with budget.reserve('model'):return True
            except BudgetStopped:return False
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(attempt,range(8)))
        self.assertEqual(sum(results),1)
        self.assertEqual(budget.snapshot()['used']['model'],1)

    def test_failed_attempt_and_retry_remain_counted(self):
        budget=CallBudget(request(max_search_calls=1))
        with self.assertRaises(RuntimeError):
            with budget.reserve('search'):raise RuntimeError('retrieval failed')
        with self.assertRaises(BudgetStopped):
            with budget.reserve('search'):pass
        self.assertEqual(budget.active,0)

    def test_concurrency_is_independent_of_total_call_cap(self):
        budget=CallBudget(request(concurrency=1))
        with budget.reserve('search'):
            with self.assertRaises(BudgetStopped):
                with budget.reserve('model'):pass
        self.assertEqual(budget.used['model'],0)
        with budget.reserve('model'):pass
        self.assertEqual(budget.used['model'],1)

    def test_deadline_or_stop_prevents_dispatch(self):
        req=request();budget=CallBudget(req,clock=lambda:req.deadline)
        with self.assertRaises(BudgetStopped):
            with budget.reserve('model'):pass
        self.assertEqual(budget.used['model'],0)
        budget=CallBudget(req);budget.stop()
        with self.assertRaises(BudgetStopped):budget.check()


class WorkspaceTests(unittest.TestCase):
    def test_outcome_and_traversal_and_absolute_paths_denied(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);(root/'notes.txt').write_text('allowed historical notes')
            (root/'funding_events.csv').write_text('SECRET_OUTCOME')
            reader=WorkspaceReader(root,allowed=['notes.txt'])
            self.assertEqual(reader.read('notes.txt'),'allowed historical notes')
            for name in ('funding_events.csv','../funding_events.csv',str(root/'funding_events.csv')):
                with self.subTest(name=name),self.assertRaises(PermissionError):reader.read(name)

    def test_symlink_escape_is_denied_when_os_allows_creation(self):
        with TemporaryDirectory() as folder,TemporaryDirectory() as other:
            root=Path(folder);target=Path(other)/'outcome.csv';target.write_text('SECRET_OUTCOME')
            try:(root/'notes.txt').symlink_to(target)
            except OSError as exc:self.skipTest('OS disallows creating symlink: '+type(exc).__name__)
            with self.assertRaises(PermissionError):WorkspaceReader(root,['notes.txt']).read('notes.txt')


class LoopTests(unittest.TestCase):
    def test_new_evidence_reaches_regenerated_committee(self):
        result=run_case()
        self.assertEqual(result['decision'],'INVEST')
        committees=[x for x in result['trace'] if x['event']=='COMMITTEE_REGENERATED']
        self.assertEqual(len(committees),2)
        self.assertGreater(committees[1]['fact_revision'],committees[0]['fact_revision'])
        self.assertGreater(len(committees[1]['cited_fact_ids']),len(committees[0]['cited_fact_ids']))
        self.assertEqual({x['role'] for x in result['trace'] if x['event']=='RESEARCH'},{'market','traction'})

    def test_all_three_decisions_and_missing_is_not_negative(self):
        self.assertEqual(run_case()['decision'],'INVEST')
        self.assertEqual(run_case(good=False)['decision'],'PASS')
        missing=run_case(empty=True)
        self.assertEqual(missing['decision'],'MORE_DILIGENCE')
        self.assertEqual(missing['stop_reason'],'NO_NEW_EVIDENCE')
        self.assertEqual(missing['essential_gaps'],['retention'])

    def test_exhausted_budget_does_not_force_pass(self):
        result=run_case(max_search_calls=2)
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['logical_call_budget']['used']['search'],2)
        self.assertEqual(result['actual_model_calls'],0)

    def test_already_expired_run_returns_structured_stop_without_dispatch(self):
        result=run_case(deadline=stamp('2020-01-01T00:00:00Z'))
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'STOP_OR_DEADLINE')
        self.assertEqual(result['logical_call_budget']['used'],{'model':0,'search':0})

    def test_invest_with_essential_gap_is_explicitly_overridden(self):
        class Inconsistent(FixtureCommittee):
            def evaluate(self,view):
                return replace(super().evaluate(view),decision=Decision.INVEST,essential_gaps=('retention',))
        req=request();provider=FixtureProvider(empty=True)
        result=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),FixtureLead(),Inconsistent(),provider).run()
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertTrue(any(x['event']=='COMMITTEE_GAP_OVERRIDE' for x in result['trace']))

    def test_stale_revision_refused(self):
        class Stale(FixtureCommittee):
            def evaluate(self,view):return replace(super().evaluate(view),fact_revision=999)
        req=request();provider=FixtureProvider()
        runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),FixtureLead(),Stale(),provider)
        with self.assertRaisesRegex(ValueError,'stale'):runtime.run()

    def test_duplicate_fact_does_not_advance_revision(self):
        candidate,record=source('stable','market','unchanged')
        fact,_=TemporalGateway(request(),{'stable':record}).admit(candidate)
        store=FactStore();self.assertTrue(store.merge([fact]));rev=store.revision
        self.assertFalse(store.merge([fact]));self.assertEqual(store.revision,rev)
        view=committee_input(request(),store,1)
        self.assertEqual(view.qa_pairs[0]['answer'],'unchanged')
        self.assertEqual(view.qa_pairs[0]['fact_id'],fact.fact_id)

    def test_changed_source_supersedes_old_fact_with_explicit_revision_event(self):
        old,old_record=source('same-source','market','old verified body')
        new,new_record=source('same-source','market','corrected verified body')
        a,_=TemporalGateway(request(),[old_record]).admit(old)
        b,_=TemporalGateway(request(),[new_record]).admit(new)
        store=FactStore();store.merge([a]);store.merge([b])
        self.assertEqual(store.revision,2)
        self.assertEqual(store.facts,(b,))
        self.assertEqual(store.last_changes[0],dict(event='SOURCE_CONTENT_REVISED',old_fact_id=a.fact_id,new_fact_id=b.fact_id))

    def test_two_companies_reusing_source_id_both_survive_fact_store(self):
        candidate,record=source('common','team','history')
        a,_=TemporalGateway(request(),[record]).admit(candidate)
        store=FactStore();store.merge([a,replace(a,company_id='OTHER',fact_id='OTHER_ID')])
        self.assertEqual(len(store.facts),2)

    def test_peer_retention_not_substituted_for_target_retention(self):
        candidate,record=source('peer','retention','SYNTHETIC_RETENTION_GOOD')
        candidate=replace(candidate,company_id='PEER');record=replace(record,company_id='PEER')
        fact,_=TemporalGateway(request(),{'peer':record}).admit(candidate,subject_id='PEER')
        store=FactStore();store.merge([fact])
        result=FixtureCommittee().evaluate(committee_input(request(),store,1))
        self.assertEqual(result.decision,Decision.MORE_DILIGENCE)
        self.assertEqual(result.essential_gaps,('retention',))

    def test_cached_source_is_revalidated_not_blindly_trusted(self):
        req=request();provider=FixtureProvider();cache={}
        runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),FixtureLead(),FixtureCommittee(),provider,cache)
        self.assertEqual(runtime.run()['decision'],'INVEST')
        # A revoked/invalid proof cannot survive through previously admitted cache entries.
        gateway=TemporalGateway(req,{})
        result=ClosedLoopRuntime(req,gateway,CallBudget(req),FixtureLead(),FixtureCommittee(),provider,cache).run()
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['admitted_fact_ids'],[])
        rejected=[x for x in result['trace'] if x['event']=='CACHED_SOURCE_HELD']
        self.assertTrue(rejected)
        self.assertNotIn('synthetic.example',json.dumps(rejected))
        self.assertNotIn('SYNTHETIC_RETENTION',json.dumps(rejected))

    def test_full_runs_with_shared_cache_never_mix_companies(self):
        cache={};results=[]
        for company_id in ('SYNTHETIC_COMPANY','OTHER_COMPANY'):
            req=request(company=CompanySeed(company_id,'Synthetic','synthetic.example'))
            provider=FixtureProvider()
            provider.market=replace(provider.market,company_id=company_id)
            provider.retention=replace(provider.retention,company_id=company_id)
            provider.ledger={r.source_id:replace(r,company_id=company_id) for r in provider.ledger.values()}
            result=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),FixtureLead(),FixtureCommittee(),provider,cache).run()
            self.assertEqual(result['decision'],'INVEST')
            self.assertFalse(any(x.get('cache_hit') for x in result['trace']))
            results.append(set(result['admitted_fact_ids']))
        self.assertFalse(results[0]&results[1])


if __name__=='__main__':unittest.main()
