"""Optional factual-gap triage reusing the committee's existing evidence-review role.

No new framework or prompt role is introduced: this issues exactly one
EvidenceReviewOutput structured call through the existing NativeBinding/
get_llm seam, using the existing agent_prompts.EVIDENCE_REVIEW_INSTRUCTION
verbatim plus a local scope-binding addendum. Input is bounded, already-
collected checker diagnostics (untrusted automatic analyst metadata), never
new evidence. Output is new factual research questions only; callers
(the evidence-checked committee wrapper) are responsible for merging these
with any pre-existing gaps.
"""
import json
from datetime import datetime
from .contracts import aware

from .agent_prompts import EVIDENCE_REVIEW_INSTRUCTION
from .guards import BudgetStopped
from .native_support import NativeBinding, HumanMessage, EvidenceReviewOutput, get_llm

MAX_JUDGMENTS = 128
MAX_DIAGNOSTIC_BYTES = 65536
MAX_QUESTION_LENGTH = 1024

LOCAL_SCOPE_BINDING = (
    'The unsupported_analyst_diagnostics below are automatic, untrusted analyst-checker '
    'metadata, not facts and not evidence. Distinguish externally checkable company facts '
    'from author opinions, recommendations, normative advice, hypotheses and mere absence '
    'of a record. Return only material, externally checkable factual research questions; '
    'never a finding, a proven fact or an investment verdict. A hypothesis may motivate a '
    'question but must not be used as its premise. Do not ask whether the author recommends '
    'investing or predicts a huge market; do not turn an unsupported opinion or '
    'recommendation into a literal research question.'
)


class EvidenceGapTriage:
    def __init__(self, backend, budget, max_questions=4):
        if backend is None:raise ValueError('explicit evidence-gap triage backend required')
        if getattr(backend,'call_budget',budget) is not budget:raise ValueError('evidence-gap triage budget mismatch')
        if type(max_questions) is not int or not 1<=max_questions<=4:raise ValueError('bounded max-question count required')
        self.backend=backend;self.call_budget=budget;self.max_questions=max_questions
        self.last_calls=[];self.last_trace=[]

    def triage(self, view, diagnostics, existing_gaps):
        self.last_calls=[];self.last_trace=[]
        budget=self.call_budget
        binding=None
        try:
            budget.check()
            if (view.company_id!=budget.bound_request.company.company_id or
                aware(datetime.fromisoformat(view.as_of))!=budget.bound_request.as_of):
                raise BudgetStopped('EVIDENCE_GAP_TRIAGE_CONTEXT_MISMATCH')
            if not isinstance(diagnostics,list) or not diagnostics:
                raise BudgetStopped('EVIDENCE_GAP_TRIAGE_EMPTY_DIAGNOSTICS')
            if not isinstance(existing_gaps,(list,tuple)) or any(not isinstance(g,str) or not g.strip() for g in existing_gaps):
                raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_EXISTING_GAPS')

            rows=[]
            for diagnostic in diagnostics:
                if not isinstance(diagnostic,dict):raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_DIAGNOSTIC')
                judgments=diagnostic.get('judgments')
                if not isinstance(judgments,list) or not judgments:raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_DIAGNOSTIC')
                for judgment in judgments:
                    if not isinstance(judgment,dict):raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_DIAGNOSTIC')
                    statement=judgment.get('statement');reason=judgment.get('reason');verdict=judgment.get('verdict')
                    if not isinstance(statement,str) or not statement.strip():raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_DIAGNOSTIC')
                    if not isinstance(reason,str) or not reason.strip():raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_DIAGNOSTIC')
                    if type(verdict) is not int or verdict not in (0,1):raise BudgetStopped('EVIDENCE_GAP_TRIAGE_INVALID_VERDICT')
                    if len(rows)>=MAX_JUDGMENTS:raise BudgetStopped('EVIDENCE_GAP_TRIAGE_DIAGNOSTIC_CAP_EXCEEDED')
                    rows.append(dict(statement=statement,reason=reason,verdict=verdict))

            if len(rows)>MAX_JUDGMENTS:raise BudgetStopped('EVIDENCE_GAP_TRIAGE_DIAGNOSTIC_CAP_EXCEEDED')
            unsupported=[row for row in rows if row['verdict']==0]
            if len(json.dumps(unsupported,ensure_ascii=False).encode('utf-8'))>MAX_DIAGNOSTIC_BYTES:
                raise BudgetStopped('EVIDENCE_GAP_TRIAGE_DIAGNOSTIC_TOO_LARGE')
            if not unsupported:
                return ()

            binding=NativeBinding(self.backend,self.call_budget,view)
            with binding.activate():
                output=get_llm(temperature=0).with_structured_output(EvidenceReviewOutput).invoke([
                    HumanMessage(json.dumps(dict(instruction=EVIDENCE_REVIEW_INSTRUCTION,
                        local_scope_binding=LOCAL_SCOPE_BINDING,
                        max_new_questions=self.max_questions,
                        question_limit_instruction=f'Return at most {self.max_questions} new questions. No minimum count. '
                            'Do not repeat or paraphrase gaps already covered by existing_gaps. '
                            'Return an empty essential_gaps list if no additional material factual gap remains.',
                        unsupported_analyst_diagnostics=unsupported,
                        existing_gaps=list(existing_gaps)),ensure_ascii=False))])

            self.last_trace.append(dict(event='EVIDENCE_GAP_TRIAGE_REVIEW',automatic=True,human=False,
                semantically_certified=False,diagnostics_considered=len(unsupported),
                output=dict(essential_gaps=list(output.essential_gaps),rationale=output.rationale)))

            raw=output.essential_gaps
            if len(raw)>self.max_questions:raise BudgetStopped('EVIDENCE_GAP_TRIAGE_QUESTION_CAP_EXCEEDED')
            if len(set(raw))!=len(raw):raise BudgetStopped('EVIDENCE_GAP_TRIAGE_DUPLICATE_QUESTION')
            if any(len(q)>MAX_QUESTION_LENGTH for q in raw):raise BudgetStopped('EVIDENCE_GAP_TRIAGE_QUESTION_TOO_LONG')

            existing_set=set(existing_gaps)
            return tuple(q for q in raw if q not in existing_set)
        except BudgetStopped as exc:
            budget.stop(str(exc))
            self.last_trace.append(dict(event='EVIDENCE_GAP_TRIAGE_STOPPED',reason=budget.stop_reason,
                automatic=True,semantically_certified=False))
            raise
        except Exception:
            budget.stop('EVIDENCE_GAP_TRIAGE_FAILED')
            raise BudgetStopped('EVIDENCE_GAP_TRIAGE_FAILED') from None
        finally:
            self.last_calls=list(binding.calls) if binding is not None else []
