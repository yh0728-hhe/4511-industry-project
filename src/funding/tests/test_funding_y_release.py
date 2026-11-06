import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_funding_y_release as release


class ReleaseChecks(unittest.TestCase):
    def test_reproduces_latest_counts_without_negative_labels(self):
        rows,m=release.build()
        self.assertEqual(len(rows),240)
        self.assertEqual(m['counts']['primary_positive'],110)
        self.assertEqual(m['counts']['supplementary_only'],1)
        self.assertEqual(m['counts']['union_unknown'],129)
        self.assertFalse(m['goal']['achieved'])
        self.assertTrue(all(r['y_primary_observed'] in ('','1') for r in rows))
        self.assertEqual(m,json.loads((release.OUT/'manifest.json').read_text()))

    def fail_changed(self,transform):
        original=release.read
        def changed(path):
            rows=copy.deepcopy(original(path))
            if path==release.OBS:transform(rows)
            return rows
        with patch.object(release,'read',side_effect=changed):
            with self.assertRaises(ValueError):release.build()

    def test_outside_window_rejected(self):
        self.fail_changed(lambda r:r[0].update(date_lower='2024-04-04'))

    def test_foreign_company_rejected(self):
        self.fail_changed(lambda r:r[0].update(company_id='unrelated'))

    def test_duplicate_rejected(self):
        self.fail_changed(lambda r:r.append(copy.deepcopy(r[0])))

    def test_deterministic(self):self.assertEqual(release.build(),release.build())


if __name__=='__main__':unittest.main()
