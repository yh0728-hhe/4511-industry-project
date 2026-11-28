"""Optional final thesis synthesis stage (audited gap T2_thesis_synthesis_stage).

Fills the gap where `runtime.finish()` is fully deterministic and never produces
the richer pro/con/contradiction/next-checks synthesis described in
`docs/architecture/agents_v0/thesis.md`'s "PROPOSED ONLY" block. Reuses that
instruction text verbatim. Gated exactly like `ModelLead`/`SpecialistResearchLoop`:
explicit backend injection (no implicit default), a single bounded structured-output
call (no inner action loop), and never invoked for an admittedly incomplete
MORE_DILIGENCE picture. The model only ever sees facts the committee already cited
(never raw model memory or uncited facts), and its own citations must stay inside
that same admitted set or the call is rejected before being returned.
"""
from dataclasses import dataclass
import json
from types import SimpleNamespace

from .agent_prompts import THESIS_SYNTHESIS_INSTRUCTION
from .contracts import Decision
from .guards import BudgetStopped
from .native_support import NativeBinding, get_llm, HumanMessage


@dataclass
class ThesisSynthesis:
    """No numeric score/probability field by construction (enforced by test)."""
    summary: str
    pro_case: list[str]
    con_case: list[str]
    cited_fact_ids: list[str]
    uncertainty_notes: list[str]
    decision_changing_questions: list[str]
    next_checks: list[str]


def _fact_row(fact):
    return dict(question=f'What is the supported evidence for {fact.topic} about this evidence subject?',
        answer=fact.text, fact_id=fact.fact_id, source_id=fact.source_id, url=fact.url,
        subject_id=fact.company_id, available_by=fact.availability_upper_bound.isoformat(),
        reliability=fact.proof_kind)


class ThesisSynthesizer:
    """One bounded call per run; mirrors ModelLead's explicit-backend pattern."""
    def __init__(self, backend, budget):
        if backend is None:raise ValueError('explicit synthesis model backend required')
        self.backend=backend;self.call_budget=budget;self.last_calls=[]

    def synthesize(self, request, context, committee_result):
        if committee_result.decision==Decision.MORE_DILIGENCE:
            raise ValueError('thesis synthesis must never be invoked for an incomplete MORE_DILIGENCE picture')
        if request!=self.call_budget.bound_request:raise ValueError('thesis budget/request mismatch')
        available={f.fact_id for f in context.store.facts}
        cited=set(committee_result.cited_fact_ids)
        if not cited:raise ValueError('substantive decision requires committee citations to synthesize from')
        if not cited<=available:raise ValueError('committee cited an unavailable fact')
        cited_rows=tuple(_fact_row(fact) for fact in context.store.facts if fact.fact_id in cited)
        view=SimpleNamespace(company_id=request.company.company_id,mandate=request.mandate,
            as_of=request.as_of.isoformat(),fact_revision=context.store.revision,
            argument_revision=context.argument_revision,qa_pairs=cited_rows)
        binding=NativeBinding(self.backend,self.call_budget,view)
        payload=dict(instruction=THESIS_SYNTHESIS_INSTRUCTION,decision=committee_result.decision.value,
            committee_rationale=committee_result.rationale,cited_fact_ids=sorted(cited),
            essential_gaps=list(committee_result.essential_gaps))
        with binding.activate():
            try:
                result=get_llm(temperature=0).with_structured_output(ThesisSynthesis).invoke([HumanMessage(json.dumps(payload))])
            finally:self.last_calls=list(binding.calls)
        if not isinstance(result,ThesisSynthesis):raise BudgetStopped('INVALID_THESIS_SCHEMA')
        for values in (result.pro_case,result.con_case,result.cited_fact_ids,result.uncertainty_notes,
                result.decision_changing_questions,result.next_checks):
            if not isinstance(values,list) or not all(isinstance(x,str) for x in values):
                raise BudgetStopped('INVALID_THESIS_SCHEMA')
        if not isinstance(result.summary,str) or not result.summary.strip():raise BudgetStopped('EMPTY_THESIS_SUMMARY')
        if not result.cited_fact_ids:raise BudgetStopped('THESIS_MISSING_CITATIONS')
        if not set(result.cited_fact_ids)<=available:raise BudgetStopped('THESIS_CITED_UNAVAILABLE_FACT')
        if not set(result.cited_fact_ids)<=cited:raise BudgetStopped('THESIS_CITED_OUTSIDE_COMMITTEE_SCOPE')
        return result
