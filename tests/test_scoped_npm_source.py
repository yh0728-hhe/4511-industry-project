"""Bounded scoped (@scope/name) npm source support; invented bytes only.

This exercises the deliberate, optional extension of verify_packages to
canonical lowercase unencoded `@scope/name` npm packages documented at
https://docs.npmjs.com/cli/v11/using-npm/scope/. No shell/network/model
calls are made; only the existing FakeHTTP test double is used.
"""
import json
import tempfile
import unittest
from pathlib import Path

from closed_loop.contracts import ResearchRequest
from closed_loop.discovered_package import DiscoveredPackageVerifier, parse_url
from closed_loop.fixtures import request
from closed_loop.guards import BudgetStopped, CallBudget, SourceCandidate, TemporalGateway
from closed_loop.npm_names import canonical_tarball_url, parse_npm_name
from closed_loop.package_registry import registry_url_allowed
from test_npm_source import tarball
from test_package_registry import FakeHTTP

SCOPE_NAME = '@acme/sample-sdk'
BASENAME = 'sample-sdk'
VERSION = '1.0.0'
WEB_URL = f'https://www.npmjs.com/package/{SCOPE_NAME}'
REGISTRY_URL = f'https://registry.npmjs.org/{SCOPE_NAME}'


def scoped_tarball(**kwargs):
    kwargs.setdefault('name', SCOPE_NAME)
    kwargs.setdefault('version', VERSION)
    raw, meta = tarball(**kwargs)
    meta['dist']['tarball'] = canonical_tarball_url(meta['name'], meta['version'])
    return raw, meta


def npm_payload(meta):
    return json.dumps(dict(name=meta['name'], time={meta['version']: meta['published']},
        versions={meta['version']: dict(name=meta['name'], version=meta['version'], dist=meta['dist'])})).encode()


class ScopedNpmSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'verification'
        self.req = request(max_search_calls=12, max_model_calls=24)
        self.budget = CallBudget(self.req)
        self.gateway = TemporalGateway(self.req, [])
        self.task = ResearchRequest('product', 'Read package documentation', self.req.company.company_id)

    def verifier(self, client):
        return DiscoveredPackageVerifier(self.req, self.gateway, self.budget, client, self.root)

    def test_canonical_tarball_url_shapes(self):
        self.assertEqual(canonical_tarball_url(SCOPE_NAME, VERSION),
            f'https://registry.npmjs.org/{SCOPE_NAME}/-/{BASENAME}-{VERSION}.tgz')
        self.assertEqual(canonical_tarball_url(BASENAME, VERSION),
            f'https://registry.npmjs.org/{BASENAME}/-/{BASENAME}-{VERSION}.tgz')
        self.assertIsNone(canonical_tarball_url('@Scope/name', VERSION))
        self.assertIsNone(canonical_tarball_url('@scope/na..me', VERSION))
        self.assertEqual(parse_npm_name(SCOPE_NAME), ('scoped', 'acme', BASENAME))

    def test_scoped_tarball_verified_through_real_gateway(self):
        raw, meta = scoped_tarball()
        client = FakeHTTP([npm_payload(meta), raw])
        v = self.verifier(client)
        candidate = v.verify_discovered_url(self.task, WEB_URL)
        self.assertIsInstance(candidate, SourceCandidate)
        fact, error = self.gateway.admit(candidate)
        self.assertIsNone(error)
        self.assertEqual(fact.topic, 'package-documentation')
        self.assertEqual(self.budget.used['search'], 2)
        self.assertEqual(len(client.calls), 2)

    def test_registry_url_alias_does_not_repeat_collection_and_journal_is_safe(self):
        raw, meta = scoped_tarball()
        client = FakeHTTP([npm_payload(meta), raw])
        v = self.verifier(client)
        first = v.verify_discovered_url(self.task, WEB_URL)
        second = v.verify_discovered_url(self.task, REGISTRY_URL)
        self.assertIs(first, second)
        self.assertEqual(len(client.calls), 2)
        journal_files = list((self.root).glob('*.jsonl'))
        self.assertEqual(len(journal_files), 1)
        self.assertNotIn('/', journal_files[0].name)

    def test_scope_manifest_mismatch_rejected(self):
        pkg = ('{"name":"@other/sample-sdk","version":"%s","homepage":"https://synthetic.example"}' % VERSION).encode()
        raw, meta = scoped_tarball(package_json=pkg)
        client = FakeHTTP([npm_payload(meta), raw])
        v = self.verifier(client)
        with self.assertRaisesRegex(BudgetStopped, 'REGISTRY_ARTIFACT_INVALID'):
            v.verify_discovered_url(self.task, WEB_URL)
        self.assertEqual(self.gateway._ledger, {})

    def test_malformed_scoped_urls_make_no_request(self):
        client = FakeHTTP([])
        v = self.verifier(client)
        for url in [
            'https://www.npmjs.com/package/@Acme/sample-sdk',
            'https://www.npmjs.com/package/@acme%2fsample-sdk',
            'https://u:secret@www.npmjs.com/package/@acme/sample-sdk',
            'https://www.npmjs.com/package/@acme/sample-sdk/extra',
            'https://www.npmjs.com/package/@acme/sample-sdk/1.0.0',
            'https://www.npmjs.com/package/@acme/sample-sdk?x=1',
            'https://registry.npmjs.org/@acme/sa..mple',
        ]:
            with self.subTest(url=url):
                self.assertIsNone(parse_url(url))
                self.assertIsNone(v.verify_discovered_url(self.task, url))
        self.assertEqual(client.calls, [])

    def test_future_release_is_unknown_and_not_downloaded(self):
        raw, meta = scoped_tarball(published='2025-01-01T00:00:00Z')
        client = FakeHTTP([npm_payload(meta)])
        v = self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(self.task, WEB_URL))
        self.assertEqual(len(client.calls), 1)
        self.assertFalse(self.budget.stopped)
        self.assertEqual(self.gateway._ledger, {})

    def test_different_scopes_keep_distinct_cache_keys_and_journals(self):
        raw1, meta1 = scoped_tarball()
        raw2, meta2 = scoped_tarball(name='@other/sample-sdk')
        client = FakeHTTP([npm_payload(meta1),raw1,npm_payload(meta2),raw2])
        v = self.verifier(client)
        first = v.verify_discovered_url(self.task, WEB_URL)
        second = v.verify_discovered_url(self.task, 'https://registry.npmjs.org/@other/sample-sdk')
        self.assertIsNotNone(first);self.assertIsNotNone(second)
        self.assertNotEqual(first.source_id,second.source_id)
        self.assertEqual(len(client.calls),4)
        journals=list(self.root.glob('*.jsonl'));self.assertEqual(len(journals),2)
        for path in journals:self.assertEqual(path.parent.resolve(),self.root.resolve())

    def test_bad_digest_stops_and_preserves_empty_ledger(self):
        raw,meta=scoped_tarball();client=FakeHTTP([npm_payload(meta),raw+b'tampered'])
        v=self.verifier(client)
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_ARTIFACT_INVALID'):
            v.verify_discovered_url(self.task,WEB_URL)
        self.assertEqual(self.gateway._ledger,{})
        with self.assertRaisesRegex(BudgetStopped,'REGISTRY_ARTIFACT_INVALID'):
            v.verify_discovered_url(self.task,REGISTRY_URL)
        self.assertEqual(len(client.calls),2)

    def test_scoped_transport_requires_same_name_and_plain_canonical_url(self):
        self.assertTrue(registry_url_allowed(REGISTRY_URL))
        self.assertTrue(registry_url_allowed(canonical_tarball_url(SCOPE_NAME,VERSION)))
        for url in ['https://registry.npmjs.org/@acme/sample-sdk/-/other-1.0.0.tgz',
                    'https://registry.npmjs.org/@a..cme/sample-sdk',
                    'https://registry.npmjs.org/@acme%2fsample-sdk',
                    'https://registry.npmjs.org:443/@acme/sample-sdk',
                    '\x00https://registry.npmjs.org/@acme/sample-sdk']:
            with self.subTest(url=url):self.assertFalse(registry_url_allowed(url))

    def test_scope_does_not_expand_wheel_namespace(self):
        client=FakeHTTP([]);v=self.verifier(client)
        self.assertIsNone(v.verify_discovered_url(self.task,'https://pypi.org/project/@acme/sample-sdk'))
        self.assertEqual(client.calls,[])

    def test_rate_limit_first_stop_no_retry(self):
        client = FakeHTTP([(429, REGISTRY_URL, {}, b'')])
        v = self.verifier(client)
        with self.assertRaisesRegex(BudgetStopped, 'REGISTRY_RATE_LIMITED'):
            v.verify_discovered_url(self.task, WEB_URL)
        with self.assertRaisesRegex(BudgetStopped, 'REGISTRY_RATE_LIMITED'):
            v.verify_discovered_url(self.task, REGISTRY_URL)
        self.assertEqual(len(client.calls), 1)


if __name__ == '__main__':
    unittest.main()
