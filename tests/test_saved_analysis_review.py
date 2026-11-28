import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from closed_loop.saved_analysis_review import review_saved_run,main
from closed_loop.analysis_acceptance import build_analysis_review_packet
from test_analysis_acceptance import make_result,make_full_review


class SavedAnalysisReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'run';self.source.mkdir()
        self.target=self.root/'review'
        self.plan={'status':'SOURCE_ADMITTED_BEFORE_MODEL_CONSTRUCTION','source_sha256':'fixture'}
        self.plan['fingerprint']=hashlib.sha256(json.dumps(self.plan,sort_keys=True).encode()).hexdigest()
        self.result=make_result()
        self.write('plan.json',self.plan);self.write('proposal.json',self.result)

    def write(self,name,value):
        (self.source/name).write_text(json.dumps(value),encoding='utf-8')

    def test_export_is_offline_and_preserves_source_bytes(self):
        before={p.name:p.read_bytes() for p in self.source.iterdir()}
        out=review_saved_run(self.source,self.target)
        self.assertEqual(out['acceptance']['decision'],'MORE_DILIGENCE')
        self.assertEqual(out['acceptance']['acceptance_state'],'NOT_REVIEWED')
        self.assertEqual(out['model_calls'],0);self.assertEqual(out['network_calls'],0)
        self.assertFalse(out['review_validated'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.source.iterdir()})

    def test_complete_review_works_without_rerun(self):
        packet=build_analysis_review_packet(self.result,self.plan['fingerprint'])
        review_file=self.root/'supplied.json';review_file.write_text(json.dumps(make_full_review(packet)))
        out=review_saved_run(self.source,self.target,review_path=review_file)
        self.assertEqual(out['acceptance']['decision'],'INVEST')
        self.assertTrue(out['review_validated'])
        self.assertFalse(out['semantic_support_certified'])

    def test_partial_review_stays_blocked(self):
        packet=build_analysis_review_packet(self.result,self.plan['fingerprint'])
        review=make_full_review(packet);review['items'].pop()
        review_file=self.root/'partial.json';review_file.write_text(json.dumps(review))
        out=review_saved_run(self.source,self.target,review_path=review_file)
        self.assertEqual(out['acceptance']['decision'],'MORE_DILIGENCE')
        self.assertEqual(out['acceptance']['acceptance_state'],'INVALID_REVIEW')

    def test_changed_plan_rejected_before_output(self):
        self.plan['source_sha256']='changed';self.write('plan.json',self.plan)
        with self.assertRaises(ValueError):review_saved_run(self.source,self.target)
        self.assertFalse(self.target.exists())

    def test_no_automatic_legacy_fallback(self):
        (self.source/'proposal.json').rename(self.source/'result.json')
        with self.assertRaises(ValueError):review_saved_run(self.source,self.target)
        out=review_saved_run(self.source,self.target,proposal_name='result.json')
        self.assertTrue(out['legacy_source_explicit'])

    def test_gated_result_not_mistaken_for_original(self):
        self.result['proposed_decision']='INVEST';self.write('proposal.json',self.result)
        with self.assertRaises(ValueError):review_saved_run(self.source,self.target)

    def test_existing_output_cannot_be_overwritten(self):
        review_saved_run(self.source,self.target)
        before=(self.target/'review_result.json').read_bytes()
        with self.assertRaises(ValueError):review_saved_run(self.source,self.target)
        self.assertEqual(before,(self.target/'review_result.json').read_bytes())

    def test_source_directory_cannot_receive_review_files(self):
        with self.assertRaises(ValueError):review_saved_run(self.source,self.source/'review')
        self.assertFalse((self.source/'review').exists())

    def test_duplicate_json_keys_and_nan_rejected(self):
        for text in ['{"decision":"INVEST","decision":"PASS"}', '{"x":NaN}']:
            (self.source/'proposal.json').write_text(text)
            with self.assertRaisesRegex(ValueError,'INVALID_SAVED_REVIEW_INPUT'):
                review_saved_run(self.source,self.target)

    def test_cli_failure_is_explicit(self):
        self.assertEqual(main(['--run-dir',str(self.source),'--output-dir',str(self.source)]),2)


if __name__=='__main__':unittest.main()
