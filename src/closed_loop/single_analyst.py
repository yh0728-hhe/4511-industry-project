"""One-pass fixed-evidence analyst baseline; not an investment-quality oracle."""
from dataclasses import dataclass,asdict
from datetime import datetime

from .contracts import aware,digest
from .guards import BudgetStopped
from .native_support import NativeBinding,HumanMessage,get_llm
from .thesis_synthesis import ThesisSynthesis
from .analysis_acceptance import build_analysis_review_packet

SINGLE_ANALYST_INSTRUCTION=(
    'Assess the seed mandate and historical cutoff using only admitted evidence. '
    'You are one analyst, with no tools, research loop or forced debate sides. '
    'Distinguish publisher claims from independently verified evidence. Missing '
    'facts remain unknown, not negative outcomes. Do not use company memory or '
    'infer team quality/traction from SDK publication or README brevity. '
    'Return decision INVEST/PASS/MORE_DILIGENCE, rationale and essential_gaps. '
    'Return a full thesis only for a supported substantive proposal with no '
    'essential gaps; otherwise MORE_DILIGENCE and thesis null. A thesis contains '
    'summary,pro_case,con_case,cited_fact_ids,uncertainty_notes,'
    'decision_changing_questions,next_checks. Cite only supplied fact IDs.'
)
SINGLE_ANALYST_INSTRUCTION_SHA256=digest(SINGLE_ANALYST_INSTRUCTION)


@dataclass
class SingleAnalystAssessment:
    decision:str
    rationale:str
    essential_gaps:list[str]
    thesis:ThesisSynthesis|None


class SingleAnalystBaseline:
    def __init__(self,backend,budget):
        if backend is None:raise ValueError('explicit baseline backend required')
        if getattr(backend,'call_budget',budget) is not budget:raise ValueError('baseline budget mismatch')
        self.backend=backend;self.call_budget=budget;self.last_calls=[]

    def assess(self,view):
        self.last_calls=[];budget=self.call_budget;req=budget.bound_request
        binding=None
        try:
            budget.check()
            if view.company_id!=req.company.company_id or aware(datetime.fromisoformat(view.as_of))!=req.as_of:
                raise BudgetStopped('BASELINE_CONTEXT_MISMATCH')
            ids=[row['fact_id'] for row in view.qa_pairs]
            if len(set(ids))!=len(ids):raise BudgetStopped('BASELINE_DUPLICATE_FACT')
            if not ids:
                packet=dict(decision='MORE_DILIGENCE',rationale='No admitted evidence.',
                    essential_gaps=['minimum_historical_evidence'],thesis=None,admitted_fact_ids=[])
                raw=None
            else:
                binding=NativeBinding(self.backend,budget,view)
                with binding.activate():
                    value=get_llm(temperature=0).with_structured_output(SingleAnalystAssessment).invoke([HumanMessage(SINGLE_ANALYST_INSTRUCTION)])
                raw=asdict(value)
                packet=dict(raw,admitted_fact_ids=ids)
                build_analysis_review_packet(packet,'baseline-shape-validation')
                if packet['decision'] in ('INVEST','PASS') and packet['thesis'] is None:
                    raise BudgetStopped('BASELINE_MISSING_THESIS')
                if packet['essential_gaps'] or packet['decision']=='MORE_DILIGENCE':
                    packet=dict(packet,decision='MORE_DILIGENCE',thesis=None)
            return dict(packet,mode='FIXED_EVIDENCE_SINGLE_ANALYST',raw_assessment=raw,
                untrusted_proposed_decision=None if raw is None else raw['decision'],
                instruction_sha256=SINGLE_ANALYST_INSTRUCTION_SHA256,
                logical_call_budget=budget.snapshot(),actual_model_calls=None,invoice='UNKNOWN',
                semantic_support_certified=False,analysis_review_status='NOT_REVIEWED')
        except BudgetStopped as exc:
            budget.stop(str(exc));raise
        except Exception:
            budget.stop('BASELINE_INVALID_RESPONSE')
            raise BudgetStopped('BASELINE_INVALID_RESPONSE') from None
        finally:
            if binding is not None:self.last_calls=list(binding.calls)
