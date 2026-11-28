"""Protocol propagation tests, explicitly NOT semantic entailment evaluation."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from closed_loop import agent_prompts as prompts
from closed_loop.fixtures import request,FixtureProvider
from closed_loop.guards import CallBudget,TemporalGateway
from closed_loop.cli_backend import ClaudeCliBackend
from closed_loop.native_fixture import NativeFixtureBackend
from closed_loop.native_support import ArgumentCritique,HumanMessage
from closed_loop.model_lead import ModelLead
from closed_loop.native_committee import NativeDialecticCommittee
from closed_loop.runtime import ClosedLoopRuntime
from closed_loop.thesis_synthesis import ThesisSynthesizer,ThesisSynthesis


class RecordingBackend(NativeFixtureBackend):
    def __init__(self):super().__init__();self.seen=[]
    def generate(self,schema,messages,temperature):
        self.seen.append((schema.__name__,messages))
        if schema is ThesisSynthesis:
            context=json.loads(messages[0].content.split('\n',1)[1])
            ids=[r['fact_id'] for r in context['evidence']]
            return ThesisSynthesis('Fixture only',['Fixture pro'],['Fixture contra'],ids,
                ['Fixture unknown'],['Fixture question'],['Fixture check'])
        return super().generate(schema,messages,temperature)


class Executor:
    def __init__(self):self.calls=[]
    def run(self,argv,stdin_bytes,timeout_seconds):
        self.calls.append((argv,stdin_bytes))
        return 0,json.dumps({'is_error':False,'structured_output':{'critique':'fixture only'}}).encode(),b''


class GroundingProtocolTests(unittest.TestCase):
    def test_shared_guard_reaches_actual_lead_critique_review_and_thesis(self):
        req=request(max_model_calls=30);budget=CallBudget(req);provider=FixtureProvider();backend=RecordingBackend()
        runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),budget,
            ModelLead(backend,budget),NativeDialecticCommittee(backend,budget),provider,
            thesis=ThesisSynthesizer(backend,budget))
        result=runtime.run()
        self.assertIsNotNone(result['thesis'])
        names={name for name,_ in backend.seen}
        self.assertTrue({'LeadPlanOutput','ArgumentCritique','EvidenceReviewOutput','ThesisSynthesis'}<=names)
        for _,messages in backend.seen:
            self.assertEqual(messages[0].role,'system')
            self.assertTrue(messages[0].content.startswith(prompts.HISTORICAL_GUARD))
            self.assertIn('A short README is not evidence',messages[0].content)
            self.assertIn('does not certify semantic support',messages[0].content)
            self.assertIn('presuppositions in research questions',messages[0].content)

    def test_static_cli_system_and_dynamic_data_stay_separate(self):
        with TemporaryDirectory() as folder:
            executor=Executor();budget=CallBudget(request())
            backend=ClaudeCliBackend(approved=True,executable_path='fixture',model_id='fixture',
                call_budget=budget,max_process_count=1,journal_path=Path(folder)/'journal',executor=executor)
            sentinel='DYNAMIC_PRIVATE_SENTINEL_2940'
            backend.generate(ArgumentCritique,[HumanMessage(sentinel)],0)
            argv,stdin=executor.calls[0]
            self.assertEqual(argv[argv.index('--system-prompt')+1],prompts.CLI_RESEARCH_SYSTEM)
            self.assertNotIn(sentinel,' '.join(argv))
            self.assertIn(sentinel.encode(),stdin)
            self.assertEqual(argv[argv.index('--tools')+1],'')
            self.assertIn('--safe-mode',argv)

    def test_system_role_change_invalidates_prompt_and_cache(self):
        before=prompts.prompt_fingerprint();req=request()
        old_cache=req.cache_key('product','question')
        with patch.object(prompts,'CLI_RESEARCH_SYSTEM',prompts.CLI_RESEARCH_SYSTEM+' changed'):
            self.assertNotEqual(before,prompts.prompt_fingerprint())
            self.assertNotEqual(old_cache,req.cache_key('product','question'))

    def test_scope_limits_are_shared_with_cli_system(self):
        self.assertIn(prompts.HISTORICAL_GUARD,prompts.CLI_RESEARCH_SYSTEM)
        self.assertIn('never that its target',prompts.HISTORICAL_GUARD)
        self.assertIn('not a coding assistant',prompts.CLI_RESEARCH_SYSTEM)
        self.assertIn('No gap may be filled by model memory',prompts.EVIDENCE_REVIEW_INSTRUCTION)


if __name__=='__main__':unittest.main()
