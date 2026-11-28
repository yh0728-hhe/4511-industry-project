"""Model-facing payloads must not leak canonical post-cutoff identifiers."""
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
from closed_loop.model_identity import model_subject_id, present_payload, decode_subject_id
from closed_loop.native_support import NativeBinding, HumanMessage
from closed_loop.native_committee import new_state, NativeConfig
from closed_loop.guards import CallBudget


FUTURE_PRIMARY = 'future_brand_2026'
PEER = 'other_peer_co'


def make_view(**overrides):
    base = dict(
        company_id=FUTURE_PRIMARY,
        mandate='Evaluate retention.',
        as_of='2026-06-01T00:00:00+00:00',
        fact_revision=1,
        argument_revision=0,
        qa_pairs=(dict(
            question='What is the supported evidence for retention about this evidence subject?',
            answer='Retention is strong; see https://hatchet.run for the public writeup about OldBrand old.example.',
            fact_id='hatchet',
            source_id='source-1',
            url='https://hatchet.run',
            subject_id=FUTURE_PRIMARY,
            available_by='2026-01-01T00:00:00+00:00',
            reliability='READABLE_ARCHIVE',
        ),),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class ModelIdentityUnitTests(unittest.TestCase):
    def test_model_subject_id_is_stable_for_primary(self):
        self.assertEqual(model_subject_id(FUTURE_PRIMARY), model_subject_id(FUTURE_PRIMARY, FUTURE_PRIMARY))

    def test_model_subject_id_differs_for_peer(self):
        self.assertNotEqual(model_subject_id(FUTURE_PRIMARY), model_subject_id(FUTURE_PRIMARY, PEER))

    def test_model_subject_id_rejects_empty_inputs(self):
        with self.assertRaises(ValueError):model_subject_id('')
        with self.assertRaises(ValueError):model_subject_id(FUTURE_PRIMARY, '')
        with self.assertRaises(ValueError):model_subject_id(None)

    def test_model_subject_id_token_never_contains_canonical_id(self):
        token = model_subject_id(FUTURE_PRIMARY)
        self.assertNotIn(FUTURE_PRIMARY, token)
        self.assertTrue(token.startswith('subject_'))

    def test_present_payload_encodes_only_identifier_keys_without_mutation(self):
        original = dict(company_id=FUTURE_PRIMARY, subject_id=PEER,
            name='future_brand_2026 Inc', url='https://future_brand_2026.example/press')
        encoded = present_payload(original, FUTURE_PRIMARY)
        self.assertEqual(original['company_id'], FUTURE_PRIMARY)
        self.assertEqual(original['subject_id'], PEER)
        self.assertNotIn(FUTURE_PRIMARY, encoded['company_id'])
        self.assertNotIn(PEER, encoded['subject_id'])
        self.assertEqual(encoded['name'], 'future_brand_2026 Inc')
        self.assertEqual(encoded['url'], 'https://future_brand_2026.example/press')

    def test_present_payload_recurses_into_nested_lists_and_dicts(self):
        original = dict(evidence=[dict(subject_id=FUTURE_PRIMARY, answer='see https://hatchet.run'),
            dict(subject_id=PEER, answer='unrelated text')], tags=('x', 'y'))
        encoded = present_payload(original, FUTURE_PRIMARY)
        self.assertEqual(encoded['evidence'][0]['answer'], 'see https://hatchet.run')
        self.assertEqual(encoded['evidence'][1]['answer'], 'unrelated text')
        self.assertNotIn(FUTURE_PRIMARY, encoded['evidence'][0]['subject_id'])
        self.assertNotIn(PEER, encoded['evidence'][1]['subject_id'])
        self.assertEqual(encoded['tags'], ('x', 'y'))

    def test_present_payload_is_idempotent_on_already_encoded_tokens(self):
        once = present_payload(dict(subject_id=FUTURE_PRIMARY), FUTURE_PRIMARY)
        twice = present_payload(once, FUTURE_PRIMARY)
        self.assertEqual(once, twice)

    def test_present_payload_preserves_none_identifiers(self):
        encoded = present_payload(dict(subject_id=None, company_id=FUTURE_PRIMARY), FUTURE_PRIMARY)
        self.assertIsNone(encoded['subject_id'])

    def test_decode_subject_id_roundtrips_known_primary_and_peer(self):
        primary_token = model_subject_id(FUTURE_PRIMARY)
        peer_token = model_subject_id(FUTURE_PRIMARY, PEER)
        self.assertEqual(decode_subject_id(primary_token, FUTURE_PRIMARY, (PEER,)), FUTURE_PRIMARY)
        self.assertEqual(decode_subject_id(peer_token, FUTURE_PRIMARY, (PEER,)), PEER)

    def test_decode_subject_id_passes_through_none_and_unknown(self):
        self.assertIsNone(decode_subject_id(None, FUTURE_PRIMARY, (PEER,)))
        self.assertEqual(decode_subject_id('subject_unknowntoken000000', FUTURE_PRIMARY, (PEER,)), 'subject_unknowntoken000000')


class NativeBindingIdentityTests(unittest.TestCase):
    def test_guard_context_hides_canonical_company_id(self):
        view = make_view()
        binding = NativeBinding(backend=object(), budget=CallBudget.__new__(CallBudget), view=view)
        binding.__dict__['budget'] = object()
        messages = binding.messages([HumanMessage('plain instruction, not json')])
        guard_content = messages[0].content
        self.assertNotIn(FUTURE_PRIMARY, guard_content)
        self.assertIn('https://hatchet.run', guard_content)
        self.assertIn('OldBrand old.example', guard_content)

    def test_plain_text_supplied_messages_are_left_untouched(self):
        view = make_view()
        binding = NativeBinding(backend=object(), budget=object(), view=view)
        plain = HumanMessage('Describe the company at future_brand_2026 in plain prose.')
        messages = binding.messages([plain])
        self.assertEqual(messages[-1].content, plain.content)

    def test_human_json_supplied_message_identifiers_are_encoded(self):
        view = make_view()
        binding = NativeBinding(backend=object(), budget=object(), view=view)
        payload = HumanMessage(json.dumps(dict(company_seed=dict(company_id=FUTURE_PRIMARY,
            name='Future Brand', domain='future.example'), note='keep this text')))
        messages = binding.messages([payload])
        decoded = json.loads(messages[-1].content)
        self.assertNotIn(FUTURE_PRIMARY, decoded['company_seed']['company_id'])
        self.assertEqual(decoded['company_seed']['name'], 'Future Brand')
        self.assertEqual(decoded['note'], 'keep this text')

    def test_future_source_date_still_rejected_before_any_identity_work(self):
        view = make_view(qa_pairs=(dict(question='q', answer='a', fact_id='f', source_id='s',
            url='https://hatchet.run', subject_id=FUTURE_PRIMARY, available_by='2099-01-01T00:00:00+00:00',
            reliability='READABLE_ARCHIVE'),))
        binding = NativeBinding(backend=object(), budget=object(), view=view)
        from closed_loop.guards import BudgetStopped
        with self.assertRaisesRegex(BudgetStopped, 'FUTURE_QA_DATE'):
            binding.messages([HumanMessage('x')])


class NativeCommitteeStateIdentityTests(unittest.TestCase):
    def test_new_state_encodes_qa_pairs_without_altering_answers_or_fact_ids(self):
        view = make_view()
        state = new_state(view, NativeConfig())
        row = state.all_qa_pairs[0]
        self.assertNotIn(FUTURE_PRIMARY, row['subject_id'])
        self.assertEqual(row['fact_id'], 'hatchet')
        self.assertEqual(row['answer'], 'Retention is strong; see https://hatchet.run for the public writeup about OldBrand old.example.')
        self.assertEqual(row['question'], view.qa_pairs[0]['question'])

    def test_new_state_tokens_distinguish_primary_from_peer(self):
        view = make_view()
        view = make_view(qa_pairs=(dict(view.qa_pairs[0]),
            dict(view.qa_pairs[0], subject_id=PEER, fact_id='peer-fact')))
        state = new_state(view, NativeConfig())
        self.assertNotEqual(state.all_qa_pairs[0]['subject_id'], state.all_qa_pairs[1]['subject_id'])


if __name__ == '__main__':
    unittest.main()
