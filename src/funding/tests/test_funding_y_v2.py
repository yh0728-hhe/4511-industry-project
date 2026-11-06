import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_funding_y_v2 as y


class FundingYV2Checks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.labels, cls.events, cls.excluded, cls.manifest = y.build()
        cls.by_id = {r['company_id']: r for r in cls.labels}

    def test_exact_cohort(self):
        original = y.read(y.INPUTS[0])
        self.assertEqual(len(self.labels), 240)
        self.assertEqual(set(self.by_id), {r['company_id'] for r in original})

    def test_unknown_never_zero_and_primary_requires_evidence(self):
        for row in self.labels:
            primary = [e for e in self.events if e['company_id'] == row['company_id'] and e['layer'] == 'PRIMARY']
            self.assertEqual(row['y_primary_observed'], 1 if primary else '')
            self.assertNotEqual(row['y_primary_observed'], 0)
        self.assertEqual(self.manifest['counts']['verified_negatives'], 0)

    def test_form_d_only_cannot_create_primary_label(self):
        supplemental_only = [r for r in self.labels if r['union_status'] == 'SUPPLEMENTARY_POSITIVE']
        self.assertEqual(len(supplemental_only), 3)
        for row in supplemental_only:
            self.assertEqual(row['y_primary_observed'], '')
            self.assertEqual(row['source_union_observed'], 1)

    def test_conflicting_legacy_matches_quarantined(self):
        for cid in ('lantern-2', 'argon-ai-inc'):
            self.assertEqual(self.by_id[cid]['union_status'], 'UNKNOWN')
            self.assertFalse(any(e['company_id'] == cid for e in self.events))
        # Tesseral is independently recovered, not admitted through its old RF match.
        self.assertEqual(self.by_id['tesseral']['y_primary_observed'], 1)
        self.assertEqual([e['evidence_id'] for e in self.events if e['company_id'] == 'tesseral'], ['OFFICIAL-TESSERAL-20250506'])

    def test_recovered_positive_evidence_counts_and_no_announcement_duplicate(self):
        for cid, expected in [('RM-agenthub', 3), ('RM-delve', 1), ('trieve', 1)]:
            self.assertEqual(self.by_id[cid]['y_primary_observed'], 1)
            self.assertEqual(self.by_id[cid]['evidence_record_count'], expected)

    def test_month_precision_does_not_fabricate_a_day(self):
        event = next(e for e in self.events if e['company_id'] == 'trieve')
        self.assertEqual(event['event_date'], '')
        self.assertEqual(event['date_precision'], 'MONTH')
        self.assertTrue(y.interval_in_window(event['date_start'], event['date_end']))
        self.assertFalse(y.interval_in_window('2024-04-01', '2024-04-30'))
        self.assertFalse(y.interval_in_window('2026-04-01', '2026-04-30'))
        self.assertFalse(y.interval_in_window('2025-02-02', '2025-02-01'))

    def test_calendar_and_window_boundaries(self):
        self.assertFalse(y.in_window('2024-04-04'))
        self.assertTrue(y.in_window('2026-04-04'))
        self.assertFalse(y.in_window('2026-04-05'))
        for invalid in ('', 'unknown', '2025-02-31'):
            with self.assertRaises(ValueError):
                y.in_window(invalid)

    def test_contradicting_bulk_domain_is_rejected(self):
        original = y.read
        def changed(rel):
            rows = copy.deepcopy(original(rel))
            if rel == y.INPUTS[3]:
                row = next(r for r in rows if r['match_basis'] == 'DOMAIN')
                row['matched_website'] = 'different-company.invalid'
            return rows
        with patch.object(y, 'read', side_effect=changed):
            with self.assertRaises(ValueError):
                y.build()

    def test_event_outside_cohort_rejected(self):
        original = y.read
        def changed(rel):
            rows = copy.deepcopy(original(rel))
            if rel == y.INPUTS[4]:
                rows[0]['company_id'] = 'not-in-cohort'
            return rows
        with patch.object(y, 'read', side_effect=changed):
            with self.assertRaises(ValueError):
                y.build()

    def test_amount_conflicts_not_summed_or_chosen(self):
        conflicts = [e for e in self.events if e['amount_conflict'] == 'YES']
        self.assertTrue(conflicts)
        self.assertTrue(all(e['amount_usd'] == '' for e in conflicts))

    def test_repeatable_and_all_inputs_hashed(self):
        self.assertEqual(y.build(), (self.labels, self.events, self.excluded, self.manifest))
        self.assertEqual(set(self.manifest['input_sha256']), set(y.INPUTS))
        for rel, checksum in self.manifest['input_sha256'].items():
            self.assertEqual(checksum, y.digest(y.ROOT / rel))


if __name__ == '__main__':
    unittest.main()
