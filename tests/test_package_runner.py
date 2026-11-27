import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from closed_loop.fixtures import request
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.package_runner import execute_package_run
from test_package_source import wheel


class PackageRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'new-run'
        self.raw,self.meta=wheel()
        self.factories=[]

    def factory(self,budget,root):
        self.factories.append((budget,root))
        return NativeFixtureBackend()

    def run_case(self,**changes):
        args=dict(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),
                    max_model_calls=24,max_search_calls=0,concurrency=1,max_research_passes=2),
                  artifact_bytes=self.raw,file_metadata=self.meta,expected_package='sample-sdk',
                  output_dir=self.root,backend_factory=self.factory,approved=True)
        args.update(changes)
        return execute_package_run(**args)

    def test_full_injected_loop_preserves_unknown_and_same_source(self):
        result=self.run_case()
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'NO_NEW_EVIDENCE')
        self.assertEqual(len(result['admitted_fact_ids']),1)
        self.assertEqual(result['fact_revision'],1)
        self.assertGreater(result['logical_call_budget']['used']['model'],1)
        self.assertLessEqual(result['logical_call_budget']['used']['model'],24)
        self.assertEqual(result['logical_call_budget']['used']['search'],0)
        self.assertFalse(result['Y_changed'])
        self.assertFalse(result['predictive_accuracy_evaluated'])
        self.assertEqual(result['analysis_review_status'],'NO_SUBSTANTIVE_PROPOSAL')
        self.assertFalse(result['semantic_support_certified'])
        self.assertTrue((self.root/'result.json').is_file())
        self.assertEqual(len(self.factories),1)

    def test_precollection_budget_is_shared_without_reset(self):
        from closed_loop.guards import CallBudget
        req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),
            max_model_calls=24,max_search_calls=2,max_research_passes=2)
        budget=CallBudget(req)
        for _ in range(2):
            with budget.reserve('search'):pass
        seen=[]
        def factory(shared,root):
            seen.append(shared)
            self.assertEqual(shared.used['search'],2)
            return NativeFixtureBackend()
        result=self.run_case(request=req,call_budget=budget,backend_factory=factory)
        self.assertIs(seen[0],budget)
        self.assertEqual(result['logical_call_budget']['used']['search'],2)
        self.assertGreater(result['logical_call_budget']['used']['model'],0)
        self.assertEqual(result['registry_transport_attempts'],2)

    def test_mismatched_precollection_budget_refused(self):
        from closed_loop.guards import CallBudget
        with self.assertRaises(ValueError):self.run_case(call_budget=CallBudget(request()))
        self.assertEqual(self.factories,[])

    def test_unreviewed_substantive_model_proposal_is_not_released(self):
        from closed_loop.native_support import EvidenceReviewOutput,SingleArgumentScore,CriterionScore
        from closed_loop.thesis_synthesis import ThesisSynthesis
        import json
        class UntrustedOptimisticBackend(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                if schema is EvidenceReviewOutput:return EvidenceReviewOutput([],"Invented model assertion; not reviewed.")
                if schema is SingleArgumentScore:
                    score=6 if 'SYNTHETIC_PRO' in messages[-1].content else 3
                    return SingleArgumentScore([CriterionScore(score,'Fixture score') for _ in range(14)])
                if schema is ThesisSynthesis:
                    context=json.loads(messages[0].content.split('\n',1)[1])
                    ids=[r['fact_id'] for r in context['evidence']]
                    return ThesisSynthesis('Invented favorable conclusion',['Fixture pro'],['Fixture contra'],
                        ids,[],[],[])
                return super().generate(schema,messages,temperature)
        result=self.run_case(backend_factory=lambda budget,root:UntrustedOptimisticBackend())
        self.assertEqual(result['proposed_decision'],'INVEST')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['analysis_review_status'],'NOT_REVIEWED')
        self.assertIsNone(result['thesis'])
        self.assertIsNotNone(result['proposed_thesis'])
        self.assertIn('final_analysis_review',result['essential_gaps'])
        proposal=json.loads((self.root/'proposal.json').read_text())
        self.assertEqual(proposal['decision'],'INVEST')

    def test_npm_source_uses_same_runtime_and_remains_unreviewed(self):
        from test_npm_source import tarball
        raw,meta=tarball()
        result=self.run_case(artifact_bytes=raw,file_metadata=meta,artifact_format='npm')
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['analysis_review_status'],'NO_SUBSTANTIVE_PROPOSAL')
        self.assertEqual(len(result['admitted_fact_ids']),1)
        import json
        plan=json.loads((self.root/'plan.json').read_text())
        self.assertEqual(plan['artifact_format'],'npm')

    def test_unsupported_format_refuses_before_factory(self):
        with self.assertRaises(ValueError):self.run_case(artifact_format='unknown')
        self.assertEqual(self.factories,[])
        self.assertFalse(self.root.exists())

    def test_invalid_source_never_constructs_backend_or_output(self):
        self.meta['digests']['sha256']='0'*64
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(self.factories,[])
        self.assertFalse(self.root.exists())

    def test_future_source_never_constructs_backend(self):
        self.meta['upload_time_iso_8601']='2025-01-01T00:00:00Z'
        with self.assertRaises(ValueError):self.run_case()
        self.assertEqual(self.factories,[])

    def test_existing_output_never_constructs_backend(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):self.run_case()
        self.assertEqual(self.factories,[])

    def test_no_approval_never_constructs_backend(self):
        with self.assertRaises(PermissionError):self.run_case(approved=False)
        self.assertEqual(self.factories,[])

    def test_expired_or_oversized_limits_refuse_before_factory(self):
        for changes in [dict(deadline=datetime.now(timezone.utc)-timedelta(seconds=1)),
                        dict(max_model_calls=25),dict(max_search_calls=3),
                        dict(concurrency=2),dict(max_research_passes=3)]:
            req=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),
                        max_model_calls=24,max_search_calls=0,concurrency=1,max_research_passes=2)
            from dataclasses import replace
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.run_case(request=replace(req,**changes))
        self.assertEqual(self.factories,[])

    def test_factory_failure_has_durable_sanitized_receipt(self):
        def broken(budget,root):raise RuntimeError('SECRET')
        result=self.run_case(backend_factory=broken)
        self.assertEqual(result['status'],'PACKAGE_RUN_FAILED')
        self.assertNotIn('SECRET',(self.root/'result.json').read_text())
        self.assertEqual(result['logical_call_budget']['used']['model'],0)

    def test_call_cap_is_retained_not_retried(self):
        result=self.run_case(request=request(deadline=datetime.now(timezone.utc)+timedelta(seconds=120),
            max_model_calls=1,max_search_calls=0,max_research_passes=2))
        self.assertEqual(result['decision'],'MORE_DILIGENCE')
        self.assertEqual(result['stop_reason'],'CALL_CAP')
        self.assertEqual(result['logical_call_budget']['used']['model'],1)
        self.assertEqual(len(result['admitted_fact_ids']),1)


if __name__=='__main__':unittest.main()


class PackageEvidenceFeedbackTests(unittest.TestCase):
    setUp=PackageRunnerTests.setUp
    factory=PackageRunnerTests.factory
    run_case=PackageRunnerTests.run_case
    def test_optional_support_checker_reaches_runtime_and_is_logged(self):
        from closed_loop.ragas_faithfulness import FaithfulnessStatements,FaithfulnessVerdicts,StatementFaithfulnessVerdict
        class CheckedBackend(NativeFixtureBackend):
            def generate(self,schema,messages,temperature):
                if schema is FaithfulnessStatements:return FaithfulnessStatements(['Fixture unsupported claim.'])
                if schema is FaithfulnessVerdicts:return FaithfulnessVerdicts([StatementFaithfulnessVerdict('Fixture unsupported claim.','Not in source.',0)])
                return super().generate(schema,messages,temperature)
        out=self.run_case(check_argument_support=True,backend_factory=lambda budget,root:CheckedBackend())
        self.assertEqual(out['decision'],'MORE_DILIGENCE')
        self.assertTrue(out['argument_support_check_enabled'])
        self.assertTrue(any(e['event']=='EVIDENCE_SUPPORT_REVIEW' for e in out['trace']))
        self.assertTrue(json.loads((self.root/'plan.json').read_text())['argument_support_check_enabled'])
        self.assertLessEqual(out['logical_call_budget']['used']['model'],24)
    def test_support_check_flag_must_be_boolean(self):
        with self.assertRaises(ValueError):self.run_case(check_argument_support='yes')
        self.assertFalse(self.factories)
