"""Deterministic HTTP fixtures; no requests to real archive/company services."""
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import json
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request,stamp
from closed_loop.contracts import ResearchRequest
from closed_loop.guards import CallBudget,TemporalGateway,BudgetStopped
from closed_loop.archive_transport import (ArchivedWebsiteProvider,HTTPResponse,archive_url_allowed,
    RetrievalFailed,visible_text,ArchiveRestricted)


class ArchiveFixtureHTTP:
    def __init__(self,variant='ok'):
        self.variant=variant;self.calls=[]
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        self.calls.append(url);check_deadline()
        if self.variant=='transport_error':raise RetrievalFailed('HTTP_TRANSPORT_ERROR')
        if '/cdx/' in url:
            if self.variant=='429':return HTTPResponse(429,url,{},b'')
            if self.variant=='empty':return HTTPResponse(200,url,{},b'[]')
            if self.variant=='bad_json':return HTTPResponse(200,url,{},b'not JSON')
            exact=parse_qs(urlparse(url).query).get('from',[None])[0]
            ts=exact if exact and self.variant=='reindex_earlier' else ('20250320000000' if self.variant=='future' else '20240320000000')
            original='https://other.example/' if self.variant=='other_domain' else 'https://synthetic.example/'
            rows=[['timestamp','original','statuscode','mimetype'],[ts,original,'200','text/html']]
            return HTTPResponse(200,url,{},json.dumps(rows).encode())
        if self.variant in ('reindex_earlier','reindex_missing','redirect_future') and '/20240320000000id_/' in url:
            replacement='20250320000000' if self.variant=='redirect_future' else '20240319000000'
            return HTTPResponse(302,url,{'Location':url.replace('20240320000000',replacement)},b'')
        headers={'Memento-Datetime':'Wed, 20 Mar 2024 00:00:00 GMT','Content-Type':'text/html'}
        if '/20240319000000id_/' in url:headers['Memento-Datetime']='Tue, 19 Mar 2024 00:00:00 GMT'
        if self.variant=='no_memento':headers={}
        if self.variant=='substitute':headers['Memento-Datetime']='Thu, 21 Mar 2024 00:00:00 GMT'
        final=url if self.variant!='redirect' else url.replace('20240320','20240321')
        if self.variant=='short':body=b'<html><script>modern scripted content</script>empty</html>'
        else:body=b'<html><body>Synthetic archived company information, products and market context. This is explicitly invented fixture content. <script>SECRET_SCRIPT_VALUE</script></body></html>'
        return HTTPResponse(200,final,headers,body)


class RootRestrictedHTTP:
    """The very first (bootstrap homepage) CDX lookup is archive-restricted."""
    def __init__(self,status):
        self.status=status;self.calls=[]
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        self.calls.append(url);check_deadline()
        return HTTPResponse(self.status,url,{},b'')


class TeamPageRestrictedHTTP:
    """Homepage resolves normally; the later team-page replay is restricted."""
    def __init__(self,status):
        self.status=status;self.calls=[]
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        self.calls.append(url);check_deadline()
        if '/cdx/' in url:
            target=parse_qs(urlparse(url).query)['url'][0]
            original='https://'+target
            rows=[['timestamp','original','statuscode','mimetype'],['20240320000000',original,'200','text/html']]
            return HTTPResponse(200,url,{},json.dumps(rows).encode())
        if url.endswith('id_/https://synthetic.example/team'):
            return HTTPResponse(self.status,url,{},b'')
        headers={'Memento-Datetime':'Wed, 20 Mar 2024 00:00:00 GMT','Content-Type':'text/html'}
        body=(b'<html><body>Synthetic archived root page with enough visible text for admission checks. '
              b'<a href="/team">Meet our founding team</a></body></html>')
        return HTTPResponse(200,url,headers,body)


TEAM_TASK=ResearchRequest('team','Our founding team history','SYNTHETIC_COMPANY')


def provider(variant='ok',cap=8,max_requests=8):
    req=request(max_search_calls=cap);budget=CallBudget(req);gateway=TemporalGateway(req,[])
    client=ArchiveFixtureHTTP(variant)
    return ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=max_requests),gateway,budget,client


TASK=ResearchRequest('market','market','SYNTHETIC_COMPANY')


class ArchiveTests(unittest.TestCase):
    def test_readable_replay_and_memento_generate_admissible_record(self):
        p,g,b,c=provider()
        candidates=p.search(TASK)
        self.assertEqual(len(candidates),1)
        fact,rejection=g.admit(candidates[0])
        self.assertIsNone(rejection)
        self.assertNotIn('SECRET_SCRIPT_VALUE',fact.text)
        self.assertEqual(fact.availability_upper_bound,stamp('2024-03-20T00:00:00Z'))
        self.assertEqual(len(c.calls),2);self.assertEqual(b.used['search'],2)
        self.assertEqual(p.receipts[0]['availability_proof'],'READABLE_REPLAY_MATCHING_MEMENTO')

    def test_query_has_cutoff_and_no_one_year_lower_bound(self):
        p,_,_,c=provider();p.search(TASK)
        query=parse_qs(urlparse(c.calls[0]).query)
        self.assertEqual(query['to'],['20240404235959'])
        self.assertEqual(query['limit'],['-1']);self.assertNotIn('from',query)

    def test_future_or_other_entity_capture_never_reaches_replay(self):
        for variant in ('future','other_domain'):
            p,_,_,c=provider(variant)
            self.assertEqual(p.search(TASK),())
            self.assertEqual(len(c.calls),1)

    def test_replay_needs_body_matching_capture_and_header(self):
        for variant in ('no_memento','substitute','redirect','short'):
            with self.subTest(variant=variant):
                p,_,_,_=provider(variant)
                self.assertEqual(p.search(TASK),())
                self.assertEqual(p.receipts,[])

    def test_alternate_capture_requires_new_index_check_and_uses_actual_date(self):
        p,g,b,c=provider('reindex_earlier')
        candidates=p.search(TASK)
        self.assertEqual(len(candidates),1)
        fact,_=g.admit(candidates[0])
        self.assertEqual(fact.availability_upper_bound,stamp('2024-03-19T00:00:00Z'))
        self.assertEqual(p.receipts[0]['original_requested_capture_before_reindex'],'20240320000000')
        self.assertEqual(len(c.calls),4);self.assertEqual(b.used['search'],4)
        self.assertEqual(parse_qs(urlparse(c.calls[2]).query)['from'],['20240319000000'])

    def test_future_or_nonindexed_alternate_is_never_silently_accepted(self):
        for variant in ('reindex_missing','redirect_future'):
            p,_,_,_=provider(variant)
            self.assertEqual(p.search(TASK),())
            self.assertFalse(p.receipts)

    def test_failure_not_converted_to_no_funding_or_death(self):
        for variant in ('transport_error','429','bad_json'):
            p,_,b,_=provider(variant);self.assertEqual(p.search(TASK),())
            self.assertEqual(b.used['search'],1)
            statuses=[x['status'] for x in p.attempts]
            self.assertTrue(any(x in statuses for x in ('HTTP_TRANSPORT_ERROR','HTTP_429','INVALID_CDX_RESPONSE')))
            self.assertNotIn('NO_FUNDING',statuses);self.assertNotIn('DEAD',statuses)

    def test_repeated_lookup_does_not_repeat_http_or_invent_new_evidence(self):
        p,_,b,c=provider();first=p.search(TASK);second=p.search(replace(TASK,role='traction',question='retention'))
        self.assertEqual(first,second);self.assertEqual(len(c.calls),2);self.assertEqual(b.used['search'],2)

    def test_each_http_request_reserved_before_dispatch(self):
        p,_,b,c=provider(cap=1)
        with self.assertRaises(BudgetStopped):p.search(TASK)
        self.assertEqual(len(c.calls),1);self.assertEqual(b.used['search'],1)
        self.assertEqual(b.active,0)

    def test_provider_request_cap_is_enforced(self):
        p,_,_,c=provider(max_requests=1)
        with self.assertRaisesRegex(BudgetStopped,'HTTP_REQUEST_CAP'):p.search(TASK)
        self.assertEqual(len(c.calls),1)

    def test_unknown_peer_needs_domain_anchor(self):
        p,_,_,c=provider()
        self.assertEqual(p.search(replace(TASK,subject_id='UNKNOWN_PEER')),())
        self.assertEqual(c.calls,[])

    def test_archive_host_policy_rejects_credentials_other_hosts_and_bad_ports(self):
        self.assertTrue(archive_url_allowed('https://web.archive.org/cdx/search/cdx'))
        for url in ('https://evil.example/','http://web.archive.org/','https://web.archive.org.evil.example/',
                    'https://key@web.archive.org/','https://web.archive.org:bad/','https://web.archive.org:444/'):
            self.assertFalse(archive_url_allowed(url))

    def test_cdx_403_or_429_stops_the_run_with_an_explicit_restriction_cause(self):
        for status,cause in ((403,'ARCHIVE_ACCESS_RESTRICTED'),(429,'ARCHIVE_RATE_LIMITED')):
            with self.subTest(status=status):
                req=request();budget=CallBudget(req);gateway=TemporalGateway(req,[])
                client=RootRestrictedHTTP(status)
                p=ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=8)
                self.assertEqual(p.search(TASK),())
                self.assertTrue(budget.stopped)
                self.assertEqual(budget.stop_reason,cause)
                self.assertIn(cause,[x['status'] for x in p.attempts])
                self.assertEqual(len(client.calls),1)

    def test_replay_403_or_429_after_successful_root_preserves_the_root_evidence(self):
        for status,cause in ((403,'ARCHIVE_ACCESS_RESTRICTED'),(429,'ARCHIVE_RATE_LIMITED')):
            with self.subTest(status=status):
                req=request();budget=CallBudget(req);gateway=TemporalGateway(req,[])
                client=TeamPageRestrictedHTTP(status)
                p=ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=8)
                candidates=p.search(TEAM_TASK)
                self.assertEqual(len(candidates),1)
                fact,rejection=gateway.admit(candidates[0])
                self.assertIsNone(rejection)
                self.assertTrue(budget.stopped)
                self.assertEqual(budget.stop_reason,cause)
                self.assertIn(cause,[x['status'] for x in p.attempts])
                # Root capture+replay plus the restricted team CDX+replay: no retry.
                self.assertEqual(len(client.calls),4)

    def test_restriction_blocks_cross_task_dispatch_and_retains_the_original_cause(self):
        client=TeamPageRestrictedHTTP(429)
        req=request();budget=CallBudget(req);gateway=TemporalGateway(req,[])
        p=ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=8)
        first=p.search(TEAM_TASK)
        self.assertEqual(len(first),1)
        calls_after_first=len(client.calls)
        # A genuinely new subject/domain would need a fresh CDX+replay pair;
        # the restriction must stop it before any new dispatch, not just this path.
        p.domain_anchors['PEER_COMPANY']='peer.example'
        with self.assertRaisesRegex(BudgetStopped,'ARCHIVE_RATE_LIMITED'):
            p.search(ResearchRequest('founder','founders','SYNTHETIC_COMPANY','PEER_COMPANY'))
        self.assertEqual(len(client.calls),calls_after_first)
        self.assertEqual(budget.stop_reason,'ARCHIVE_RATE_LIMITED')

    def test_ordinary_404_and_malformed_cdx_are_not_mislabeled_as_restriction(self):
        for variant in ('empty','bad_json'):
            p,_,b,_=provider(variant)
            self.assertEqual(p.search(TASK),())
            self.assertFalse(b.stopped)
            statuses=[x['status'] for x in p.attempts]
            self.assertNotIn('ARCHIVE_ACCESS_RESTRICTED',statuses)
            self.assertNotIn('ARCHIVE_RATE_LIMITED',statuses)

    def test_direct_restriction_marks_budget_before_unwind(self):
        req=request();budget=CallBudget(req);gateway=TemporalGateway(req,[])
        client=RootRestrictedHTTP(429)
        p=ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=8)
        with self.assertRaisesRegex(ArchiveRestricted,'ARCHIVE_RATE_LIMITED'):
            p._get('https://web.archive.org/cdx/search/cdx?url=synthetic.example/')
        self.assertTrue(budget.stopped)
        self.assertEqual(budget.stop_reason,'ARCHIVE_RATE_LIMITED')

    def test_actual_http404_remains_nonterminal_unknown(self):
        req=request();budget=CallBudget(req);gateway=TemporalGateway(req,[])
        client=RootRestrictedHTTP(404)
        p=ArchivedWebsiteProvider(req,gateway,budget,client,max_requests=8)
        self.assertEqual(p.search(TASK),())
        self.assertFalse(budget.stopped)
        self.assertEqual(client.calls.__len__(),1)
        self.assertIn('HTTP_404',[x['status'] for x in p.attempts])


if __name__=='__main__':unittest.main()
