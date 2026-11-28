import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from closed_loop.output_text import validate_plain_analysis_text
from closed_loop.agent_prompts import STRUCTURED_TEXT_INSTRUCTION,prompt_fingerprint
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,BudgetStopped
from closed_loop.native_support import NativeBinding,IndividualRefinedArgumentOutput,HumanMessage,get_llm
from closed_loop.analysis_acceptance import gate_analysis
from test_analysis_acceptance import make_result


class TextFormatTests(unittest.TestCase):
    def test_plain_analysis_and_inline_json_or_quoted_xml_preserved(self):
        for text in ['Supported claim.','Example {"x":1} requires validation.','The word parameter is ordinary prose.',
                     'The literal "</parameter>" is discussed.', '"A quoted observation."']:
            self.assertEqual(validate_plain_analysis_text(text),text)

    def test_whole_encoded_objects_and_control_suffix_rejected(self):
        for text in ['{"refined_argument":"claim"}','{"content":"claim","qa_indices":[0]}',
                     '["claim"]','Claim.</parameter.','Claim. </tool_call>','Claim.</parameter']:
            with self.subTest(text=text),self.assertRaisesRegex(ValueError,'INVALID_ANALYSIS_TEXT_FORMAT'):
                validate_plain_analysis_text(text)

    def test_actual_refinement_route_contract_and_terminal_rejection(self):
        req=request();budget=CallBudget(req)
        row=dict(fact_id='f',available_by='2024-03-01T00:00:00Z',answer='fixture',subject_id=req.company.company_id)
        view=SimpleNamespace(company_id=req.company.company_id,mandate=req.mandate,as_of=req.as_of.isoformat(),
            fact_revision=1,argument_revision=1,qa_pairs=(row,))
        class Backend:
            stop_on_validation_error=True
            def __init__(self):self.calls=[];self.value=IndividualRefinedArgumentOutput('{"refined_argument":"fixture"}',[0])
            def generate(self,schema,messages,temperature):self.calls.append(messages);return self.value
        backend=Backend();binding=NativeBinding(backend,budget,view)
        original=HumanMessage('Original SYNTHETIC_PRO prompt')
        with binding.activate():
            model=get_llm().with_structured_output(IndividualRefinedArgumentOutput)
            with self.assertRaisesRegex(BudgetStopped,'INVALID_ANALYSIS_TEXT_FORMAT'):model.invoke([original])
            with self.assertRaises(BudgetStopped):model.invoke([original])
        self.assertEqual(len(backend.calls),1)
        self.assertEqual(budget.used['model'],1)
        self.assertIn(STRUCTURED_TEXT_INSTRUCTION,backend.calls[0][-1].content)
        self.assertIn('SYNTHETIC_PRO',backend.calls[0][-1].content)
        self.assertEqual(original.content,'Original SYNTHETIC_PRO prompt')
        self.assertEqual(backend.value.content,'{"refined_argument":"fixture"}')

    def test_final_packet_cannot_accept_tagged_rationale(self):
        result=make_result();result['rationale']+='</parameter.'
        out=gate_analysis(result,'run')
        self.assertEqual(out['acceptance_state'],'INVALID_ANALYSIS_PACKET')
        self.assertEqual(out['decision'],'MORE_DILIGENCE')

    def test_old_frozen_protocol_no_longer_matches_changed_prompt(self):
        protocol=Path('data/metadata/workflow_20261121/paired_evaluation_protocol_20261124.json')
        self.assertNotEqual(json.loads(protocol.read_text())['prompt_bundle_sha256'],prompt_fingerprint())


    def test_known_argument_placeholders_fail_at_generation_and_refinement(self):
        from closed_loop.native_support import ArgumentsOutput,ArgumentOutput
        for schema in (ArgumentsOutput,IndividualRefinedArgumentOutput):
            for text in ('test',' Test. ','TODO','placeholder!'):
                with self.subTest(schema=schema.__name__,text=text):
                    req=request();budget=CallBudget(req)
                    row=dict(fact_id='f',available_by='2024-03-01T00:00:00Z',answer='fixture',subject_id=req.company.company_id)
                    view=SimpleNamespace(company_id=req.company.company_id,mandate=req.mandate,as_of=req.as_of.isoformat(),fact_revision=1,argument_revision=1,qa_pairs=(row,))
                    value=ArgumentsOutput([ArgumentOutput(text,[0])]) if schema is ArgumentsOutput else IndividualRefinedArgumentOutput(text,[0])
                    class Backend:
                        stop_on_validation_error=True
                        calls=0
                        def generate(self,*a):self.calls+=1;return value
                    backend=Backend();binding=NativeBinding(backend,budget,view)
                    with binding.activate():
                        model=get_llm().with_structured_output(schema)
                        with self.assertRaisesRegex(BudgetStopped,'PLACEHOLDER_ARGUMENT'):model.invoke([HumanMessage('fixture')])
                        with self.assertRaises(BudgetStopped):model.invoke([HumanMessage('fixture')])
                    self.assertEqual(backend.calls,1);self.assertEqual(budget.used['model'],1)
                    self.assertEqual(value.arguments[0].content if schema is ArgumentsOutput else value.content,text)

    def test_ordinary_use_of_test_and_short_uncertainty_statement_allowed(self):
        req=request();budget=CallBudget(req)
        row=dict(fact_id='f',available_by='2024-03-01T00:00:00Z',answer='fixture',subject_id=req.company.company_id)
        view=SimpleNamespace(company_id=req.company.company_id,mandate=req.mandate,as_of=req.as_of.isoformat(),fact_revision=1,argument_revision=1,qa_pairs=(row,))
        binding=NativeBinding(object(),budget,view)
        for text in ('We should test customer demand.','Insufficient evidence.'):
            out=IndividualRefinedArgumentOutput(text,[0]);self.assertIs(binding.validate(IndividualRefinedArgumentOutput,out),out)


if __name__=='__main__':unittest.main()
