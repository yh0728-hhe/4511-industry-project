"""Optional evidence-support feedback wrapper around an existing DIALECTIC committee.

Reuses the committee's own result/trace and the Ragas-based faithfulness
checker verbatim; no new prompts, no new framework. Only the committee's
final selected arguments (NATIVE_COMMITTEE_STAGE stage=final_aggregation)
are assessed, never rationale/meta text.
"""
from dataclasses import replace

from .contracts import CommitteeResult, Decision
from .guards import BudgetStopped

UNVERIFIED_CLAIM_PREFIX='Find evidence that supports or refutes this unverified claim: '


class EvidenceCheckedCommittee:
    def __init__(self, committee, checker, budget, max_arguments=4, gap_triage=None):
        if getattr(committee,'call_budget',None) is not budget:raise ValueError('committee budget mismatch')
        if getattr(checker,'call_budget',None) is not budget:raise ValueError('checker budget mismatch')
        if gap_triage is not None and getattr(gap_triage,'call_budget',None) is not budget:raise ValueError('gap-triage budget mismatch')
        if type(max_arguments) is not int or not 1<=max_arguments<=4:raise ValueError('bounded max-argument count required')
        self.committee=committee;self.checker=checker;self.call_budget=budget;self.max_arguments=max_arguments
        self.gap_triage=gap_triage
        self.last_trace=[];self.last_calls=[]

    def evaluate(self, view):
        self.last_trace=[];self.last_calls=[]
        try:
            self.call_budget.check()
            try:
                result=self.committee.evaluate(view)
            finally:
                self.last_trace=list(getattr(self.committee,'last_trace',()))
                self.last_calls=list(getattr(self.committee,'last_calls',()))
            if not isinstance(result,CommitteeResult):raise BudgetStopped('INVALID_EVIDENCE_SUPPORT_RESULT')
            return self._apply_evidence_check(view,result)
        except BudgetStopped as exc:
            self.call_budget.stop(str(exc));raise
        except Exception:
            self.call_budget.stop('INVALID_EVIDENCE_SUPPORT_RESULT')
            raise BudgetStopped('INVALID_EVIDENCE_SUPPORT_RESULT') from None

    def _apply_evidence_check(self, view, result):
        final_stages=[entry for entry in self.last_trace
            if entry.get('event')=='NATIVE_COMMITTEE_STAGE' and entry.get('stage')=='final_aggregation']
        arguments=final_stages[-1]['arguments'] if final_stages else []

        if not isinstance(arguments,list):raise BudgetStopped('INVALID_EVIDENCE_SUPPORT_RESULT')
        if not arguments:
            if result.decision==Decision.MORE_DILIGENCE:return result
            gaps=tuple(dict.fromkeys((*result.essential_gaps,'missing_argument_trace')))
            return replace(result,decision=Decision.MORE_DILIGENCE,essential_gaps=gaps)

        if len(arguments)>self.max_arguments:raise BudgetStopped('EVIDENCE_SUPPORT_ARGUMENT_CAP_EXCEEDED')

        admissible=set(row['fact_id'] for row in view.qa_pairs)
        unsupported_statements=[]
        collected_diagnostics=[]
        for argument in arguments:
            if not isinstance(argument,dict):raise BudgetStopped('INVALID_EVIDENCE_SUPPORT_RESULT')
            text=argument.get('text')
            cited=argument.get('cited_fact_ids')
            tracking_id=argument.get('tracking_id')
            if not isinstance(text,str) or not text.strip():raise BudgetStopped('EVIDENCE_SUPPORT_BLANK_ARGUMENT')
            if not isinstance(cited,list) or not cited or any(not isinstance(c,str) or not c.strip() for c in cited):
                raise BudgetStopped('EVIDENCE_SUPPORT_INVALID_CITATIONS')
            if len(set(cited))!=len(cited):raise BudgetStopped('EVIDENCE_SUPPORT_DUPLICATE_CITATIONS')
            if not set(cited)<=admissible:raise BudgetStopped('EVIDENCE_SUPPORT_FOREIGN_CITATION')

        for argument in arguments:
            text=argument['text'];cited=argument['cited_fact_ids'];tracking_id=argument.get('tracking_id')
            try:
                diagnostics=self.checker.assess(view,
                    question='Is this investment argument supported by its cited historical evidence?',
                    response=text,cited_fact_ids=cited)
            except Exception as exc:
                self.last_trace.append(dict(event='EVIDENCE_SUPPORT_CHECK_STOPPED',
                    tracking_id=tracking_id,cited_fact_ids=list(cited),
                    reason=str(exc) if isinstance(exc,BudgetStopped) else 'CHECKER_FAILED',
                    checker_stage_trace=list(getattr(self.checker,'last_trace',()))))
                raise
            finally:
                self.last_calls=self.last_calls+list(getattr(self.checker,'last_calls',()))

            collected_diagnostics.append(diagnostics)
            judgments=diagnostics.get('judgments') if isinstance(diagnostics,dict) else None
            if not isinstance(judgments,list) or not judgments:raise BudgetStopped('EVIDENCE_SUPPORT_EMPTY_JUDGMENTS')
            for judgment in judgments:
                if not isinstance(judgment,dict):raise BudgetStopped('INVALID_EVIDENCE_SUPPORT_RESULT')
                verdict=judgment.get('verdict')
                if type(verdict) is not int or verdict not in (0,1):raise BudgetStopped('EVIDENCE_SUPPORT_INVALID_VERDICT')
                statement=judgment.get('statement')
                if not isinstance(statement,str) or not statement.strip():raise BudgetStopped('EVIDENCE_SUPPORT_BLANK_STATEMENT')
                reason=judgment.get('reason')
                if not isinstance(reason,str) or not reason.strip():raise BudgetStopped('EVIDENCE_SUPPORT_BLANK_REASON')
                if verdict==0:unsupported_statements.append(statement)

            self.last_trace.append(dict(event='EVIDENCE_SUPPORT_REVIEW',automatic=True,human=False,
                semantically_certified=False,tracking_id=tracking_id,cited_fact_ids=list(cited),
                diagnostics=diagnostics))

        if not unsupported_statements:return result

        if self.gap_triage is None:
            new_gaps=tuple(dict.fromkeys((*result.essential_gaps,
                *(UNVERIFIED_CLAIM_PREFIX+statement for statement in unsupported_statements))))
            return replace(result,decision=Decision.MORE_DILIGENCE,essential_gaps=new_gaps)

        try:
            new_questions=self.gap_triage.triage(view,collected_diagnostics,result.essential_gaps)
        except BudgetStopped as exc:
            self.last_trace.append(dict(event='EVIDENCE_GAP_TRIAGE_STOPPED',reason=str(exc),
                triage_trace=list(getattr(self.gap_triage,'last_trace',()))))
            raise
        finally:
            self.last_calls=self.last_calls+list(getattr(self.gap_triage,'last_calls',()))
        self.last_trace.extend(list(getattr(self.gap_triage,'last_trace',())))

        if (not isinstance(new_questions,tuple) or len(new_questions)>4 or
            any(not isinstance(q,str) or not q.strip() or len(q)>1024 for q in new_questions) or
            len(set(new_questions))!=len(new_questions)):
            raise BudgetStopped('INVALID_GAP_TRIAGE_QUESTIONS')
        if not new_questions:
            self.last_trace.append(dict(event='EVIDENCE_SUPPORT_UNRESOLVED',automatic=True,
                semantically_certified=False,no_new_research_questions=True))
            if result.decision==Decision.MORE_DILIGENCE:return result
            note=' Automatic evidence-support check found unresolved citation support; no new research questions were produced by triage.'
            return replace(result,decision=Decision.MORE_DILIGENCE,rationale=result.rationale+note)
        new_gaps=tuple(dict.fromkeys((*result.essential_gaps,*new_questions)))
        return replace(result,decision=Decision.MORE_DILIGENCE,essential_gaps=new_gaps)
