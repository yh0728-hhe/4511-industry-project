import hashlib
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SCRIPT=Path(__file__).parents[1]/'scripts/experiments/prepare_company_review.py'
spec=importlib.util.spec_from_file_location('company_review_export',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class CompanyReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.pair=self.base/'sealed';self.pair.mkdir()
        self.wire=self.pair/'backend_wire';self.wire.mkdir();self.out=self.base/'review'
        self.context=dict(as_of='2024-04-04T23:59:59+00:00',mandate='Fixture mandate',
            evidence=[dict(fact_id='f1',answer='The publisher claims feature A.',source_id='s1')])
        plan=dict(as_of=self.context['as_of'],mandate=self.context['mandate'],evidence_sha256='fixture-sha')
        arms=[dict(arm=arm,status='EXECUTED_REVIEW_PENDING',evidence_sha256='fixture-sha',
            proposal=dict(rationale='Fixture rationale '+arm,admitted_fact_ids=['f1']))
            for arm in ('single_analyst','committee')]
        trace=[dict(stage='final_aggregation',arguments=[dict(text='Fixture argument '+role,
            cited_fact_ids=['f1'],role=role) for role in ('pro','contra')])]
        data={'plan.json':plan,'arms.json':arms,'result.json':{},
            'committee_draft_trace.json':trace,'single_analyst_raw.json':{}}
        self.hashes={}
        for name,value in data.items():
            raw=json.dumps(value).encode();(self.pair/name).write_bytes(raw)
            self.hashes[name]=hashlib.sha256(raw).hexdigest()
        self.receipt=self.base/'receipt.json';self.receipt.write_text(json.dumps(dict(raw_sha256=self.hashes)))
        self.write_wires()
    def write_wires(self,second=None):
        events=[]
        for n,ctx in [(1,self.context),(2,second or self.context)]:
            raw=('system: fixture\n'+json.dumps(ctx)+'\n\nuser: fixture').encode()
            (self.wire/f'call_{n:03d}.stdin').write_bytes(raw)
            events.append(dict(status='DISPATCHING',process_count=n,prompt_hash=m.sha(raw)))
        (self.pair/'dispatch.jsonl').write_text('\n'.join(json.dumps(x) for x in events))
    def run_export(self,**kwargs):
        return m.prepare(self.pair,self.receipt,kwargs.pop('out',self.out),mask_seed=kwargs.pop('seed',42))
    def test_exports_all_four_units_without_agent_generated_reference(self):
        result=self.run_export()
        self.assertEqual(result['passage_count'],4);self.assertEqual(result['case_count'],1)
        self.assertFalse(result['reference_labels_created']);self.assertIsNone(result['quality_score'])
        self.assertEqual(result['model_cli_attempts'],0)
        review=json.loads((self.out/'reviewer/outputs_second.json').read_text())
        self.assertEqual([x['verdict'] for x in review['units']],[None]*4)
        self.assertTrue(all('origin' not in x for x in review['units']))
        reference=json.loads((self.out/'reviewer/reference_first.json').read_text())
        self.assertEqual(reference['source_only_reference_claims'],[])
        self.assertIsNone(reference['reviewer_independent_of_generation'])
        self.assertEqual(len(json.loads((self.out/'operator/arm_mapping.json').read_text())),4)
    def test_modified_sealed_output_rejected_before_creating_packet(self):
        (self.pair/'arms.json').write_text('[]')
        with self.assertRaisesRegex(ValueError,'SEALED_INPUT_HASH_MISMATCH'):self.run_export()
        self.assertFalse(self.out.exists())
    def test_modified_wire_rejected(self):
        (self.wire/'call_001.stdin').write_text('changed')
        with self.assertRaisesRegex(ValueError,'WIRE_HASH_MISMATCH'):self.run_export()
        self.assertFalse(self.out.exists())
    def test_different_model_visible_context_even_with_matching_wire_hash_rejected(self):
        self.write_wires(dict(self.context,mandate='DIFFERENT'))
        with self.assertRaisesRegex(ValueError,'MODEL_VISIBLE_CONTEXTS_DIFFER'):self.run_export()
        self.assertFalse(self.out.exists())
    def test_existing_reviewer_work_never_overwritten(self):
        self.out.mkdir();(self.out/'human-work.txt').write_text('keep')
        with self.assertRaises(FileExistsError):self.run_export()
        self.assertEqual((self.out/'human-work.txt').read_text(),'keep')
    def test_explicit_mask_seed_and_deterministic_output(self):
        for bad in (True,-1,2**32):
            with self.assertRaises(ValueError):self.run_export(seed=bad)
        first=self.run_export();other=self.base/'other'
        second=self.run_export(out=other)
        self.assertEqual(first,second)
    def test_manifest_hashes_match_written_files_and_inputs_remain_untouched(self):
        result=self.run_export()
        for name,expected in result['files_sha256'].items():
            self.assertEqual(m.sha((self.out/name).read_bytes()),expected)
        for name,expected in self.hashes.items():
            self.assertEqual(m.sha((self.pair/name).read_bytes()),expected)
    def test_duplicate_or_partial_arm_not_exported_as_complete(self):
        arms=json.loads((self.pair/'arms.json').read_text());arms[0]['status']='STOPPED_NO_RETRY'
        raw=json.dumps(arms).encode();(self.pair/'arms.json').write_bytes(raw)
        self.hashes['arms.json']=m.sha(raw)
        self.receipt.write_text(json.dumps(dict(raw_sha256=self.hashes)))
        with self.assertRaisesRegex(ValueError,'INCOMPLETE_PAIR'):self.run_export()
        self.assertFalse(self.out.exists())


if __name__=='__main__':unittest.main()
