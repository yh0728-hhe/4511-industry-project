"""Bounded model-guided specialist research action loop: SUBMIT_FACT | FOLLOW_LINK | STOP.

Fills the audited gap where `ClosedLoopRuntime.research` only issued one
`provider.search()` per task with no specialist-level decision point. Each
`FOLLOW_LINK` consumes one additional `provider.search` reservation under the
SAME run `call_budget`, driven by the model reading admitted facts and the
provider's own `link_hints()` for THIS task, not a new autonomous tool/network
surface. `RESEARCH_PROTOCOL` is reused verbatim and placed in the real request
payload (not merely hashed into a fingerprint, unlike before this change).
"""
from dataclasses import dataclass, replace
import json
from types import SimpleNamespace

from .agent_prompts import RESEARCH_PROTOCOL
from .guards import BudgetStopped
from .native_support import NativeBinding, get_llm, HumanMessage


@dataclass
class SpecialistAction:
    decision: str
    path: str | None = None
    reason: str | None = None


def _fact_row(task, fact):
    return dict(question=f'What is the supported evidence for {fact.topic} about this evidence subject?',
        answer=fact.text, fact_id=fact.fact_id, source_id=fact.source_id, url=fact.url,
        subject_id=fact.company_id, available_by=fact.availability_upper_bound.isoformat(),
        reliability=fact.proof_kind)


class SpecialistResearchLoop:
    """One specialist task, several model-decided dispatch rounds, one shared budget.

    Mirrors `ModelLead`'s explicit-backend/bounded-count pattern: no implicit
    default backend, no unbounded iteration count.
    """
    def __init__(self, backend, budget, max_iterations=4):
        if backend is None:raise ValueError('explicit specialist model backend required')
        if type(max_iterations) is not int or not 1<=max_iterations<=8:raise ValueError('bounded iteration count required')
        self.backend=backend;self.call_budget=budget;self.max_iterations=max_iterations;self.last_calls=[]

    def run(self, task, provider, gateway, trace, as_of, fact_revision=0):
        subject=task.subject_id or task.company_id
        tried_paths={task.source_path} if task.source_path else set()
        admitted=[]
        admitted.extend(self._admit(self._dispatch(provider,task),gateway,task,trace))
        calls=[]
        for _ in range(self.max_iterations):
            hints=tuple(h for h in getattr(provider,'link_hints',lambda:())()
                if h.get('subject_id')==subject and h.get('path') not in tried_paths)
            action=self._decide(task,admitted,hints,as_of,fact_revision)
            calls.extend(self.last_calls)
            trace.append(dict(event='SPECIALIST_LOOP_STEP',role=task.role,subject_id=subject,
                action=action.decision,path=action.path,reason=action.reason))
            if action.decision=='STOP':break
            if action.decision=='SUBMIT_FACT':break
            if action.decision=='FOLLOW_LINK':
                available={h['path'] for h in hints}
                if not action.path or action.path in tried_paths or action.path not in available:
                    trace.append(dict(event='SPECIALIST_LOOP_STEP',role=task.role,subject_id=subject,
                        action='STOP',path=None,reason='NO_NEW_CONCRETE_LEAD'))
                    break
                tried_paths.add(action.path)
                follow_up=replace(task,source_path=action.path)
                admitted.extend(self._admit(self._dispatch(provider,follow_up),gateway,task,trace))
                continue
            raise BudgetStopped('INVALID_SPECIALIST_ACTION')
        self.last_calls=calls
        return tuple(admitted)

    def _dispatch(self, provider, task):
        if getattr(provider,'call_budget',None) is self.call_budget:
            return tuple(provider.search(task))
        with self.call_budget.reserve('search'):
            return tuple(provider.search(task))

    def _admit(self, candidates, gateway, task, trace):
        admitted=[]
        for candidate in candidates:
            fact,rejection=gateway.admit(candidate,task.subject_id)
            if fact is not None:admitted.append(fact)
            else:trace.append(dict(event='SOURCE_HELD',**rejection))
        return admitted

    def _decide(self, task, admitted, hints, as_of, fact_revision):
        view=SimpleNamespace(company_id=task.company_id,mandate=RESEARCH_PROTOCOL,as_of=as_of.isoformat(),
            fact_revision=fact_revision,argument_revision=0,qa_pairs=tuple(_fact_row(task,fact) for fact in admitted))
        binding=NativeBinding(self.backend,self.call_budget,view)
        payload=dict(research_protocol=RESEARCH_PROTOCOL,role=task.role,question=task.question,
            subject_id=task.subject_id or task.company_id,
            admitted_fact_ids=[fact.fact_id for fact in admitted],
            link_hints=[dict(h) for h in hints])
        with binding.activate():
            try:
                action=get_llm(temperature=0).with_structured_output(SpecialistAction).invoke([HumanMessage(json.dumps(payload))])
            finally:self.last_calls=list(binding.calls)
        if not isinstance(action,SpecialistAction) or action.decision not in ('SUBMIT_FACT','FOLLOW_LINK','STOP'):
            raise BudgetStopped('INVALID_SPECIALIST_ACTION')
        if action.decision=='FOLLOW_LINK' and (not isinstance(action.path,str) or not action.path.startswith('/')):
            raise BudgetStopped('INVALID_SPECIALIST_ACTION')
        return action
