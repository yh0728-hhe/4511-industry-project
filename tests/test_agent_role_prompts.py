"""Offline regressions for real prompt wiring and critic-to-research handoff."""
from pathlib import Path
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]/'src'))
from closed_loop.agent_prompts import ROLE_BRIEFS, VERSION, prompt_fingerprint
from closed_loop.fixtures import request, FixtureProvider
from closed_loop.model_lead import ModelLead, LeadPlanOutput
from closed_loop.native_support import EvidenceReviewOutput
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.native_committee import NativeDialecticCommittee
from closed_loop.guards import CallBudget, TemporalGateway
from closed_loop.runtime import ClosedLoopRuntime
from closed_loop.offline_network import OfflineSocketGuard


class RecordingBackend(NativeFixtureBackend):
    def __init__(self):
        super().__init__()
        self.plans = []
        self.reviews = []
        self.contexts = []

    def generate(self, schema, messages, temperature):
        self.contexts.append(json.loads(messages[0].content.split('\n', 1)[1]))
        if schema is LeadPlanOutput:
            self.plans.append(json.loads(messages[-1].content))
        if schema is EvidenceReviewOutput:
            self.reviews.append(json.loads(messages[-1].content))
        return super().generate(schema, messages, temperature)


class RolePromptWiring(unittest.TestCase):
    def test_prompt_edit_invalidates_research_cache_even_without_manual_version_bump(self):
        req = request()
        key = req.cache_key('market', 'size')
        original = prompt_fingerprint()
        with patch.dict(ROLE_BRIEFS, {'market': 'Different mandate-specific market protocol'}):
            self.assertNotEqual(original, prompt_fingerprint())
            self.assertNotEqual(key, req.cache_key('market', 'size'))
        self.assertEqual(key, req.cache_key('market', 'size'))

    def test_lead_and_evidence_review_receive_actual_role_and_critic_context(self):
        with OfflineSocketGuard():
            req = request(max_model_calls=40)
            budget = CallBudget(req)
            backend = RecordingBackend()
            provider = FixtureProvider()
            runtime = ClosedLoopRuntime(req, TemporalGateway(req, provider.ledger), budget,
                ModelLead(backend, budget), NativeDialecticCommittee(backend, budget), provider)
            result = runtime.run()
        self.assertEqual(result['decision'], 'INVEST')  # synthetic fixture only
        self.assertEqual(backend.plans[0]['role_briefs'], ROLE_BRIEFS)
        self.assertEqual(len(backend.plans[0]['role_briefs']), 7)
        critiques = [a['critique'] for review in backend.reviews
            for stage in review['debate_trace'] for a in stage['arguments'] if a['critique']]
        self.assertTrue(any('verify retention' in text for text in critiques))
        self.assertTrue(all('not new verified facts' in r['trace_semantics'] for r in backend.reviews))
        self.assertTrue(all(c['prompt_bundle']['version'] == VERSION for c in backend.contexts))
        self.assertTrue(all(c['prompt_bundle']['fingerprint'] == prompt_fingerprint() for c in backend.contexts))


if __name__ == '__main__':
    unittest.main()
