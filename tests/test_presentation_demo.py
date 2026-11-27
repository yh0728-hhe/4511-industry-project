"""Demo provenance/determinism checks; never call models or external sources."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workflow_automation import presentation_demo as d


class PresentationDemoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)

    def test_two_builds_byte_identical_and_manifest_matches(self):
        a=self.folder/'one';b=self.folder/'two'
        d.build(a);d.build(b)
        self.assertEqual(sorted(p.name for p in a.iterdir()),sorted(p.name for p in b.iterdir()))
        for p in a.iterdir():self.assertEqual(p.read_bytes(),(b/p.name).read_bytes())
        manifest=json.loads((a/'manifest.json').read_text())
        for n,h in manifest['artifact_sha256'].items():
            self.assertEqual(hashlib.sha256((a/n).read_bytes()).hexdigest(),h)

    def test_existing_output_preserved(self):
        out=self.folder/'demo';out.mkdir();(out/'keep').write_text('original')
        with self.assertRaises(ValueError):d.build(out)
        self.assertEqual((out/'keep').read_text(),'original')

    def test_generation_failure_leaves_no_partial_output(self):
        out=self.folder/'demo'
        with patch.object(d,'collect',side_effect=ValueError('bad receipt')):
            with self.assertRaises(ValueError):d.build(out)
        self.assertFalse(out.exists())

    def test_guard_blocks_network_inside_collector(self):
        import socket
        def bad(root):socket.getaddrinfo('not-allowed.example',443)
        with patch.object(d,'collect',side_effect=bad):
            with self.assertRaises(PermissionError):d.build(self.folder/'demo')

    def test_output_distinguishes_saved_real_run_from_synthetic(self):
        out=self.folder/'demo';d.build(out)
        summary=json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['prior_real_cli_handoff']['classification'],'SAVED_HISTORICAL_RECEIPT_NOT_RERUN_NOW')
        self.assertEqual(summary['generated_now'],{'actual_model_calls':0,'network_calls':0,'training':False})
        self.assertEqual(summary['coverage']['composite_observed'],164)
        score=json.loads((out/'synthetic_scoring_example.json').read_text())
        self.assertEqual(score['classification'],'SYNTHETIC_INJECTED_ERROR_NOT_MODEL_OUTPUT')
        self.assertEqual(score['report']['metrics']['structural_citation_precision']['rate'],0.5)

    def test_html_escapes_dynamic_fields(self):
        summary={'coverage':{'composite_observed':164,'financing_observed':153,'verified_financing_negatives':0},
                 'historical_gate':'<script>bad</script>'}
        page=d.render(summary,{'<script>x</script>':{'decision':'PASS','stop_reason':'<svg>','fact_revision':1}})
        self.assertNotIn('<script>',page);self.assertIn('&lt;script&gt;',page)

    def test_plausible_but_changed_receipt_rejected(self):
        original=Path.read_bytes
        def altered(path):
            raw=original(path)
            if path.as_posix().endswith(d.INPUTS[0]):
                value=json.loads(raw);value['run_id']='invented-but-still-DONE'
                return json.dumps(value).encode()
            return raw
        with patch.object(Path,'read_bytes',altered):
            with self.assertRaisesRegex(ValueError,'pinned'):d.collect(d.ROOT)

    def test_new_directory_under_source_tree_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with self.assertRaisesRegex(ValueError,'source'):d.build(root/'tests'/'new-demo',root=root)


if __name__=='__main__':unittest.main()
