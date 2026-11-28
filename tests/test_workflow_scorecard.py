"""Independent hand-calculated scorer tests, not model-performance data."""
import copy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
from workflow_automation.scorecard import score, main


class ScorecardTests(unittest.TestCase):
    def setUp(self):
        self.g={'version':'claim-scorecard-v1','cases':[
            {'case_id':'a','facts':[{'claim_id':'historical','source_id':'old','admissible':True},
                                   {'claim_id':'future','source_id':'new','admissible':False}]},
            {'case_id':'b','facts':[]}]}
        self.s={'version':'claim-scorecard-v1','cases':[
            {'case_id':'a','status':'COMPLETED','claims':[{'claim_id':'historical','source_id':'old'},
                                                       {'claim_id':'future','source_id':'new'}]},
            {'case_id':'b','status':'ABSTAINED','claims':[]}]}

    def test_hand_calculated_precision_recall_and_abstention(self):
        m=score(self.g,self.s)['metrics']
        self.assertEqual(m['structural_citation_precision'],{'numerator':1,'denominator':2,'rate':0.5})
        self.assertEqual(m['admissible_claim_recall']['rate'],1)
        self.assertEqual(m['appropriate_abstention_rate']['rate'],1)
        self.assertEqual(m['abstention_rate']['rate'],0.5)

    def test_wrong_citation_not_supported(self):
        self.s['cases'][0]['claims'][0]['source_id']='other-company'
        self.assertEqual(score(self.g,self.s)['metrics']['structural_citation_precision']['rate'],0)

    def test_missing_case_rejected_not_dropped(self):
        self.s['cases'].pop()
        with self.assertRaises(ValueError):score(self.g,self.s)

    def test_duplicate_claim_cannot_inflate_counts(self):
        self.s['cases'][0]['claims'].append(copy.deepcopy(self.s['cases'][0]['claims'][0]))
        with self.assertRaises(ValueError):score(self.g,self.s)

    def test_duplicate_case_rejected(self):
        self.s['cases'].append(copy.deepcopy(self.s['cases'][0]))
        with self.assertRaises(ValueError):score(self.g,self.s)

    def test_failed_case_retains_recall_denominator(self):
        self.s['cases'][0].update(status='FAILED',claims=[])
        m=score(self.g,self.s)['metrics']
        self.assertEqual(m['admissible_claim_recall']['rate'],0)
        self.assertEqual(m['failure_rate']['rate'],0.5)
        self.assertIsNone(m['structural_citation_precision']['rate'])

    def test_no_admissible_claims_null_recall_not_perfect(self):
        self.g['cases'][0]['facts'][0]['admissible']=False
        self.assertIsNone(score(self.g,self.s)['metrics']['admissible_claim_recall']['rate'])

    def test_failed_or_abstained_cannot_smuggle_claims(self):
        self.s['cases'][0]['status']='ABSTAINED'
        with self.assertRaises(ValueError):score(self.g,self.s)

    def test_unreviewed_gold_rejected(self):
        self.g['cases'][0]['facts'][0]['admissible']='YES'
        with self.assertRaises(ValueError):score(self.g,self.s)

    def test_unknown_claim_is_unsupported(self):
        self.s['cases'][0]['claims'][0]['claim_id']='fabricated'
        self.assertEqual(score(self.g,self.s)['metrics']['structural_citation_precision']['rate'],0)

    def test_excess_abstention_and_unsupported_rates(self):
        self.assertEqual(score(self.g,self.s)['metrics']['unsupported_or_wrong_citation_rate']['rate'],0.5)
        self.s['cases'][0].update(status='ABSTAINED',claims=[])
        self.assertEqual(score(self.g,self.s)['metrics']['excess_abstention_rate'],
                         {'numerator':1,'denominator':1,'rate':1.0})

    def test_completed_empty_not_counted_as_abstention(self):
        self.s['cases'][1]['status']='COMPLETED'
        m=score(self.g,self.s)['metrics']
        self.assertEqual(m['appropriate_abstention_rate']['rate'],0)
        self.assertEqual(m['abstention_rate']['rate'],0)

    def test_cli_hashes_and_exclusive_output(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);g=folder/'gold.json';s=folder/'pred.json';o=folder/'report.json'
            g.write_text(json.dumps(self.g));s.write_text(json.dumps(self.s))
            args=['scorecard','--gold',str(g),'--submission',str(s),'--output',str(o)]
            with patch('sys.argv',args):main()
            report=json.loads(o.read_text())
            self.assertEqual(len(report['input_sha256']['gold']),64)
            before=o.read_bytes()
            with patch('sys.argv',args), self.assertRaises(SystemExit):main()
            self.assertEqual(before,o.read_bytes())

    def test_cli_refuses_to_overwrite_gold(self):
        with tempfile.TemporaryDirectory() as d:
            g=Path(d)/'gold.json';s=Path(d)/'pred.json'
            g.write_text(json.dumps(self.g));s.write_text(json.dumps(self.s));before=g.read_bytes()
            with patch('sys.argv',['scorecard','--gold',str(g),'--submission',str(s),'--output',str(g)]),self.assertRaises(SystemExit):main()
            self.assertEqual(before,g.read_bytes())


if __name__=='__main__':unittest.main()
