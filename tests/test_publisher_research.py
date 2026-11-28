"""Injected archive/publication composition; no real traffic or semantic accuracy claim."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.archive_transport import ArchivedWebsiteProvider
from closed_loop.archived_publisher import ArchivedPublisherVerifier,PUBLISHER_CONTEXT_TOPIC
from closed_loop.discovered_research import DiscoveredResearchProvider
from closed_loop.guards import CallBudget
from closed_loop.contracts import ResearchRequest
from test_archived_publisher import build,task,FakeClient,PUBLISHER_URL
from test_discovered_research import FakeDiscoveryAgent,discovery_result

class PublisherResearchTests(unittest.TestCase):
    def provider(self,urls=None,max_sources=2):
        req,budget,gateway,publisher=build()
        official=ArchivedWebsiteProvider(req,gateway,budget,client=publisher.client)
        made=[]
        def factory(t):
            made.append(t);return FakeDiscoveryAgent(req,budget,discovery_result(urls or [PUBLISHER_URL]))
        provider=DiscoveredResearchProvider(req,gateway,budget,factory,official,
            max_sources=max_sources,publisher_verifier=publisher)
        return req,budget,gateway,publisher,official,provider,made
    def test_publisher_lead_enters_gateway_only_after_independent_proof(self):
        req,b,g,pub,official,provider,made=self.provider()
        candidates=provider.search(task(req))
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0].topic,PUBLISHER_CONTEXT_TOPIC)
        self.assertIsNotNone(g.admit(candidates[0])[0])
        self.assertEqual(len(pub.client.calls),2)
        self.assertEqual(b.used['search'],2) # double discovery agent adds no synthetic charge
    def test_default_no_publisher_verifier_keeps_foreign_url_held(self):
        req,b,g,pub,official,provider,made=self.provider()
        provider.publisher_verifier=None
        self.assertEqual(provider.search(task(req)),())
        self.assertEqual(pub.client.calls,[])
    def test_optional_context_mismatch_rejected(self):
        req,b,g,pub,official,provider,made=self.provider()
        pub.call_budget=CallBudget(req)
        with self.assertRaises(ValueError):
            DiscoveredResearchProvider(req,g,b,lambda t:None,official,publisher_verifier=pub)
    def test_official_lead_is_not_starved_by_first_external_hit(self):
        req,b,g,pub,official,provider,made=self.provider([PUBLISHER_URL,'https://company.example/'],max_sources=1)
        candidates=provider.search(task(req))
        self.assertEqual(len(candidates),1)
        self.assertNotEqual(candidates[0].topic,PUBLISHER_CONTEXT_TOPIC)
        self.assertEqual(pub.receipts,[])
    def test_publisher_observed_company_link_is_independently_verified_without_new_search(self):
        req,b,g,pub,official,provider,made=self.provider()
        provider.search(task(req))
        hints=provider.link_hints()
        self.assertTrue(any(h['path']=='/about' and not h['target_content_verified'] for h in hints))
        candidate=provider.search(ResearchRequest('team','Inspect company about page',req.company.company_id,source_path='/about'))
        self.assertEqual(len(made),1)
        self.assertTrue(candidate)
        self.assertEqual(len(pub.client.calls),4)
        self.assertNotEqual(candidate[0].topic,PUBLISHER_CONTEXT_TOPIC)
    def test_publisher_cache_configuration_does_not_reuse_disabled_provider_namespace(self):
        req,b,g,pub,official,provider,made=self.provider()
        other=DiscoveredResearchProvider(req,g,b,lambda t:None,official)
        self.assertNotEqual(provider.cache_namespace,other.cache_namespace)
if __name__=='__main__':unittest.main()
