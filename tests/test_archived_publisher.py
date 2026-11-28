"""Offline tests for the third-party-publisher archived-binding verifier.

All HTML/CDX/memento fixtures are invented; no real CLI/HTTP/model is used.
Proves only a historical headline+link relationship to an archived publisher
snapshot -- never editorial independence or claim accuracy.
"""
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.archive_transport import HTTPResponse
from closed_loop.archived_publisher import ArchivedPublisherVerifier, PUBLISHER_CONTEXT_TOPIC
from closed_loop.contracts import CompanySeed, ResearchRequest
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget, SourceCandidate, TemporalGateway

COMPANY = CompanySeed('TARGET_CO', 'Target Co', 'company.example')
PUBLISHER_URL = 'https://publisher.example/article'
GOOD_HTML = (
    b'<html><head><title>Target Co Raises Funding</title></head><body>'
    b'<h1>Target Co Raises Funding</h1>'
    b'<p>Sponsored commentary from Other Org about the round.</p>'
    b'<a href="https://company.example/about">Visit Target Co site</a>'
    b'</body></html>'
)


class FakeClient:
    def __init__(self, html=GOOD_HTML, memento='Wed, 20 Mar 2024 00:00:00 GMT', replay_status=200,
                 cdx_original=None, cdx_ts='20240320000000'):
        self.calls = []
        self.html = html.replace(b'<body>',b'<body><article>').replace(b'</body>',b'</article></body>')
        self.memento = memento
        self.replay_status = replay_status
        self.cdx_original = cdx_original
        self.cdx_ts = cdx_ts

    def get(self, url, timeout, max_bytes, check_deadline=lambda: None):
        check_deadline()
        self.calls.append(url)
        if '/cdx/' in url:
            requested_original = 'https://' + parse_qs(urlparse(url).query)['url'][0]
            original = self.cdx_original or requested_original
            return HTTPResponse(200, url, {}, json.dumps([
                ['timestamp', 'original', 'statuscode', 'mimetype'],
                [self.cdx_ts, original, '200', 'text/html']]).encode())
        if self.replay_status != 200:
            return HTTPResponse(self.replay_status, url, {}, b'')
        headers = {'Content-Type': 'text/html'}
        if self.memento:
            headers['Memento-Datetime'] = self.memento
        return HTTPResponse(200, url, headers, self.html)


def build(client=None, cap=10):
    req = request(company=COMPANY, max_search_calls=cap, max_model_calls=cap)
    budget = CallBudget(req)
    gateway = TemporalGateway(req, [])
    verifier = ArchivedPublisherVerifier(req, gateway, budget, client=client or FakeClient(), max_requests=cap)
    return req, budget, gateway, verifier


def task(req, subject=None):
    return ResearchRequest('other', 'Find press coverage', req.company.company_id, subject)


class ArchivedPublisherVerifierTests(unittest.TestCase):
    def test_valid_headline_and_link_admits_new_topic_with_two_http_calls(self):
        req, budget, gateway, verifier = build()
        candidate = verifier.verify_discovered_url(task(req), PUBLISHER_URL)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.topic, PUBLISHER_CONTEXT_TOPIC)
        fact, rejection = gateway.admit(candidate)
        self.assertIsNotNone(fact)
        self.assertIsNone(rejection)
        self.assertEqual(len(verifier.client.calls), 2)
        receipt = next(r for r in verifier.receipts if r['source_id'] == candidate.source_id)
        self.assertEqual(receipt['editorial_independence'], 'UNKNOWN')

    def test_missing_headline_holds_no_fact(self):
        html = GOOD_HTML.replace(b'Target Co Raises Funding', b'Some Other Startup Raises Funding')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_name_present_but_no_matching_link_holds(self):
        html = (b'<html><head><title>Target Co Raises Funding</title></head><body>'
                b'<h1>Target Co Raises Funding</h1>'
                b'<a href="https://other.example/x">Unrelated link</a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_link_present_but_label_does_not_match_holds(self):
        html = (b'<html><head><title>Target Co Raises Funding</title></head><body>'
                b'<h1>Target Co Raises Funding</h1>'
                b'<a href="https://company.example/about">Click here</a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_hidden_script_name_does_not_count(self):
        html = (b'<html><head><title>Press roundup</title></head><body>'
                b'<script>var x = "Target Co";</script>'
                b'<a href="https://company.example/about">Target Co</a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_image_alt_counts_as_link_label(self):
        html = (b'<html><head><title>Target Co Raises Funding</title></head><body>'
                b'<h1>Target Co Raises Funding</h1>'
                b'<p>Invented historical article body with enough readable content to meet the inherited body minimum.</p>'
                b'<a href="https://company.example/about"><img alt="Target Co logo"/></a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        candidate = verifier.verify_discovered_url(task(req), PUBLISHER_URL)
        self.assertIsNotNone(candidate)

    def test_foreign_link_wrong_domain_holds(self):
        html = (b'<html><head><title>Target Co Raises Funding</title></head><body>'
                b'<h1>Target Co Raises Funding</h1>'
                b'<a href="https://unrelated.example/about">Target Co official site</a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_authenticated_link_rejected(self):
        html = (b'<html><head><title>Target Co Raises Funding</title></head><body>'
                b'<h1>Target Co Raises Funding</h1>'
                b'<a href="https://user:pass@company.example/about">Target Co site</a>'
                b'</body></html>')
        req, budget, gateway, verifier = build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_future_capture_excluded(self):
        req, budget, gateway, verifier = build(FakeClient(cdx_ts='20250320000000'))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_memento_mismatch_held(self):
        req, budget, gateway, verifier = build(FakeClient(memento='Thu, 21 Mar 2024 00:00:00 GMT'))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_restriction_terminal_no_extra_http(self):
        req, budget, gateway, verifier = build(FakeClient(replay_status=429))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))
        self.assertTrue(budget.stopped)
        calls_after = len(verifier.client.calls)
        with self.assertRaises(Exception):
            verifier.verify_discovered_url(task(req), 'https://publisher.example/other')
        self.assertEqual(len(verifier.client.calls), calls_after)

    def test_exact_url_mismatch_from_cdx_held(self):
        req, budget, gateway, verifier = build(FakeClient(cdx_original='https://different.example/article'))
        self.assertIsNone(verifier.verify_discovered_url(task(req), PUBLISHER_URL))

    def test_official_domain_defers_to_first_party_verifier_zero_http(self):
        req, budget, gateway, verifier = build()
        self.assertIsNone(verifier.verify_discovered_url(task(req), 'https://company.example/press'))
        self.assertEqual(verifier.client.calls, [])

    def test_peer_subject_held_zero_http_before_any_request(self):
        req, budget, gateway, verifier = build()
        self.assertIsNone(verifier.verify_discovered_url(task(req, subject='PEER_CO'), PUBLISHER_URL))
        self.assertEqual(verifier.client.calls, [])

    def test_task_company_mismatch_raises(self):
        req, budget, gateway, verifier = build()
        with self.assertRaises(ValueError):
            verifier.verify_discovered_url(ResearchRequest('other', 'q', 'OTHER_COMPANY'), PUBLISHER_URL)

    def test_malformed_url_variants_rejected_without_http(self):
        req, budget, gateway, verifier = build()
        for bad in ('https://user:secret@publisher.example/article', 'ftp://publisher.example/article',
                    'https://publisher.example:8443/article', 'https://publisher.example/article#frag',
                    'https://publisher.example/../secret', 'https://publisher.example/' + 'x' * 600,
                    'https://publisher.example/article;x=1'):
            with self.subTest(bad=bad):
                self.assertIsNone(verifier.verify_discovered_url(task(req), bad))
        self.assertEqual(verifier.client.calls, [])

    def test_declared_editorial_independence_is_unknown_not_truth_verified(self):
        req, budget, gateway, verifier = build()
        candidate = verifier.verify_discovered_url(task(req), PUBLISHER_URL)
        receipt = next(r for r in verifier.receipts if r['source_id'] == candidate.source_id)
        self.assertEqual(receipt['editorial_independence'], 'UNKNOWN')
        self.assertNotIn('verified_true', receipt)

    def test_gateway_admit_rejects_fabricated_candidate_when_binding_never_registered(self):
        req, budget, gateway, verifier = build()
        fabricated = SourceCandidate('fabricated-id', PUBLISHER_URL, req.company.company_id,
            PUBLISHER_CONTEXT_TOPIC, 'Pretend verified publisher text with no registered proof.')
        fact, rejection = gateway.admit(fabricated)
        self.assertIsNone(fact)
        self.assertEqual(rejection['reason'], 'UNVERIFIED_SOURCE')


    def test_headline_name_cannot_be_assembled_across_title_and_h1(self):
        html=GOOD_HTML.replace(b'<title>Target Co Raises Funding</title>',b'<title>Target</title>').replace(b'<h1>Target Co Raises Funding</h1>',b'<h1>Co raises funding</h1>')
        req,budget,gateway,verifier=build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req),PUBLISHER_URL))
    def test_www_link_alias_not_assumed_to_be_company_anchor(self):
        html=GOOD_HTML.replace(b'https://company.example/about',b'https://www.company.example/about')
        req,budget,gateway,verifier=build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req),PUBLISHER_URL))
    def test_malformed_link_port_is_held_without_crashing(self):
        html=GOOD_HTML.replace(b'https://company.example/about',b'https://company.example:bad/about')
        req,budget,gateway,verifier=build(FakeClient(html=html))
        self.assertIsNone(verifier.verify_discovered_url(task(req),PUBLISHER_URL))
    def test_tiny_context_budget_does_not_admit_only_a_generated_preface(self):
        req,budget,gateway,verifier=build()
        verifier.max_text_chars=100
        self.assertIsNone(verifier.verify_discovered_url(task(req),PUBLISHER_URL))


    def test_navigation_is_not_admitted_as_target_company_content(self):
        html=GOOD_HTML.replace(b'<body>',b'<body><nav>NAV_SENTINEL unrelated publisher tools</nav>')
        req,budget,gateway,verifier=build(FakeClient(html=html))
        candidate=verifier.verify_discovered_url(task(req),PUBLISHER_URL)
        self.assertIsNotNone(candidate)
        self.assertNotIn('NAV_SENTINEL',candidate.text)
    def test_missing_semantic_article_or_main_context_stays_unknown(self):
        client=FakeClient();client.html=GOOD_HTML
        req,budget,gateway,verifier=build(client)
        self.assertIsNone(verifier.verify_discovered_url(task(req),PUBLISHER_URL))
    def test_main_context_supported_when_article_is_absent(self):
        client=FakeClient();client.html=client.html.replace(b'<article>',b'<main>').replace(b'</article>',b'</main>')
        req,budget,gateway,verifier=build(client)
        candidate=verifier.verify_discovered_url(task(req),PUBLISHER_URL)
        self.assertIsNotNone(candidate)


if __name__ == '__main__':
    unittest.main()
