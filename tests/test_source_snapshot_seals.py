"""Forensic worker snapshots are data: preserve bytes, never import or execute."""
import hashlib
import json
from pathlib import Path
import unittest


class SourceSnapshotSealTests(unittest.TestCase):
    def test_git_checkout_snapshots_match_frozen_raw_byte_protocols(self):
        root=Path(__file__).resolve().parents[1]
        cases=[('danswer_archive_worker_20261128.py.txt','danswer_archive_protocol_20261128.json','worker_sha256'),
               ('sealed_replay_initial_client_20261128.py.txt','sealed_real_archive_replay_protocol_20261128.json','source_client_sha256')]
        for filename,protocol,key in cases:
            with self.subTest(filename=filename):
                value=json.loads((root/'data/metadata/workflow_20261121'/protocol).read_text(encoding='utf-8'))
                raw=(root/'docs/workflow_automation_20261121/probe_worker_sources'/filename).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(),value[key])


if __name__=='__main__':unittest.main()
