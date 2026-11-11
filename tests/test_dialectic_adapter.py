"""Test actual reused aggregation, not a rerun of the original model pipeline."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.contracts import Decision
from closed_loop.dialectic_adapter import ScoredArgument, aggregate_arguments


class AdapterTests(unittest.TestCase):
    def test_humane_saved_score_replays_aggregation_only(self):
        path=Path(__file__).parents[1]/'data/metadata/runtime_r002_20261108/prior_humane_summary.json'
        previous=json.loads(path.read_text())
        args=[ScoredArgument(x['type'],x['score'],('prior-claim',)) for x in previous['final_arguments']]
        # prior-claim is a regression token, not newly verified historical evidence.
        self.assertEqual(aggregate_arguments(args,{'prior-claim'}),Decision.PASS)
        self.assertEqual(previous['final_decision'],'not_invest')

    def test_mean_per_side_not_sum(self):
        args=[ScoredArgument('pro',20,('a',)),ScoredArgument('pro',20,('a',)),ScoredArgument('contra',30,('b',))]
        self.assertEqual(aggregate_arguments(args,{'a','b'}),Decision.PASS)

    def test_gap_and_empty_arguments_yield_more_diligence(self):
        arg=ScoredArgument('pro',90,('a',))
        self.assertEqual(aggregate_arguments([arg],{'a'},('retention',)),Decision.MORE_DILIGENCE)
        self.assertEqual(aggregate_arguments([],set()),Decision.MORE_DILIGENCE)

    def test_stale_citations_and_nonfinite_scores_fail(self):
        with self.assertRaises(ValueError):aggregate_arguments([ScoredArgument('pro',90,('old',))],{'new'})
        for value in (float('nan'),float('inf'),-1,101,True):
            with self.subTest(value=value),self.assertRaises(ValueError):ScoredArgument('pro',value,('a',))

    def test_vendored_function_matches_recorded_upstream_extraction(self):
        root=Path(__file__).parents[1]
        meta=json.loads((root/'data/metadata/runtime_r002_20261108/dialectic_node_provenance.json').read_text())
        source=(root/'src/closed_loop/vendor/dialectic_decision.py').read_text(encoding='utf-8')
        function=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef))
        content=ast.get_source_segment(source,function).replace('\r\n','\n')
        self.assertEqual(hashlib.sha256(content.encode()).hexdigest(),meta['normalized_function_sha256'])

    def test_all_selected_native_bodies_and_prompts_match_upstream_hash_manifest(self):
        root=Path(__file__).parents[1]
        meta=json.loads((root/'data/metadata/runtime_r002_20261108/native_committee_provenance.json').read_text())
        source=(root/'src/closed_loop/vendor/dialectic_committee_nodes.py').read_text(encoding='utf-8')
        definitions={}
        for node in ast.parse(source).body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):name=node.name
            elif isinstance(node,ast.Assign):name=','.join(t.id for t in node.targets)
            else:continue
            definitions[name]=hashlib.sha256(ast.get_source_segment(source,node).replace('\r\n','\n').encode()).hexdigest()
        checked=0
        for file in meta['sources']:
            for definition in file['selected_definitions']:
                self.assertEqual(definitions[definition['name']],definition['sha256'])
                checked+=1
        self.assertEqual(checked,42)


if __name__=='__main__':unittest.main()
