"""Offline operator handoff tests; fixtures are invented and never real evidence."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from test_commoncrawl_record import fixture, COLLECTION

SPEC = importlib.util.spec_from_file_location('inspect_archive_bundle',
    Path(__file__).resolve().parents[1] / 'scripts/experiments/inspect_archive_bundle.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArchiveBundleTests(unittest.TestCase):
    def prepare(self, root):
        p, response, req = fixture()
        manifest = dict(company=dict(company_id=req.company.company_id,
            name=req.company.name, domain=req.company.domain),
            as_of=req.as_of.isoformat(), collection=COLLECTION, original_url=p.url,
            capture_timestamp=p.captured_at.strftime('%Y%m%d%H%M%S'),
            response_status=response.status, response_url=response.url,
            response_headers=response.headers, acquisition_note='SYNTHETIC fixture, no HTTP acquisition.')
        index = dict(url=p.url, timestamp=manifest['capture_timestamp'], status='200', mime='text/html',
            digest=p.digest_sha1_base32, filename=p.filename, offset=str(p.offset), length=str(p.length))
        (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (root/'index.jsonl').write_text(json.dumps(index), encoding='utf-8')
        (root/'record.gz').write_bytes(response.body)
        return manifest

    def run_bundle(self, root):
        return MODULE.inspect_bundle(root/'manifest.json', root/'index.jsonl', root/'record.gz', root/'out')

    def test_valid_integrity_never_releases_unverified_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.prepare(root); result=self.run_bundle(root)
            self.assertEqual(result['status'], 'INTEGRITY_CHECKED_ACQUISITION_REVIEW_PENDING')
            for key in ('transport_independently_authenticated', 'ledger_registration_allowed', 'model_input_released'):
                self.assertIs(result[key], False)
            self.assertEqual(result['source_http_requests'], 0)
            self.assertIn('Example Co', (root/'out/text_preview.txt').read_text())
            self.assertEqual(len(list((root/'out').iterdir())), 2)
            with self.assertRaisesRegex(ValueError, 'FRESH_OUTPUT'):
                self.run_bundle(root)

    def test_tampered_body_creates_no_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.prepare(root)
            body=(root/'record.gz').read_bytes(); (root/'record.gz').write_bytes(body[:-1]+b'X')
            with self.assertRaises(ValueError): self.run_bundle(root)
            self.assertFalse((root/'out').exists())

    def test_duplicate_fields_unknown_capture_and_added_labels_rejected(self):
        for mode in ('duplicate', 'capture', 'label'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root=Path(directory); manifest=self.prepare(root)
                if mode=='capture': manifest['capture_timestamp']='20240301000000'
                if mode=='label': manifest['Y']=1
                raw=json.dumps(manifest)
                if mode=='duplicate': raw=raw[:-1]+', "response_status": 206}'
                (root/'manifest.json').write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError): self.run_bundle(root)
                self.assertFalse((root/'out').exists())

    def test_oversized_local_input_rejected_before_decoding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.prepare(root)
            (root/'manifest.json').write_bytes(b'x'*65537)
            with self.assertRaisesRegex(ValueError, 'TOO_LARGE'): self.run_bundle(root)
            self.assertFalse((root/'out').exists())


if __name__=='__main__': unittest.main()
