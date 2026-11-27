"""Tests for the OPTIONAL experimental scripts/experiments/local_token_support_contract.py guard.

This exercises the stdlib-only contract validator itself. It does not call
any real model; `infer_tokens`/`token_count` are injected fakes. The real
upstream LettuceDetect model output has no character offsets, so a
tokenizer/offset bridge is still needed before any real model could be
plugged in here -- these tests do not claim otherwise.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts' / 'experiments'))

from local_token_support_contract import evaluate_token_support


class TokenSupportContractTests(unittest.TestCase):
    def test_preflight_refuses_before_inference_when_over_budget(self):
        calls = []

        def token_count(context, question, answer):
            return 100

        def infer_tokens(context, question, answer):
            calls.append('called')
            return [dict(start=0, end=len(answer), unsupported_probability=0.0)]

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer='a', max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens,
            )
        self.assertEqual(calls, [])

    def test_valid_supported_path(self):
        answer = 'Paris is the capital.'

        def token_count(context, question, answer):
            return 5

        def infer_tokens(context, question, answer):
            return [dict(start=0, end=len(answer), unsupported_probability=0.1)]

        result = evaluate_token_support(
            context=['France capital is Paris.'], question='capital?', answer=answer,
            max_tokens=10, token_count=token_count, infer_tokens=infer_tokens,
        )
        self.assertEqual(result['method'], 'token_support_diagnostic')
        self.assertTrue(result['complete'])
        self.assertFalse(result['any_unsupported'])
        self.assertEqual(result['unsupported_spans'], [])
        self.assertFalse(result['quality_accuracy_claim'])

    def test_valid_unsupported_path_reports_exact_substring_and_merges_overlap(self):
        answer = 'Paris is in Germany today.'

        def token_count(context, question, answer):
            return 5

        def infer_tokens(context, question, answer):
            # two overlapping flagged spans covering "Germany" region, plus
            # a low-probability span covering the rest.
            return [
                dict(start=0, end=12, unsupported_probability=0.0),
                dict(start=12, end=18, unsupported_probability=0.9),
                dict(start=15, end=20, unsupported_probability=0.7),
                dict(start=20, end=len(answer), unsupported_probability=0.0),
            ]

        result = evaluate_token_support(
            context=['Paris is in France.'], question='where?', answer=answer,
            max_tokens=10, token_count=token_count, infer_tokens=infer_tokens,
        )
        self.assertTrue(result['any_unsupported'])
        self.assertEqual(len(result['unsupported_spans']), 1)
        span = result['unsupported_spans'][0]
        self.assertEqual(span['text'], answer[span['start']:span['end']])
        self.assertIn('Germany', span['text'])

    def test_rejects_incomplete_coverage(self):
        answer = 'abcdef'

        def token_count(context, question, answer):
            return 5

        def infer_tokens(context, question, answer):
            return [dict(start=0, end=3, unsupported_probability=0.0)]

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer=answer, max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens,
            )

    def test_rejects_empty_infer_tokens_output_instead_of_claiming_full_support(self):
        def token_count(context, question, answer):
            return 5

        def infer_tokens(context, question, answer):
            return []

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer='abc', max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens,
            )

    def test_rejects_bool_probability_and_out_of_range_offsets(self):
        answer = 'abc'

        def token_count(context, question, answer):
            return 5

        def infer_tokens_bool_prob(context, question, answer):
            return [dict(start=0, end=3, unsupported_probability=True)]

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer=answer, max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens_bool_prob,
            )

        def infer_tokens_bad_offset(context, question, answer):
            return [dict(start=0, end=len(answer) + 5, unsupported_probability=0.2)]

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer=answer, max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens_bad_offset,
            )

    def test_rejects_malformed_inputs(self):
        def token_count(context, question, answer):
            return 1

        def infer_tokens(context, question, answer):
            return [dict(start=0, end=len(answer), unsupported_probability=0.0)]

        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=[], question='q', answer='abc', max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens,
            )
        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='   ', answer='abc', max_tokens=10,
                token_count=token_count, infer_tokens=infer_tokens,
            )
        with self.assertRaises(ValueError):
            evaluate_token_support(
                context=['c'], question='q', answer='abc', max_tokens=0,
                token_count=token_count, infer_tokens=infer_tokens,
            )

    def test_fixed_threshold_and_nonfinite_values(self):
        for probability, expected in [(0.4999, False), (0.5, True), (1, True)]:
            with self.subTest(probability=probability):
                result = evaluate_token_support(
                    context=['c'], question='q', answer='a', max_tokens=1,
                    token_count=lambda *args: 1,
                    infer_tokens=lambda *args: [dict(start=0, end=1, unsupported_probability=probability)])
                self.assertIs(result['any_unsupported'], expected)
        for probability in [float('nan'), float('inf'), -0.1, 1.1, '0.2']:
            with self.subTest(invalid_probability=probability), self.assertRaises(ValueError):
                evaluate_token_support(
                    context=['c'], question='q', answer='a', max_tokens=1,
                    token_count=lambda *args: 1,
                    infer_tokens=lambda *args: [dict(start=0, end=1, unsupported_probability=probability)])

    def test_boolean_counts_and_offsets_are_refused(self):
        def forbidden(*args):
            self.fail('inference must not run after an invalid count')
        with self.assertRaises(ValueError):
            evaluate_token_support(context=['c'], question='q', answer='a', max_tokens=2,
                                   token_count=lambda *args: True, infer_tokens=forbidden)
        with self.assertRaises(ValueError):
            evaluate_token_support(context=['c'], question='q', answer='a', max_tokens=2,
                token_count=lambda *args: 1,
                infer_tokens=lambda *args: [dict(start=False,end=1,unsupported_probability=0)])

    def test_unicode_answer_full_coverage_and_whitespace_exempt(self):
        answer = '巴黎 是 法国首都.'

        def token_count(context, question, answer):
            return 3

        def infer_tokens(context, question, answer):
            tokens = []
            i = 0
            while i < len(answer):
                if answer[i].isspace():
                    i += 1
                    continue
                tokens.append(dict(start=i, end=i + 1, unsupported_probability=0.0))
                i += 1
            return tokens

        result = evaluate_token_support(
            context=['法国首都是巴黎'], question='q', answer=answer,
            max_tokens=10, token_count=token_count, infer_tokens=infer_tokens,
        )
        self.assertFalse(result['any_unsupported'])
        self.assertEqual(result['answer_token_count'], len([c for c in answer if not c.isspace()]))


if __name__ == '__main__':
    unittest.main()
