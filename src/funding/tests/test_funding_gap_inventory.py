import csv
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src/funding'))
import build_funding_gap_inventory as inventory


class InventoryChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.pilot = inventory.build_rows(str(REPO))
        cls.by_id = {r['company_id']: r for r in cls.rows}

    def test_exact_frozen_cohort_and_values_no_candidate_promotion(self):
        labels = inventory.read_csv(str(REPO / inventory.LABELS_PATH))
        self.assertEqual(set(self.by_id), {r['company_id'] for r in labels})
        self.assertEqual(len(self.rows), 240)
        for lab in labels:
            row = self.by_id[lab['company_id']]
            for name in ('confirmed_positive', 'observation_status', 'observed_event_count', 'recentfunding_status'):
                self.assertEqual(row['frozen_' + name], lab[name])
        for cid in ('RM-agenthub', 'RM-delve'):
            self.assertEqual(self.by_id[cid]['candidate_evidence_present'], '1')
            self.assertEqual(self.by_id[cid]['frozen_observation_status'], 'UNKNOWN')

    def test_search_gap_alone_is_not_a_detail_gap(self):
        gaps = inventory.read_csv(str(REPO / inventory.REMATCH_GAPS_PATH))
        expected = {r['company_id'] for r in gaps if r['gap_kind'] == 'DETAIL_NOT_CACHED'}
        actual = {r['company_id'] for r in self.rows if r['missing_detail_cache'] == '1'}
        self.assertEqual(actual, expected)
        search_only = {r['company_id'] for r in gaps if r['gap_kind'] == 'SEARCH_NOT_CACHED'} - expected
        self.assertTrue(search_only)
        for cid in search_only:
            self.assertNotIn('MISSING_DETAIL_CACHE', self.by_id[cid]['reason_flags'])

    def test_original_caveats_carried_without_false_match_verdict(self):
        raw = {r['entity_id']: r for r in inventory.read_csv(str(REPO / inventory.RAW_OUTCOMES_PATH))}
        for cid in ('lantern-2', 'argon-ai-inc'):
            self.assertEqual(self.by_id[cid]['form_d_confirmed_label_caveat'], raw[cid]['funding_match_caveat'])

    def test_pilot_count_and_nonexclusive_reasons(self):
        self.assertEqual(len(self.pilot), 20)
        row = self.by_id['RM-agenthub']
        self.assertIn('CANDIDATE_EVIDENCE_PRESENT', row['reason_flags'])
        self.assertIn('NO_OBSERVED_EVENT', row['reason_flags'])

    def test_duplicate_frozen_ids_fail_closed(self):
        original = inventory.read_csv
        def damaged(path):
            rows = original(path)
            return rows[:-1] + [rows[0]] if path.endswith(inventory.LABELS_PATH) else rows
        with patch.object(inventory, 'read_csv', side_effect=damaged):
            with self.assertRaises(ValueError):
                inventory.build_rows(str(REPO))

    def test_inventory_directory_cannot_overwrite_seed_or_frozen_output(self):
        for path in (inventory.SOURCE_DIR, 'results/verified/funding_y_v1', '../escaped'):
            with self.assertRaises(ValueError):
                inventory.resolve_confined_out_dir(str(REPO), path)

    def test_build_and_manifest_deterministic(self):
        again, pilot = inventory.build_rows(str(REPO))
        self.assertEqual(again, self.rows)
        one = inventory.build_manifest(str(REPO), self.rows, self.pilot)
        self.assertEqual(one, inventory.build_manifest(str(REPO), again, pilot))
        self.assertEqual(one['counts']['missing_detail_cache_present'], 2)


if __name__ == '__main__':
    unittest.main()
