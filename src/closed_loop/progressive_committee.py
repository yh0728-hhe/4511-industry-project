"""Optional cheap-screen-before-committee wrapper; requires explicit runner opt-in and is off by default.

Reuses SingleAnalystBaseline.assess verbatim as a preliminary screen and only
invokes the existing (possibly evidence-checked) committee when that screen
finds no essential gaps. The screen's own rationale/claims are never passed
into the committee as facts or prompts, and its assessment is only ever
retained privately in this wrapper's trace as an automatic, non-certified
preliminary signal. Preliminary abstention can be wrong; this makes no
accuracy claim either way.
"""
from copy import deepcopy

from .contracts import CommitteeResult, Decision
from .guards import BudgetStopped

_VALID_DECISIONS = ('INVEST', 'PASS', 'MORE_DILIGENCE')


class ProgressiveCommittee:
    def __init__(self, screen, committee, budget):
        if getattr(screen, 'call_budget', None) is not budget:
            raise ValueError('screen budget mismatch')
        if getattr(committee, 'call_budget', None) is not budget:
            raise ValueError('committee budget mismatch')
        self.screen = screen
        self.committee = committee
        self.call_budget = budget
        self.last_trace = []
        self.last_calls = []

    def evaluate(self, view):
        self.last_trace = []
        self.last_calls = []
        stage='screen'
        try:
            self.call_budget.check()
            try:
                screening = self.screen.assess(view)
            finally:
                self.last_calls = list(getattr(self.screen, 'last_calls', ()))
                self.last_trace = list(getattr(self.screen, 'last_trace', ()))
            decision, gaps = self._validate_screening(view, screening)
            self.last_trace.append(dict(event='PROGRESSIVE_PRELIMINARY_ASSESSMENT',automatic=True,human=False,
                semantically_certified=False,untrusted_assessment=deepcopy(screening)))
            if decision == 'MORE_DILIGENCE' and not gaps:
                raise BudgetStopped('PROGRESSIVE_SCREEN_MISSING_GAPS')
            if decision == 'MORE_DILIGENCE' or gaps:
                self.last_trace.append(dict(event='PROGRESSIVE_SCREEN_MORE_DILIGENCE',
                    automatic=True, human=False, semantically_certified=False,
                    screen_decision=decision, screen_essential_gaps=list(gaps)))
                return CommitteeResult(Decision.MORE_DILIGENCE,
                    'Preliminary assessment reports unresolved information; further research is required.',
                    tuple(dict.fromkeys(gaps)), view.fact_revision, view.argument_revision, ())
            self.last_trace.append(dict(event='PROGRESSIVE_SCREEN_ESCALATED',
                automatic=True, human=False, semantically_certified=False, screen_decision=decision))
            stage='committee'
            try:
                proposed = self.committee.evaluate(view)
            finally:
                self.last_trace = self.last_trace + list(getattr(self.committee, 'last_trace', ()))
                self.last_calls = self.last_calls + list(getattr(self.committee, 'last_calls', ()))
            if not isinstance(proposed, CommitteeResult):
                raise BudgetStopped('PROGRESSIVE_COMMITTEE_INVALID_RESULT')
            return proposed
        except BudgetStopped as exc:
            self.call_budget.stop(str(exc))
            self.last_trace.append(dict(event='PROGRESSIVE_COMMITTEE_STOPPED',stage=stage,reason=self.call_budget.stop_reason))
            raise BudgetStopped(self.call_budget.stop_reason) from None
        except Exception:
            self.call_budget.stop('PROGRESSIVE_'+stage.upper()+'_FAILED')
            self.last_trace.append(dict(event='PROGRESSIVE_COMMITTEE_STOPPED',stage=stage,reason=self.call_budget.stop_reason))
            raise BudgetStopped(self.call_budget.stop_reason) from None

    def _validate_screening(self, view, screening):
        if not isinstance(screening, dict):
            raise BudgetStopped('PROGRESSIVE_COMMITTEE_INVALID_SCREEN')
        decision = screening.get('decision')
        if decision not in _VALID_DECISIONS:
            raise BudgetStopped('PROGRESSIVE_COMMITTEE_INVALID_SCREEN')
        gaps = screening.get('essential_gaps')
        if (not isinstance(gaps, list) or len(gaps) > 32
                or any(not isinstance(g, str) or not g.strip() or len(g) > 1024 for g in gaps)
                or len(set(gaps)) != len(gaps)):
            raise BudgetStopped('PROGRESSIVE_COMMITTEE_INVALID_SCREEN')
        expected_ids = [row['fact_id'] for row in view.qa_pairs]
        if screening.get('admitted_fact_ids') != expected_ids:
            raise BudgetStopped('PROGRESSIVE_COMMITTEE_INVALID_SCREEN')
        return decision, gaps
