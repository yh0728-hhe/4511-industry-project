"""Invented registry bytes; no model, installation or network calls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from closed_loop.fixtures import request
from closed_loop.guards import CallBudget, TemporalGateway, BudgetStopped, SourceCandidate
from closed_loop.contracts import ResearchRequest
from closed_loop.discovered_package import DiscoveredPackageVerifier, parse_url
from closed_loop.discovered_research import DiscoveredResearchProvider
from closed_loop.archive_transport import ArchivedWebsiteProvider
from test_npm_source import tarball
from test_package_source import wheel
from test_package_registry import FakeHTTP
from test_discovered_research import DiscoveryHTTP, FakeDiscoveryAgent, discovery_result

NPM_URL='https://www.npmjs.com/package/sample-sdk'
PYPI_URL='https://pypi.org/project/sample-sdk/'


def npm_payload(meta):
    return json.dumps(dict(name=meta['name'],time={meta['version']:meta['published']},
        versions={meta['version']:dict(name=meta['name'],version=meta['version'],dist=meta['dist'])})).encode()


class DiscoveredPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'verification'
        self.req=request(max_search_calls=12,max_model_calls=24)
        self.budget=CallBudget(self.req);self.gateway=TemporalGateway(self.req,[])
        self.task=ResearchRequest('product','Read package documentation',self.req.company.company_id)
    def verifier(self,client):
        return DiscoveredPackageVerifier(self.req,self.gateway,self.budget,client,self.root)

    def test_npm_two_gets_return_candidate_through_real_gateway(self):
        raw,meta=tarball();client=FakeHTTP([npm_payload(meta),raw]);v=self.verifier(client)
        candidate=v.verify_discovered_url(self.task,NPM_URL)
        self.assertIsInstance(candidate,SourceCandidate)
        fact,error=self.gateway.admit(candidate)
        self.assertIsNone(error);self.assertEqual(fact.topic,'package-documentation')
        self.assertEqual(self.budget.used['search'],2)
        self.assertEqual(self.budget.used['model'],0)
        self.assertEqual(len(client.calls),2)
        self.assertEqual(v.receipts[0]['evidence_scope'],'ATTRIBUTED_PACKAGE_DOCUMENTATION')

    def test_wheel_normalized_alias_does_not_repeat_collection(self):
        raw,meta=wheel();client=FakeHTTP([json.dumps({'releases':{'1.0':[meta]}}).encode(),raw])
        v=self.verifier(client);first=v.verify_discovered_url(self.task,PYPI_URL)
        second=v.verify_discovered_url(self.task,'https://pypi.org/project/sample_sdk')
        self.assertIs(first,second);self.assertIsInstance(first,SourceCandidate)
        self.assertEqual(len(client.calls),2)
        self.assertEqual(len(v.receipts),1)

    def test_404_miss_cached_across_url_aliases(self):
        client=FakeHTTP([(404,'https://registry.npmjs.org/sample-sdk',{},b'')]);v=self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(self.task,NPM_URL))
        self.assertIsNone(v.verify_discovered_url(self.task,'https://registry.npmjs.org/sample-sdk'))
        self.assertEqual(len(client.calls),1)
        self.assertEqual(self.gateway._ledger,{})

    def test_future_release_is_unknown_and_not_downloaded(self):
        raw,meta=tarball(published='2025-01-01T00:00:00Z')
        client=FakeHTTP([npm_payload(meta)]);v=self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(self.task,NPM_URL))
        self.assertEqual(len(client.calls),1);self.assertFalse(self.budget.stopped)
        self.assertEqual(self.gateway._ledger,{})

    def test_wrong_domain_is_terminal_and_never_registered(self):
        raw,meta=tarball(readme=b'Other docs https://other.example/docs')
        client=FakeHTTP([npm_payload(meta),raw]);v=self.verifier(client)
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_ARTIFACT_INVALID'):
            v.verify_discovered_url(self.task,NPM_URL)
        self.assertEqual(len(client.calls),2);self.assertEqual(self.gateway._ledger,{})

    def test_rate_limit_first_stop_no_retry(self):
        client=FakeHTTP([(429,'https://registry.npmjs.org/sample-sdk',{},b'')]);v=self.verifier(client)
        for url in [NPM_URL,'https://registry.npmjs.org/sample-sdk']:
            with self.assertRaisesRegex(BudgetStopped,'REGISTRY_RATE_LIMITED'):
                v.verify_discovered_url(self.task,url)
        self.assertEqual(len(client.calls),1)

    def test_peers_and_unsupported_urls_make_no_request(self):
        client=FakeHTTP([]);v=self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(replace(self.task,subject_id='peer'),NPM_URL))
        for url in ['https://pypi.org:bad/project/sample-sdk','https://pypi.org:443/project/sample-sdk',
                'http://pypi.org/project/sample-sdk','https://pypi.org/project/sample-sdk/1.0/',
                'https://pypi.org/project/a..b','https://evil.example/package/sample-sdk',
                'https://u:secret@pypi.org/project/sample-sdk',
                'https://pypi.org/project/sample-sdk?x=1','https://pypi.org/project/sample-sdk#x',
                'https://pypi.org/project/sample%2dsdk', ' https://pypi.org/project/sample-sdk']:
            with self.subTest(url=url):
                self.assertIsNone(parse_url(url));self.assertIsNone(v.verify_discovered_url(self.task,url))
        self.assertEqual(client.calls,[])
        self.assertNotIn('secret',json.dumps(v.trace))

    def test_oversized_readme_held_without_registering_or_older_fallback(self):
        body=('SDK docs https://synthetic.example/docs '+''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(110))).encode()
        raw,meta=tarball(readme=body);client=FakeHTTP([npm_payload(meta),raw]);v=self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(self.task,NPM_URL))
        self.assertEqual(v.receipts[0]['outcome'],'held_oversized')
        self.assertFalse(self.budget.stopped);self.assertEqual(self.gateway._ledger,{})
        self.assertEqual(len(client.calls),2)

    def test_context_mismatch_before_directory_creation(self):
        other=replace(self.req,mandate='different')
        with self.assertRaises(ValueError):
            DiscoveredPackageVerifier(self.req,TemporalGateway(other,[]),self.budget,FakeHTTP([]),self.root)
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            DiscoveredPackageVerifier(self.req,self.gateway,CallBudget(other),FakeHTTP([]),self.root)
        self.assertFalse(self.root.exists())

    def test_existing_output_is_refused_without_requests(self):
        self.root.mkdir();client=FakeHTTP([])
        with self.assertRaises(FileExistsError):self.verifier(client)
        self.assertEqual(client.calls,[])

    def test_discovery_routes_package_without_publisher_or_archive_requests(self):
        raw,meta=tarball();registry=FakeHTTP([npm_payload(meta),raw]);v=self.verifier(registry)
        http=DiscoveryHTTP();archive=ArchivedWebsiteProvider(self.req,self.gateway,self.budget,client=http,max_requests=12)
        provider=DiscoveredResearchProvider(self.req,self.gateway,self.budget,
            lambda task:FakeDiscoveryAgent(self.req,self.budget,discovery_result([NPM_URL])),archive,package_verifier=v)
        candidates=provider.search(self.task)
        self.assertEqual(len(candidates),1);self.assertIsInstance(candidates[0],SourceCandidate)
        self.assertEqual(http.calls,[]);self.assertEqual(len(registry.calls),2)
        self.assertEqual(provider.search(self.task),candidates)
        self.assertEqual(len(registry.calls),2)


if __name__=='__main__':unittest.main()
