import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import build_cohort_historical_dataset as dataset


class CohortHistoricalChecks(unittest.TestCase):
    def test_all_rows_and_honest_gaps(self):
        packets,rows,m=dataset.build()
        self.assertEqual(len(packets),240)
        self.assertEqual(len({p['company_id'] for p in packets}),240)
        self.assertEqual(m['counts']['archived_structured_companies'],57)
        self.assertEqual(m['counts']['companies_with_dated_source'],75)
        self.assertEqual(m['counts']['evidence_gap_companies'],165)
        self.assertTrue(all(not p['model_ready'] for p in packets))
        self.assertTrue(all(p['local_external_availability_date'] is None for p in packets))
        self.assertFalse(any('outcomes' in p or 'funding_y' in p for p in m['input_sha256']))

    def test_archived_fields_are_pre_cutoff(self):
        packets,_,_=dataset.build()
        for p in packets:
            a=p['archived_yc_fields']
            if a:
                self.assertLessEqual(a['capture_date'],'2024-04-04')
                self.assertEqual(a['original_company_name'],p['company_name_at_decision'])
                self.assertIsNone(a['market_size'])
                self.assertIsNone(a['revenue'])

    def test_post_cutoff_capture_rejected(self):
        with dataset.COHORT.open(encoding='utf-8-sig',newline='') as f:
            row=next(dataset.csv.DictReader(f))
        r=dict(query_status='ARCHIVE_BODY_FETCHED',capture_timestamp='20240405000000')
        with self.assertRaises(ValueError):dataset.archived_claims(row,r)

    def test_loose_hn_company_match_rejected(self):
        row={'Company Name':'Sample'}
        hits=[dict(title='Launch HN: Soundry AI (YC W24) - sample generator',created_at='2024-03-21',objectID='1')]
        self.assertEqual(dataset.hn_matches(row,hits),[])

    def test_offline_curated_extractions_reproduce(self):
        expected=dataset.build()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(dataset,'CACHE',Path(tmp)):
                self.assertEqual(dataset.build(),expected)
        self.assertEqual(expected[2],json.loads((dataset.OUT/'manifest.json').read_text(encoding='utf-8')))


if __name__=='__main__':unittest.main()
