import importlib.util
import json
from pathlib import Path
import unittest
import test_company_review_export as fixtures

SCRIPT=Path(__file__).parents[1]/'scripts/experiments/audit_pair_usage.py'
spec=importlib.util.spec_from_file_location('pair_usage_audit',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class PairUsageAuditTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.CompanyReviewExportTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.root=self.fx.pair
        plan=json.loads((self.root/'plan.json').read_text());plan['model']='fixture-model'
        arms=json.loads((self.root/'arms.json').read_text())
        for a in arms:a['model_reservations']=1
        for name,value in [('plan.json',plan),('result.json',dict(cli_process_attempts=2)),('arms.json',arms)]:
            raw=json.dumps(value).encode();(self.root/name).write_bytes(raw);self.fx.hashes[name]=m.sha(raw)
        self.fx.receipt.write_text(json.dumps(dict(raw_sha256=self.fx.hashes)))
        events=[json.loads(x) for x in (self.root/'dispatch.jsonl').read_text().splitlines()]
        for event in list(events):
            event['model_id']='fixture-model';event['attempt_id']='fixture-'+str(event['process_count'])
            usage=dict(input_tokens=3,output_tokens=7,cache_creation_input_tokens=10,cache_read_input_tokens=0)
            envelope=dict(is_error=False,usage=usage)
            (self.fx.wire/f"call_{event['process_count']:03d}.stdout").write_text(json.dumps(envelope))
            events.append(dict(event,status='SUCCEEDED',actual_usage=usage))
        self.events=events;self.write_events()
    def write_events(self):
        (self.root/'dispatch.jsonl').write_text('\n'.join(json.dumps(e) for e in self.events))
    def audit(self):return m.audit(self.root,self.fx.receipt)
    def test_complete_counters_reconcile_without_billing_claim(self):
        value=self.audit()
        self.assertEqual([a['observed_cli_attempts'] for a in value['arms']],[1,1])
        self.assertEqual(value['arms'][0]['reported_counter_sums']['output_tokens'],7)
        self.assertEqual(value['amount_charged'],'UNKNOWN')
        self.assertEqual(value['new_model_cli_attempts'],0)
        self.assertFalse(value['independently_authenticated_billing'])
    def test_missing_cache_counter_not_filled_with_zero(self):
        path=self.fx.wire/'call_001.stdout';v=json.loads(path.read_text());del v['usage']['cache_read_input_tokens']
        path.write_text(json.dumps(v));self.events[2]['actual_usage']=v['usage'];self.write_events()
        arm=self.audit()['arms'][0]
        self.assertIsNone(arm['reported_counter_sums']['cache_read_input_tokens'])
        self.assertEqual(arm['counter_coverage']['cache_read_input_tokens'],0)
    def test_conflicting_journal_counter_not_summed(self):
        self.events[2]['actual_usage']['output_tokens']=100;self.write_events()
        with self.assertRaisesRegex(ValueError,'REPORTED_USAGE_MISSING_OR_CONFLICTING'):self.audit()
    def test_failed_envelope_not_counted_as_success(self):
        path=self.fx.wire/'call_001.stdout';v=json.loads(path.read_text());v['is_error']=True
        path.write_text(json.dumps(v))
        with self.assertRaisesRegex(ValueError,'EXPLICIT_SUCCESS_ENVELOPE_REQUIRED'):self.audit()
    def test_duplicate_dispatch_not_double_counted(self):
        original=list(self.events)
        self.events.append(dict(self.events[0]));self.write_events()
        with self.assertRaisesRegex(ValueError,'UNIQUE_COMPLETE_DISPATCHES_REQUIRED'):self.audit()
        for bad in (True,None,'1'):
            self.events=[dict(e) for e in original];self.events[0]['process_count']=bad;self.write_events()
            with self.assertRaisesRegex(ValueError,'UNIQUE_COMPLETE_DISPATCHES_REQUIRED'):self.audit()
    def test_sealed_output_change_detected(self):
        (self.root/'arms.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'SEALED_PAIR_HASH_MISMATCH'):self.audit()
    def test_changed_prompt_detected_before_usage_admission(self):
        (self.fx.wire/'call_001.stdin').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'PROMPT_HASH_MISMATCH'):self.audit()


if __name__=='__main__':unittest.main()
