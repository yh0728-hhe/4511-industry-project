from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.cli_limits import find_primary_rate_limit_rejection, is_quota_result_envelope


class QuotaEnvelopeTests(unittest.TestCase):
    def test_success_envelope_never_classified_even_with_quota_text(self):
        self.assertFalse(is_quota_result_envelope({'is_error':False,'result':'quota looks fine'}))

    def test_known_subtype_classified(self):
        self.assertTrue(is_quota_result_envelope({'is_error':True,'subtype':'error_quota_exceeded'}))

    def test_text_marker_without_subtype_classified(self):
        self.assertTrue(is_quota_result_envelope({'is_error':True,'result':'Usage limit reached'}))

    def test_errors_list_marker_classified(self):
        self.assertTrue(is_quota_result_envelope({'is_error':True,'errors':['hit-your-limit for this account']}))

    def test_generic_error_not_classified(self):
        self.assertFalse(is_quota_result_envelope({'is_error':True,'errors':['max-turns exceeded']}))

    def test_disk_quota_and_unrelated_guard_do_not_claim_model_exhaustion(self):
        self.assertFalse(is_quota_result_envelope({'is_error':True,'result':'Disk quota used up (ENOSPC)'}))
        self.assertFalse(is_quota_result_envelope({'is_error':True,'subtype':'error_max_budget_usd','result':'Local experiment budget guard, not a quota rejection'}))
        self.assertFalse(is_quota_result_envelope({'is_error':True,'result':'Failed to parse QuotaTool'}))
        self.assertFalse(is_quota_result_envelope({'is_error':True,'result':'Not a quota error; malformed result'}))
        self.assertFalse(is_quota_result_envelope({'is_error':True,'result':'quota not exceeded'}))
        self.assertFalse(is_quota_result_envelope({'is_error':True,'subtype':[]}))
    def test_credit_code_and_hyphenated_limit_errors_are_recognized(self):
        self.assertTrue(is_quota_result_envelope({'is_error':True,'errors':['credits_required']}))
        self.assertTrue(is_quota_result_envelope({'is_error':True,'result':'Token quota has been exhausted'}))
        self.assertTrue(is_quota_result_envelope({'is_error':True,'errors':['rate_limit_error']}))

    def test_non_error_dict_not_classified(self):
        self.assertFalse(is_quota_result_envelope({'subtype':'error_quota_exceeded'}))


class RateLimitEventTests(unittest.TestCase):
    def test_primary_rejected_detected(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}}]
        self.assertIsNotNone(find_primary_rate_limit_rejection(events))

    def test_primary_allowed_with_secondary_rejected_not_detected(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'allowed'},
            'secondary_rate_limit_info':{'status':'rejected'}}]
        self.assertIsNone(find_primary_rate_limit_rejection(events))

    def test_allowed_warning_not_detected(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'allowed_warning'}}]
        self.assertIsNone(find_primary_rate_limit_rejection(events))

    def test_nested_tool_text_never_consulted(self):
        events=[{'type':'user','message':{'content':[{'type':'tool_result','content':'rejected quota'}]}}]
        self.assertIsNone(find_primary_rate_limit_rejection(events))

    def test_first_rejection_returned_even_if_later_allowed(self):
        events=[{'type':'rate_limit_event','rate_limit_info':{'status':'rejected'}},
            {'type':'rate_limit_event','rate_limit_info':{'status':'allowed'}}]
        self.assertIs(find_primary_rate_limit_rejection(events), events[0])


if __name__=='__main__':unittest.main()
