"""Local replay integration with invented archive records; no HTTP or models."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from closed_loop.archive_transport import HTTPResponse
from closed_loop.guards import BudgetStopped
from closed_loop.sealed_archive_replay import SealedArchiveReplayClient

URL='https://web.archive.org/web/20240301000000id_/https://example.com/'


class SealedReplayTests(unittest.TestCase):
    def setup_cache(self, root, **updates):
        (root/'capture.body').write_bytes(b'ORIGINAL_ARCHIVE_BODY')
        row=dict(request_url=URL,response_url=URL,status=200,headers={'Memento-Datetime':'Fri, 01 Mar 2024 00:00:00 GMT'},body_file='capture.body',body_sha256=hashlib.sha256(b'ORIGINAL_ARCHIVE_BODY').hexdigest())
        row.update(updates)
        raw=json.dumps(dict(version=1,responses=[row])).encode()
        (root/'manifest.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def test_exact_replay_zero_network_and_no_shared_header_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest=self.setup_cache(root)
            c=SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256=digest,max_gets=2)
            r=c.get(URL,1,100)
            self.assertIsInstance(r,HTTPResponse);self.assertEqual(r.body,b'ORIGINAL_ARCHIVE_BODY')
            r.headers.clear();self.assertTrue(c.get(URL,1,100).headers)
            self.assertEqual(c.actual_http_requests,0)
            self.assertEqual(len(c.events),2)
            with self.assertRaisesRegex(BudgetStopped,'CALL_CAP'):c.get(URL,1,100)

    def test_missing_url_never_falls_back_and_records_hold(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest=self.setup_cache(root)
            c=SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256=digest)
            with self.assertRaisesRegex(BudgetStopped,'CACHE_MISS'):
                c.get(URL+'missing',1,100)
            self.assertEqual(c.events[0]['status'],'HELD')
            self.assertEqual(c.actual_http_requests,0)

    def test_changed_body_or_manifest_cannot_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest=self.setup_cache(root)
            with self.assertRaisesRegex(ValueError,'MANIFEST_CHANGED'):
                SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256='0'*64)
            c=SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256=digest)
            (root/'capture.body').write_bytes(b'CHANGED')
            with self.assertRaisesRegex(ValueError,'BODY_CHANGED'):c.get(URL,1,100)
            self.assertEqual(c.events[0]['status'],'HELD')

    def test_path_escape_duplicate_manifest_keys_and_extra_fields_rejected(self):
        for fields in ({'body_file':'../capture.body'},{'request_url':'https://evil.test/'},{'response_url':URL+'redirect'},{'status':True},{'unexpected':'x'}):
            with self.subTest(fields=fields),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);digest=self.setup_cache(root,**fields)
                with self.assertRaises(ValueError):SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256=digest)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.setup_cache(root)
            p=root/'manifest.json';raw=p.read_bytes().replace(b'"version": 1',b'"version": 2,"version": 1');p.write_bytes(raw)
            with self.assertRaises(ValueError):SealedArchiveReplayClient(p,trusted_manifest_sha256=hashlib.sha256(raw).hexdigest())

    def test_shared_deadline_and_body_cap_prevent_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);digest=self.setup_cache(root)
            c=SealedArchiveReplayClient(root/'manifest.json',trusted_manifest_sha256=digest)
            def stop():raise BudgetStopped('STOP_OR_DEADLINE')
            with self.assertRaises(BudgetStopped):c.get(URL,1,100,check_deadline=stop)
            self.assertEqual(c.events,[])
            with self.assertRaises(ValueError):c.get(URL,1,3)
            self.assertEqual(c.events[0]['status'],'HELD')


if __name__=='__main__':unittest.main()
