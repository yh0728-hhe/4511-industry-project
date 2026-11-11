"""Dependency-injected coordinator; no implicit model, search or outcome client."""
from dataclasses import dataclass, field
from typing import Protocol

from .contracts import CommitteeResult, Decision, Fact, ResearchRequest
from .guards import BudgetStopped, SourceCandidate


@dataclass(frozen=True)
class CommitteeInput:
    company_id: str
    mandate: str
    as_of: str
    fact_revision: int
    argument_revision: int
    qa_pairs: tuple[dict,...]


class Lead(Protocol):
    def select(self, request, essential_gaps:tuple[str,...]) -> tuple[ResearchRequest,...]:...


class Committee(Protocol):
    def evaluate(self, value:CommitteeInput) -> CommitteeResult:...


class FactStore:
    def __init__(self):
        self._active={}
        self.revision=0
        self.last_changes=()

    def merge(self, facts):
        changed=False
        changes=[]
        for fact in facts:
            key=(fact.company_id,fact.source_id,fact.topic)
            if self._active.get(key)!=fact:
                old=self._active.get(key)
                changes.append(dict(event='SOURCE_CONTENT_REVISED' if old else 'FACT_ADDED',
                    old_fact_id=old.fact_id if old else None,new_fact_id=fact.fact_id))
                self._active[key]=fact
                changed=True
        if changed:self.revision+=1
        self.last_changes=tuple(changes)
        return changed

    @property
    def facts(self):return tuple(self._active[k] for k in sorted(self._active))


def committee_input(request, store, argument_revision):
    """Explicit QA bridge: admitted current facts, not hidden extra graph fields.

    QA question/answer keys match the inspected DIALECTIC QA container shape.
    Actual DIALECTIC generation/critique nodes are not invoked by this prototype.
    Provenance remains bound to every row and stable fact ID, not a stale index.

    `reliability` carries the gateway-verified `proof_kind` tier (e.g.
    READABLE_ARCHIVE vs VERIFIED_ORIGINAL_PUBLICATION), not a model-asserted
    confidence score. This closes the gap where the workflow spec requires
    specialists to report "how reliable" a finding is, but the fact's only
    existing reliability signal (proof_kind) was computed by TemporalGateway
    and then silently dropped before reaching the committee/lead view.
    """
    rows=tuple(dict(question=f'What is the supported evidence for {fact.topic} about {fact.company_id}?',
        answer=fact.text,fact_id=fact.fact_id,source_id=fact.source_id,url=fact.url,
        subject_id=fact.company_id,available_by=fact.availability_upper_bound.isoformat(),
        reliability=fact.proof_kind) for fact in store.facts)
    return CommitteeInput(request.company.company_id,request.mandate,request.as_of.isoformat(),
        store.revision,argument_revision,rows)


class ClosedLoopRuntime:
    def __init__(self, request, gateway, budget, lead, committee, provider, cache=None):
        if gateway.request!=request or budget.bound_request!=request:
            raise ValueError('request/gateway/budget contexts must match')
        for component in (lead,committee,provider):
            if getattr(component,'call_budget',budget) is not budget:
                raise ValueError('nested component budget must be the run budget')
        self.request=request;self.gateway=gateway;self.budget=budget
        self.lead=lead;self.committee=committee;self.provider=provider
        self.cache=cache if cache is not None else {}

    def plan(self, context):
        self.budget.check()
        def select():
            contextual=getattr(self.lead,'select_with_context',None)
            if contextual:
                view=committee_input(self.request,context.store,context.argument_revision)
                hints=getattr(self.provider,'link_hints',lambda:())()
                return contextual(self.request,context.gaps,view.qa_pairs,hints,fact_revision=context.store.revision)
            return self.lead.select(self.request,context.gaps)
        if getattr(self.lead,'call_budget',None) is self.budget:
            context.tasks=select()
        else:
            with self.budget.reserve('model'):
                context.tasks=select()
        if not isinstance(context.tasks,tuple) or not context.tasks:
            context.stop='NO_RESEARCH_TASKS'

    def research(self, context):
        self.budget.check()
        added=False
        for task in context.tasks:
            if not isinstance(task,ResearchRequest) or task.company_id!=self.request.company.company_id:
                raise ValueError('lead returned invalid identity/task')
            key=self.request.cache_key(task.role,task.question,task.subject_id,task.source_path)
            cached=self.cache.get(key)
            if cached is None:
                if getattr(self.provider,'call_budget',None) is self.budget:
                    candidates=tuple(self.provider.search(task))
                else:
                    with self.budget.reserve('search'):
                        candidates=tuple(self.provider.search(task))
                admitted=[]
                for candidate in candidates:
                    fact,rejection=self.gateway.admit(candidate,task.subject_id)
                    if fact is not None:admitted.append(fact)
                    else:context.trace.append(dict(event='SOURCE_HELD',**rejection))
                self.cache[key]=tuple(admitted)
            else:
                admitted=[]
                for previous in cached:
                    candidate=SourceCandidate(previous.source_id,previous.url,previous.company_id,previous.topic,previous.text)
                    fact,rejection=self.gateway.admit(candidate,task.subject_id)
                    if fact is not None:admitted.append(fact)
                    else:context.trace.append(dict(event='CACHED_SOURCE_HELD',**rejection))
            added=context.store.merge(admitted) or added
            context.trace.extend(context.store.last_changes)
            context.trace.append(dict(event='RESEARCH',role=task.role,question=task.question,
                cache_hit=cached is not None,admitted_fact_ids=[f.fact_id for f in admitted],fact_revision=context.store.revision))
        if context.research_pass and not added:context.stop='NO_NEW_EVIDENCE'

    def evaluate(self, context):
        context.argument_revision+=1
        view=committee_input(self.request,context.store,context.argument_revision)
        if getattr(self.committee,'call_budget',None) is self.budget:
            # A trusted native adapter meters EVERY nested generation/critique/
            # score/retry/refinement call, instead of charging one outer call.
            proposed=self.committee.evaluate(view)
        else:
            with self.budget.reserve('model'):
                proposed=self.committee.evaluate(view)
        if not isinstance(proposed,CommitteeResult) or not isinstance(proposed.decision,Decision):raise ValueError('invalid committee result')
        if (proposed.fact_revision,proposed.argument_revision)!=(context.store.revision,context.argument_revision):
            raise ValueError('stale committee/argument revision')
        if not set(proposed.cited_fact_ids)<= {f.fact_id for f in context.store.facts}:raise ValueError('committee cited an unavailable fact')
        if proposed.decision!=Decision.MORE_DILIGENCE and not proposed.cited_fact_ids:raise ValueError('unsupported substantive decision')
        context.result=proposed;context.gaps=proposed.essential_gaps
        if context.gaps and proposed.decision!=Decision.MORE_DILIGENCE:
            context.trace.append(dict(event='COMMITTEE_GAP_OVERRIDE',reason='Essential gaps prevent final substantive recommendation'))
        context.trace.append(dict(event='COMMITTEE_REGENERATED',fact_revision=context.store.revision,
            argument_revision=context.argument_revision,cited_fact_ids=list(proposed.cited_fact_ids),proposed_decision=proposed.decision.value))
        context.trace.extend(getattr(self.committee,'last_trace',()))

    def review(self, context):
        self.budget.check()
        if not context.gaps:context.stop='EVIDENCE_REVIEW_COMPLETE';return
        context.trace.append(dict(event='EVIDENCE_GAP',questions=list(context.gaps),fact_revision=context.store.revision))
        context.research_pass+=1
        if context.research_pass>=self.request.max_research_passes:context.stop='RESEARCH_PASS_CAP'

    def step(self, stage, context):
        if context.stop:return
        try:getattr(self,stage)(context)
        except BudgetStopped as exc:context.stop=str(exc)

    def finish(self, context):
        result=context.result;gaps=context.gaps;stop=context.stop
        if result is None or gaps or stop!='EVIDENCE_REVIEW_COMPLETE':
            decision=Decision.MORE_DILIGENCE
            rationale='Research incomplete; unresolved facts are unknown, not negative.'
        else:
            decision=result.decision;rationale=result.rationale
        return dict(status='DEPENDENCY_INJECTED_RUNTIME_NOT_A_BACKTEST',decision=decision.value,
            rationale=rationale,essential_gaps=list(gaps) if gaps else ([] if result else ['initial_due_diligence_incomplete']),
            stop_reason=stop,fact_revision=context.store.revision,argument_revision=context.argument_revision,
            admitted_fact_ids=[f.fact_id for f in context.store.facts],trace=context.trace,
            logical_call_budget=self.budget.snapshot(),actual_model_calls=None,actual_network_calls=None,
            accounting_note='Core counts logical dispatch reservations, not external provider billing. Fixture harness supplies verified zero-call counters.')

    def run(self):
        context=RunContext()
        while not context.stop:
            for stage in ('plan','research','evaluate','review'):
                self.step(stage,context)
                if context.stop:break
        return self.finish(context)


@dataclass
class RunContext:
    store: FactStore = field(default_factory=FactStore)
    trace: list = field(default_factory=list)
    gaps: tuple = ()
    tasks: tuple = ()
    research_pass: int = 0
    argument_revision: int = 0
    result: CommitteeResult | None = None
    stop: str | None = None
