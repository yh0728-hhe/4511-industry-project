"""Date precision and evidence-dimension regressions for the weekly audit."""
import copy
import csv
from datetime import date
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('audit_funding_dates', ROOT / 'scripts/audit_funding_dates.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FundingDateAuditTests(unittest.TestCase):
    def test_year_and_unknown_precision_do_not_infer_january_day(self):
        for precision in ('YEAR', 'UNREPORTED', 'UNKNOWN'):
            span = audit.date_interval('2026-01-01', precision)
            self.assertEqual(span, (date(2026, 1, 1), date(2026, 12, 31)))
            self.assertEqual(audit.window_attribution(span), 'UNDETERMINED')

    def test_whole_month_required_inside(self):
        self.assertEqual(audit.window_attribution(audit.date_interval('2026-04', 'MONTH')), 'UNDETERMINED')
        self.assertEqual(audit.window_attribution(audit.date_interval('2026-03', 'MONTH')), 'INSIDE')
        self.assertEqual(audit.window_attribution(audit.date_interval('2024-04', 'MONTH')), 'UNDETERMINED')

    def test_day_boundaries_and_leap_month(self):
        for value in ('2024-04-05', '2026-04-04'):
            self.assertEqual(audit.window_attribution(audit.date_interval(value, 'DAY')), 'INSIDE')
        self.assertEqual(audit.date_interval('2024-02', 'MONTH')[1], date(2024, 2, 29))
        self.assertEqual(audit.window_attribution(audit.date_interval('2026-04-05', 'DAY')), 'OUTSIDE')

    def test_three_calendar_month_boundary_screen_never_changes_dates(self):
        span = audit.date_interval('2026-07-04', 'DAY')
        self.assertEqual(audit.boundary_flags(span), 'END')
        self.assertEqual(audit.window_attribution(span), 'OUTSIDE')
        self.assertEqual(audit.boundary_flags(audit.date_interval('2026-07-05', 'DAY')), '')
        self.assertEqual(audit.month_shift(date(2024, 5, 31), -3), date(2024, 2, 29))

    def test_invalid_day_rejected_before_widening(self):
        with self.assertRaises(ValueError):
            audit.date_interval('2026-02-30', 'UNREPORTED')

    def setUp(self):
        with (ROOT / 'data/team_snapshot_20261111/funding_outcomes.csv').open() as stream:
            self.baseline = list(csv.DictReader(stream))
        self.reviews = json.loads((ROOT / 'data/weekly_audit_20261119/reviewed_evidence.json').read_text())['reviews']

    def test_one_primary_disclosure_added_transaction_labels_unchanged(self):
        before = copy.deepcopy(self.baseline)
        candidate, rows, summary = audit.build(self.baseline, self.reviews)
        self.assertEqual(self.baseline, before)
        self.assertEqual(summary['candidate_disclosure_companies'], 103)
        self.assertEqual(summary['disclosure_additions'], ['trueclaim'])
        self.assertEqual(summary['original_13_round_dates_undetermined'], 13)
        self.assertEqual(summary['verified_negative_companies'], 0)
        self.assertEqual([r['transaction_in_window_confirmed'] for r in candidate],
                         [r['transaction_in_window_confirmed'] for r in before])
        haplotype = next(r for r in rows if r['company_id'] == 'haplotype-labs')
        self.assertEqual(haplotype['transaction_event_attribution'], 'OUTSIDE')
        self.assertEqual(haplotype['transaction_company_label'], 'UNKNOWN')
        self.assertEqual(haplotype['company_strict_disclosure_candidate'], 'UNKNOWN')

    def test_primary_admission_cannot_accept_transaction_or_undated_record(self):
        row = copy.deepcopy(next(r for r in self.reviews if r['company_id'] == 'trueclaim'))
        row['alternative_disclosure_semantics'] = 'SEC_ISSUER_FIRST_SALE'
        with self.assertRaises(ValueError):
            audit.admitted_disclosure(row)
        row['alternative_disclosure_semantics'] = 'INVESTOR_PUBLIC_DISCLOSURE'
        row['alternative_disclosure_precision'] = 'UNREPORTED'
        with self.assertRaises(ValueError):
            audit.admitted_disclosure(row)
        row['alternative_disclosure_precision'] = 'YEAR'
        row['alternative_disclosure_date'] = '2026-01-01'
        with self.assertRaises(ValueError):
            audit.admitted_disclosure(row)

    def test_exact_original_13_ids_required(self):
        with self.assertRaises(ValueError):
            audit.build(self.baseline, self.reviews[:-1])
        with self.assertRaises(ValueError):
            audit.build(self.baseline, self.reviews + self.reviews[:1])


if __name__ == '__main__':
    unittest.main()
