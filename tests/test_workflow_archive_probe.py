"""Archive connectivity semantics with injected transport, no external network."""
from datetime import datetime
import json
from urllib.parse import parse_qs,urlparse
import unittest
from workflow_automation.archive_probe import probe
from closed_loop.archive_transport import HTTPResponse

class FakeArchive:
    def __init__(self,available=True):self.available=available;self.calls=[]
    def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
        self.calls.append(url);check_deadline()
        if not self.available:return HTTPResponse(403,url,{},b'')
        if '/cdx/' in url:
            original='https://'+parse_qs(urlparse(url).query)['url'][0]
            return HTTPResponse(200,url,{},json.dumps([['timestamp','original','statuscode','mimetype'],['20240320000000',original,'200','text/html']]).encode())
        return HTTPResponse(200,url,{'Memento-Datetime':'Wed, 20 Mar 2024 00:00:00 GMT','Content-Type':'text/html'},b'Invented archived company homepage for transport verification only. '*4)

class ArchiveProbeTests(unittest.TestCase):
    def test_blocked_archive_means_unknown_not_negative(self):
        client=FakeArchive(False);r=probe(client=client)
        self.assertEqual(r['status'],'NO_ADMITTED_SOURCE')
        self.assertEqual(r['archive_http_requests'],1)
        self.assertFalse(r['admitted_fact_metadata'])
        self.assertEqual(r['actual_model_calls'],0)
        self.assertFalse(r['y_read'])

    def test_verified_fixture_source_stays_clearly_not_model_result(self):
        client=FakeArchive();r=probe(client=client)
        self.assertEqual(r['status'],'HISTORICAL_SOURCE_ADMITTED_NOT_A_MODEL_RUN')
        self.assertEqual(r['archive_http_requests'],2)
        self.assertEqual(r['company']['name'],'Adagy Robotics')
        self.assertEqual(len(r['admitted_fact_metadata']),1)
        self.assertFalse(r['raw_bodies_saved'])
        self.assertFalse(r['historical_domain_ownership_independently_verified'])
        self.assertEqual(r['paid_api_calls'],0)

if __name__=='__main__':unittest.main()
