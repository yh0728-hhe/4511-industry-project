"""Offline corruption tests; no model/network or company outcome files."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.saved_run_audit import audit_run,main,CONSISTENT,INCONSISTENT

class SavedRunAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'run';self.root.mkdir()
        self.plan=dict(max_model_calls=4,max_search_reservations=6)
        self.proposal=dict(decision='MORE_DILIGENCE',stop_reason='NO_ADMITTED_FACTS',admitted_fact_ids=[],thesis=None)
        self.result=dict(self.proposal,status='DISCOVERY_RUNTIME_EXECUTED',proposed_decision='MORE_DILIGENCE',
            acceptance=dict(decision='MORE_DILIGENCE'),logical_call_budget=dict(caps=dict(model=4,search=6),used=dict(model=2,search=3),active=0),
            backend_process_attempts=1,managed_discovery_process_attempts=1,direct_archive_http_attempts=2,
            Y_changed=False,training_run=False,predictive_accuracy_evaluated=False,semantic_support_certified=False)
        self.trace=[];self.save()
    def save(self):
        p=copy.deepcopy(self.plan);p['fingerprint']=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest()
        for name,value in (('plan.json',p),('result.json',self.result),('proposal.json',self.proposal),('committee_trace.json',self.trace)):
            (self.root/name).write_text(json.dumps(value),encoding='utf-8')
    def codes(self):return {f['code'] for f in audit_run(self.root)['findings']}
    def test_valid_sparse_and_input_hashes(self):
        out=audit_run(self.root);self.assertEqual(out['status'],CONSISTENT);self.assertEqual(len(out['input_sha256']),4)
    def test_source_rich_uses_stage_revision_not_final_fact_ids(self):
        self.proposal['admitted_fact_ids']=['new'];self.result['admitted_fact_ids']=['new']
        self.trace=[dict(qa_fact_ids=['old'],arguments=[dict(cited_fact_ids=['old'])])];self.save()
        self.assertEqual(audit_run(self.root)['status'],CONSISTENT)
    def test_missing_required(self):
        (self.root/'result.json').unlink();self.assertIn('MISSING_REQUIRED_FILE',self.codes())
    def test_malformed_json(self):
        (self.root/'result.json').write_text('{SECRET',encoding='utf-8')
        self.assertNotIn('SECRET',json.dumps(audit_run(self.root)));self.assertIn('MALFORMED_JSON',self.codes())
    def test_duplicate_key_rejected(self):
        (self.root/'result.json').write_text('{"x":1,"x":2}',encoding='utf-8');self.assertIn('MALFORMED_JSON',self.codes())
    def test_nonfinite_rejected(self):
        (self.root/'result.json').write_text('{"x":NaN}',encoding='utf-8');self.assertIn('MALFORMED_JSON',self.codes())
    def test_null_result_rejected(self):
        (self.root/'result.json').write_text('null',encoding='utf-8');self.assertIn('RESULT_NOT_OBJECT',self.codes())
    def test_plan_hash_mismatch(self):
        p=json.loads((self.root/'plan.json').read_text());p['max_model_calls']=5
        (self.root/'plan.json').write_text(json.dumps(p),encoding='utf-8');self.assertIn('PLAN_FINGERPRINT_MISMATCH',self.codes())
    def test_bool_counts_and_active_are_rejected(self):
        self.result['logical_call_budget']['used']['model']=True;self.result['logical_call_budget']['active']=False
        self.save();self.assertIn('USED_MODEL_NOT_NONNEGATIVE_INT',self.codes());self.assertIn('ACTIVE_RESERVATION_NOT_ZERO',self.codes())
    def test_bool_cap_rejected_even_equal_integer(self):
        self.plan['max_model_calls']=1;self.result['logical_call_budget']['caps']['model']=True
        self.save();self.assertIn('MODEL_CAP_MISMATCH',self.codes())
    def test_observed_bool_is_not_unknown(self):
        self.result['backend_process_attempts']=True;self.save();self.assertIn('INVALID_OBSERVED_COUNT',self.codes())
    def test_exceeded_cap(self):
        self.result['logical_call_budget']['used']['model']=5;self.save();self.assertIn('USED_MODEL_EXCEEDS_CAP',self.codes())
    def test_observed_process_count_exceeded(self):
        self.result['backend_process_attempts']=3;self.result['direct_archive_http_attempts']=4
        self.save();self.assertIn('OBSERVED_MODEL_PROCESSES_EXCEED_USED',self.codes());self.assertIn('OBSERVED_SEARCH_PROCESSES_EXCEED_USED',self.codes())
    def test_null_observed_counts_remain_unknown(self):
        self.result['backend_process_attempts']=None;self.save();self.assertEqual(audit_run(self.root)['status'],CONSISTENT)
    def test_acceptance_disagreement(self):
        self.result['acceptance']['decision']='INVEST';self.save();self.assertIn('ACCEPTANCE_DECISION_MISMATCH',self.codes())
    def test_success_requires_proposal(self):
        (self.root/'proposal.json').unlink();self.assertIn('MISSING_PROPOSAL_FOR_EXECUTED',self.codes())
    def test_success_requires_saved_committee_trace(self):
        (self.root/'committee_trace.json').unlink();self.assertIn('MISSING_COMMITTEE_TRACE_FOR_EXECUTED',self.codes())
    def test_stage_citation_outside_available_ids(self):
        self.trace=[dict(qa_fact_ids=['a'],arguments=[dict(cited_fact_ids=['b'])])];self.save()
        self.assertIn('CITATION_NOT_SUBSET_OF_STAGE_FACTS',self.codes())
    def test_zero_facts_cannot_have_substantive_proposal(self):
        self.result.update(decision='INVEST',thesis={'summary':'unsupported'})
        self.save();self.assertIn('ZERO_FACTS_SUBSTANTIVE_DECISION',self.codes());self.assertIn('ZERO_FACTS_SUBSTANTIVE_THESIS',self.codes())
    def test_failed_run_without_acceptance_or_proposal_allowed(self):
        self.result['status']='DISCOVERY_RUNTIME_FAILED';self.result.pop('acceptance');self.save()
        (self.root/'proposal.json').unlink();self.assertEqual(audit_run(self.root)['status'],CONSISTENT)
    def test_prohibited_flags(self):
        self.result['semantic_support_certified']=True;self.save();self.assertIn('PROHIBITED_FLAG_TRUE',self.codes())
    def test_cli_refuses_write_inside_run(self):
        self.assertEqual(main(['--run-dir',str(self.root),'--output',str(self.root/'audit.json')]),2)
        self.assertFalse((self.root/'audit.json').exists())
    def test_cli_exclusive_outside_output_and_immutable_inputs(self):
        before={f.name:f.read_bytes() for f in self.root.iterdir()};out=self.base/'audit.json'
        self.assertEqual(main(['--run-dir',str(self.root),'--output',str(out)]),0)
        self.assertEqual(main(['--run-dir',str(self.root),'--output',str(out)]),2)
        self.assertEqual(before,{f.name:f.read_bytes() for f in self.root.iterdir()})
    def test_failed_run_cannot_accept_substantive_decision(self):
        self.result.update(status='DISCOVERY_RUNTIME_FAILED',decision='INVEST',acceptance={'decision':'INVEST'})
        self.save();self.assertIn('TERMINAL_FAILURE_SUBSTANTIVE_RESULT',self.codes())
    def test_missing_stage_available_ids_does_not_skip_citation_check(self):
        self.trace=[dict(arguments=[dict(cited_fact_ids=['unknown'])])];self.save()
        self.assertIn('MALFORMED_COMMITTEE_TRACE_ENTRY',self.codes())
    def test_missing_citation_field_is_not_silent_success(self):
        self.trace=[dict(arguments=[dict(text='claim')],qa_fact_ids=['a'])];self.save()
        self.assertIn('MALFORMED_COMMITTEE_TRACE_ENTRY',self.codes())
    def test_missing_fact_lists_in_success_rejected(self):
        self.result.pop('admitted_fact_ids');self.proposal.pop('admitted_fact_ids');self.save()
        self.assertIn('MISSING_EXECUTED_FACT_LIST',self.codes())
    def test_gated_substantive_proposal_without_facts_still_flagged(self):
        self.proposal['decision']='INVEST';self.result['proposed_decision']='INVEST';self.save()
        self.assertIn('UNSUPPORTED_SUBSTANTIVE_PROPOSAL',self.codes())

    def test_unknown_status_rejected(self):
        self.result['status']='invented';self.save();self.assertIn('INVALID_RUN_STATUS',self.codes())
if __name__=='__main__':unittest.main()
