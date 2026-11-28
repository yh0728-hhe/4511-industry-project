"""Invented WARC records only. No HTTP, model, or real-source admission."""
import base64
from dataclasses import replace
from datetime import datetime,timezone
import gzip
import hashlib
import unittest

from closed_loop.archive_transport import HTTPResponse
from closed_loop.commoncrawl_index import CapturePointer
from closed_loop.commoncrawl_record import verify_commoncrawl_record
from closed_loop.contracts import CompanySeed
from closed_loop.fixtures import request
from closed_loop.guards import TemporalGateway

COLLECTION='CC-MAIN-2024-10'
URL='https://exampleco.com/'
DATE=datetime(2024,3,2,7,58,21,tzinfo=timezone.utc)
HTML=b'<html><head><title>Example Co</title></head><body><h1>Example Co</h1><p>Example Co states it provides a technical workflow product. No independent adoption evidence is supplied.</p></body></html>'
FILENAME='crawl-data/CC-MAIN-2024-10/segments/1707947475757.50/warc/CC-MAIN-20240302052634-20240302082634-00381.warc.gz'


def sha1(raw):return base64.b32encode(hashlib.sha1(raw).digest()).decode()


def fixture(*,html=HTML,warc_changes=None,http_extra=(),warc_extra=(),
        http_status='HTTP/1.1 200 OK',extra_tail=b'',extra_member=b''):
    http_fields=[('Content-Type','text/html; charset=utf-8'),('Content-Length',str(len(html)))]
    http_fields.extend(http_extra)
    block=(http_status+'\r\n'+'\r\n'.join(k+': '+v for k,v in http_fields)+'\r\n\r\n').encode()+html
    fields=dict([('WARC-Type','response'),('WARC-Date','2024-03-02T07:58:21Z'),
        ('WARC-Target-URI',URL),('WARC-Record-ID','<urn:uuid:92283950-ef2f-4d72-b224-f54c6ec90bb0>'),
        ('Content-Type','application/http; msgtype=response'),('Content-Length',str(len(block))),
        ('WARC-Block-Digest','sha1:'+sha1(block)),('WARC-Payload-Digest','sha1:'+sha1(html))])
    fields.update(warc_changes or {})
    lines=list(fields.items())+list(warc_extra)
    raw=('WARC/1.1\r\n'+'\r\n'.join(k+': '+v for k,v in lines)+'\r\n\r\n').encode()+block+b'\r\n\r\n'+extra_tail
    zipped=gzip.compress(raw,mtime=0)+extra_member
    pointer=CapturePointer(URL,DATE,sha1(html),FILENAME,120,len(zipped))
    headers={'Content-Length':str(len(zipped)),'Content-Range':f'bytes 120-{119+len(zipped)}/9000000'}
    response=HTTPResponse(206,pointer.data_url,headers,zipped)
    req=request(company=CompanySeed('SYNTHETIC_CC','Example Co','exampleco.com'))
    return pointer,response,req


def verify(items=None,**changes):
    p,r,req=items or fixture()
    return verify_commoncrawl_record(p,r,request=req,collection=COLLECTION,**changes)


class CommonCrawlRecordTests(unittest.TestCase):
    def test_plain_complete_capture_passes_same_existing_gateway_without_network(self):
        p,response,req=fixture();candidate,record,receipt=verify((p,response,req))
        fact,error=TemporalGateway(req,[record]).admit(candidate)
        self.assertIsNone(error);self.assertEqual(fact.url,URL)
        self.assertEqual(record.proof_kind,'READABLE_ARCHIVE')
        self.assertEqual(record.availability_upper_bound,DATE)
        self.assertFalse(receipt['semantic_claim_truth_certified'])
        self.assertFalse(receipt['domain_ownership_independently_certified'])
        self.assertEqual(receipt['compressed_sha256'],hashlib.sha256(response.body).hexdigest())
        self.assertEqual(receipt['source_http_requests'],0)
    def test_archive_integrity_never_releases_investment_without_claim_review(self):
        from closed_loop.analysis_acceptance import gate_analysis
        p,response,req=fixture();candidate,record,_=verify((p,response,req))
        fact,error=TemporalGateway(req,[record]).admit(candidate)
        self.assertIsNone(error)
        thesis=dict(summary='Publisher makes technical product claims.',
            pro_case=['Published product description is available.'],
            con_case=['Business assertions have not been independently corroborated.'],
            uncertainty_notes=['Archived text is not proof of adoption.'],
            decision_changing_questions=['What independently substantiates adoption?'],
            next_checks=['Review independent evidence.'],cited_fact_ids=[fact.fact_id])
        for decision in ('INVEST','PASS'):
            proposal=dict(decision=decision,rationale='A document is available.',
                admitted_fact_ids=[fact.fact_id],essential_gaps=[],thesis=thesis)
            out=gate_analysis(proposal,'synthetic-warc-source-bound-gate')
            self.assertEqual(out['decision'],'MORE_DILIGENCE')
            self.assertEqual(out['acceptance_state'],'NOT_REVIEWED')
            self.assertFalse(out['semantic_support_certified'])

    def test_range_response_status_origin_length_and_case_duplicates(self):
        p,r,req=fixture()
        bads=[replace(r,status=200),replace(r,status=True),replace(r,url=URL),
            replace(r,body=r.body[:-1]),replace(r,headers=dict(r.headers,**{'content-range':r.headers['Content-Range']})),
            replace(r,headers=dict(r.headers,**{'Content-Range':'bytes 121-999/1000'})),
            replace(r,headers=dict(r.headers,**{'Content-Length':'1'})),
            replace(r,headers=dict(r.headers,**{'Content-Encoding':'gzip'}))]
        for bad in bads:
            with self.subTest(response=bad.status):
                with self.assertRaises(ValueError):verify((p,bad,req))
    def test_total_range_must_cover_end_and_not_use_unknown_star(self):
        p,r,req=fixture()
        for value in (f'bytes 120-{119+p.length}/*',f'bytes 120-{119+p.length}/{119+p.length}'):
            with self.assertRaises(ValueError):verify((p,replace(r,headers=dict(r.headers,**{'Content-Range':value})),req))
    def test_gzip_bomb_incomplete_members_and_extra_bytes_held(self):
        cases=[fixture(html=HTML+b'x'*300000),fixture(extra_member=gzip.compress(b'extra')),
            fixture(extra_tail=b'extra')]
        for item in cases:
            with self.assertRaises(ValueError):verify(item)
        p,r,req=fixture();broken=r.body[:-5]
        p=replace(p,length=len(broken));r=replace(r,body=broken,headers={
            'Content-Length':str(len(broken)),'Content-Range':f'bytes 120-{119+len(broken)}/9000000'})
        with self.assertRaises(ValueError):verify((p,r,req))
    def test_warc_url_date_type_and_truncation_must_match(self):
        for changes in ({'WARC-Type':'revisit'},{'WARC-Target-URI':'https://other.com/'},
            {'WARC-Date':'2024-03-03T07:58:21Z'},{'WARC-Date':'2024-03-02T07:58:21'},
            {'WARC-Truncated':'length'},{'WARC-Segment-Number':'1'},
            {'Content-Type':'application/http;msgtype=request'}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):verify(fixture(warc_changes=changes))
    def test_subsecond_warc_date_preserves_real_availability_upper_bound(self):
        item=fixture(warc_changes={'WARC-Date':'2024-03-02T07:58:21.123Z'})
        _,record,_=verify(item)
        self.assertEqual(record.availability_upper_bound.microsecond,123000)
        p,r,req=item
        with self.assertRaises(ValueError):verify((p,r,replace(req,as_of=DATE)))
    def test_warc_and_index_digests_checked_separately(self):
        for changes in ({'WARC-Block-Digest':'sha1:'+'A'*32},{'WARC-Payload-Digest':'sha1:'+'A'*32}):
            with self.assertRaises(ValueError):verify(fixture(warc_changes=changes))
        p,r,req=fixture()
        with self.assertRaises(ValueError):verify((replace(p,digest_sha1_base32='B'*32),r,req))
    def test_critical_duplicate_warc_and_http_headers_rejected(self):
        for item in (fixture(warc_extra=[('WARC-Date','2024-03-02T07:58:21Z')]),
            fixture(http_extra=[('Content-Length',str(len(HTML)))])):
            with self.assertRaises(ValueError):verify(item)
    def test_optional_repeatable_warc_protocols_are_not_overwritten(self):
        candidate,_,_=verify(fixture(warc_extra=[('WARC-Protocol','h2'),('WARC-Protocol','tls/1.3')]))
        self.assertIn('Example Co',candidate.text)
    def test_http_redirect_chunked_encoded_and_non_html_held(self):
        for item in (fixture(http_status='HTTP/1.1 301 Moved'),
            fixture(http_extra=[('Transfer-Encoding','chunked')]),
            fixture(http_extra=[('Content-Encoding','gzip')]),
            fixture(http_extra=[('Content-Type','application/json')])):
            with self.assertRaises(ValueError):verify(item)
    def test_foreign_domain_pointer_or_naive_capture_cannot_become_proof(self):
        p,r,req=fixture()
        bads=[replace(p,url='https://other.com/'),replace(p,offset=True),
            replace(p,filename=p.filename.replace('/warc/','/../warc/')),
            replace(p,captured_at=p.captured_at.replace(tzinfo=None))]
        for bad in bads:
            with self.assertRaises(ValueError):verify((bad,r,req))
        with self.assertRaises(ValueError):verify((p,r,replace(req,company=CompanySeed('OTHER','Example Co','other.com'))))
    def test_headline_binding_and_visible_text_required(self):
        for html in (HTML.replace(b'Example Co',b'Other Co'),b'<title>Example Co</title>',
            b'<title>Other Co</title><script>Example Co does things in hidden script.</script>'+b'x'*50):
            with self.assertRaises(ValueError):verify(fixture(html=html))
    def test_all_failures_sanitized_and_limits_strict(self):
        for changes in ({'max_decompressed_bytes':True},{'max_text_chars':6001},
            {'max_decompressed_bytes':0},{'max_decompressed_bytes':1048577}):
            with self.assertRaisesRegex(ValueError,'^INVALID_COMMONCRAWL_RECORD$'):verify(**changes)
        with self.assertRaisesRegex(ValueError,'^INVALID_COMMONCRAWL_RECORD$'):verify(fixture(html=b'PRIVATE_BODY'))


if __name__=='__main__':unittest.main()
