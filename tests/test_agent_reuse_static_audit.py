"""Source-audit regressions: inspect generated fixtures without importing them."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

SPEC = importlib.util.spec_from_file_location(
    'reuse_static_audit', Path(__file__).parents[1]/'src/agent_reuse/static_audit.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StaticAuditTests(unittest.TestCase):
    def make_tree(self, root, repaired=False):
        files = {
            'pipeline/graph.py': 'raise RuntimeError("MUST NEVER IMPORT")\nbuilder.add_edge("answer_questions", "generate_pro_arguments")\n',
            'pipeline/stages/parallel_answering.py': (
                'async def answer_all_trees(state):\n'
                '    return await _get_or_answer_tree(is_backtesting=' +
                ('state.backtesting, search_end_date=state.as_of)' if repaired else
                 'False, search_end_date=None)') + '\n'),
            'pipeline/stages/cache.py': (
                'def get_cache_key(question, company' +
                (', as_of, mandate, source_policy_version' if repaired else '') +
                '):\n    return "fixture"\n'
                'def get_answered_cache_key(aspect, company' +
                (', as_of, mandate, source_policy_version' if repaired else '') +
                '):\n    return "fixture"\n'),
            'cli.py': 'parser.add_argument(' + ('"--as-of"' if repaired else '"--name"') + ')\n',
            'web_search/providers.py': (
                'class Provider:\n    def _format_results(self, item):\n'
                '        date=item.get("date")\n        return ' +
                ('str(date)' if repaired else '"date lost"') + '\n' +
                ('' if repaired else 'LOOKBACK=timedelta(days=365)\n')),
            'pipeline/state/investment_story.py': (
                'class InputState:\n    company: str\n    config: str\n' +
                ('    all_qa_pairs: list\n' if repaired else '') +
                'decision: ' + ('Literal["invest", "not_invest", "more_diligence"]' if repaired else
                               'Literal["invest", "not_invest"]') + '\n'),
        }
        for suffix, text in files.items():
            path = root/'src/agent'/suffix
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')

    def test_known_risks_detected_without_executing_fixture(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); self.make_tree(root)
            result=MODULE.audit(root)
            codes=[f['code'] for f in result['findings']]
            self.assertEqual(len(codes), 8)
            self.assertEqual(codes.count('CACHE_CONTEXT_NOT_KEYED'), 2)
            self.assertIn('RESULT_DATE_DISCARDED', codes)
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual(result['explicit_graph_edges'], [('answer_questions','generate_pro_arguments')])

    def test_changed_signatures_and_provenance_do_not_raise_old_flags(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); self.make_tree(root, repaired=True)
            self.assertEqual(MODULE.audit(root)['findings'], [])

    def test_changed_source_hash_is_detected_even_if_flags_same(self):
        with TemporaryDirectory() as folder:
            root=Path(folder); self.make_tree(root)
            before=MODULE.audit(root)
            path=root/'src/agent/cli.py'
            path.write_text(path.read_text()+'# independent change\n')
            after=MODULE.audit(root)
            self.assertNotEqual(before['source_sha256']['src/agent/cli.py'], after['source_sha256']['src/agent/cli.py'])


if __name__=='__main__':
    unittest.main()
