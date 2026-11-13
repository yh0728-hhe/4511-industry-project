"""Dated discovery is distinct from independently verified target content."""
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import json
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider,HTTPResponse
from closed_loop.contracts import ResearchRequest
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,TemporalGateway


class LinkedHTTP:
    def __init__(self,future_target=False):self.calls=[];self.future_target=future_target
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        check_deadline();self.calls.append(url)
        if '/cdx/' in url:
            original='https://'+parse_qs(urlparse(url).query)['url'][0]
            future=self.future_target and original.endswith('/pricing')
            ts='20250320000000' if future else '20240320000000'
            rows=[['timestamp','original','statuscode','mimetype'],[ts,original,'200','text/html']]
            return HTTPResponse(200,url,{},json.dumps(rows).encode())
        text=('Invented historical company website description. '*3)
        if url.endswith('/pricing'):text+='Fixture price is ten units per seat, not real company data.'
        else:text+='<a href="/pricing">Pricing plans</a><a href="/team">Our founders</a>'
        return HTTPResponse(200,url,{'Memento-Datetime':'Wed, 20 Mar 2024 00:00:00 GMT','Content-Type':'text/html'},text.encode())


def setup(future_target=False,cap=8):
    req=request(max_search_calls=cap);budget=CallBudget(req);gateway=TemporalGateway(req,[])
    client=LinkedHTTP(future_target)
    return ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=cap),gateway,budget,client


class NavigationTests(unittest.TestCase):
    def test_old_homepage_links_target_requires_separate_index_and_replay(self):
        provider,gateway,budget,client=setup()
        candidates=provider.search(ResearchRequest('unit_economics','Pricing plans?','SYNTHETIC_COMPANY'))
        self.assertEqual(len(candidates),2)
        self.assertEqual(len(client.calls),4)
        self.assertEqual(budget.used['search'],4)
        self.assertEqual(len(provider.receipts),2)
        facts=[gateway.admit(candidate)[0] for candidate in candidates]
        self.assertIn('ten units per seat',facts[1].text)
        self.assertTrue(all(not hint['target_content_verified'] for hint in provider.link_hints()))

    def test_old_href_does_not_admit_future_target_body(self):
        provider,_,budget,client=setup(future_target=True)
        candidates=provider.search(ResearchRequest('unit_economics','Pricing?','SYNTHETIC_COMPANY'))
        self.assertEqual(len(candidates),1)
        self.assertEqual(len(client.calls),3)
        self.assertEqual(budget.used['search'],3)
        self.assertFalse(any('/pricing' in item['original_url'] for item in provider.receipts))
        self.assertTrue(any(hint['path']=='/pricing' for hint in provider.link_hints()))

    def test_model_cannot_select_path_not_observed_historically(self):
        provider,_,_,client=setup()
        candidates=provider.search(ResearchRequest('product','Secret plan?','SYNTHETIC_COMPANY',source_path='/unseen'))
        self.assertEqual(len(candidates),1);self.assertEqual(len(client.calls),2)
        self.assertEqual(provider.attempts[-1]['status'],'REQUESTED_PATH_NOT_OBSERVED_HISTORICALLY')

    def test_budget_preserves_homepage_without_starting_unaffordable_target(self):
        provider,_,budget,client=setup(cap=3)
        self.assertEqual(len(provider.search(ResearchRequest('unit_economics','Pricing?','SYNTHETIC_COMPANY'))),1)
        self.assertEqual(len(client.calls),2)
        self.assertEqual(budget.used['search'],2)
        self.assertEqual(provider.attempts[-1]['status'],'OPTIONAL_LOOKUP_SKIPPED_BUDGET')


if __name__=='__main__':unittest.main()
