"""Run reused DIALECTIC generation/critique/score/refine stages on admitted facts.

Backend injection is mandatory. No provider, .env loader, search function or
original import-time model initializer is used. This adapter is historical-safe
plumbing, not an unchanged upstream baseline or a paper-replication claim.
"""
import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from threading import Lock
from datetime import datetime

from .contracts import CommitteeResult, Decision, aware
from .native_support import NativeBinding, get_llm, EvidenceReviewOutput, HumanMessage
from .guards import BudgetStopped
from .agent_prompts import EVIDENCE_REVIEW_INSTRUCTION
from .vendor import dialectic_committee_nodes as nodes


@dataclass(frozen=True)
class NativeConfig:
    n_pro_arguments: int = 1
    n_contra_arguments: int = 1
    k_best_arguments_per_iteration: tuple[int,...] = (1,)
    max_iterations: int = 1
    selection_policy: str = 'legacy_global'

    def __post_init__(self):
        for value in (self.n_pro_arguments,self.n_contra_arguments,self.max_iterations):
            if type(value) is not int or value<1:raise ValueError('positive native-stage bounds required')
        if not isinstance(self.k_best_arguments_per_iteration,tuple) or not self.k_best_arguments_per_iteration or any(type(x) is not int or x<1 for x in self.k_best_arguments_per_iteration):
            raise ValueError('explicit retained-argument counts required')
        if self.selection_policy not in ('legacy_global','balanced_per_side'):raise ValueError('explicit selection policy required')


class NativeState(SimpleNamespace):
    @property
    def should_continue_iterations(self):return self.current_iteration<self.config.max_iterations
    def get_current_k_best(self):
        return self.config.k_best_arguments_per_iteration[min(self.current_iteration,len(self.config.k_best_arguments_per_iteration)-1)]


def new_state(view,config):
    values=dict(config=config,all_qa_pairs=[dict(row) for row in view.qa_pairs],current_iteration=0,
        arguments_history=[],is_final=False,final_decision=None)
    for name in ('pro_arguments','contra_arguments','current_arguments','selected_arguments','refined_arguments',
            'devils_advocate_pro_arguments','devils_advocate_contra_arguments','refined_pro_arguments',
            'refined_contra_arguments','final_arguments'):
        values[name]=[]
    return NativeState(**values)


def apply(state,update):
    if isinstance(update,dict):
        for name,value in update.items():setattr(state,name,value)


class NativeDialecticCommittee:
    def __init__(self, backend, budget, config=None):
        if backend is None:raise ValueError('explicit model backend required; no live fallback')
        self.backend=backend;self.call_budget=budget;self.config=config or NativeConfig()
        self.last_trace=[];self.last_calls=[]
        self._evaluation_lock=Lock()

    def evaluate(self,view):return asyncio.run(self.evaluate_async(view))

    async def evaluate_async(self,view):
        if not self._evaluation_lock.acquire(blocking=False):raise BudgetStopped('COMMITTEE_INSTANCE_BUSY')
        try:return await self._evaluate_async(view)
        finally:self._evaluation_lock.release()

    async def _evaluate_async(self,view):
        self.last_trace=[];self.last_calls=[]
        req=self.call_budget.bound_request
        if (view.company_id,view.mandate,datetime.fromisoformat(view.as_of))!=(req.company.company_id,req.mandate,req.as_of):
            raise ValueError('committee view does not match bound request')
        for row in view.qa_pairs:
            try:available=aware(datetime.fromisoformat(row['available_by']))
            except (KeyError,TypeError,ValueError):raise BudgetStopped('UNVERIFIED_QA_DATE') from None
            if available>req.as_of:raise BudgetStopped('FUTURE_QA_DATE')
        if not view.qa_pairs:
            return CommitteeResult(Decision.MORE_DILIGENCE,'No admitted evidence.',('minimum_historical_evidence',),view.fact_revision,view.argument_revision,())
        state=new_state(view,self.config)
        binding=NativeBinding(self.backend,self.call_budget,view)
        def event(stage):
            arguments=state.refined_arguments if stage=='refinement' else (state.final_arguments if stage=='final_aggregation' else state.current_arguments)
            snapshots=[]
            for argument in arguments:
                indices=argument.refined_qa_indices if stage=='refinement' else argument.qa_indices
                snapshots.append(dict(tracking_id=argument.tracking_id,role=argument.argument_type,
                    text=(argument.refined_content if stage=='refinement' else argument.content),
                    critique=argument.critique,quality_total=argument.score,
                    cited_fact_ids=[view.qa_pairs[i]['fact_id'] for i in indices],
                    source_support_not_semantically_certified=True))
            self.last_trace.append(dict(event='NATIVE_COMMITTEE_STAGE',stage=stage,
                fact_revision=view.fact_revision,argument_revision=view.argument_revision,
                qa_fact_ids=[x['fact_id'] for x in view.qa_pairs],
                iteration=state.current_iteration,
                current_types=[x.argument_type for x in state.current_arguments],
                selected_types=[x.argument_type for x in state.selected_arguments],arguments=snapshots))
        with binding.activate():
            try:
                apply(state,nodes.generate_pro_arguments(state))
                apply(state,nodes.generate_contra_arguments(state))
                if len(state.pro_arguments)!=self.config.n_pro_arguments or len(state.contra_arguments)!=self.config.n_contra_arguments:
                    raise ValueError('model generated an unexpected argument count')
                apply(state,nodes.merge_arguments(state));event('generation')
                while state.should_continue_iterations:
                    apply(state,await nodes.apply_devils_advocate_to_pro_arguments(state))
                    apply(state,await nodes.apply_devils_advocate_to_contra_arguments(state));event('critique')
                    apply(state,await nodes.score_and_select_best_k(state))
                    if self.config.selection_policy=='balanced_per_side':
                        k=state.get_current_k_best()
                        state.selected_arguments=[arg for side in ('pro','contra') for arg in
                            sorted((x for x in state.current_arguments if x.argument_type==side),key=lambda x:x.score,reverse=True)[:k]]
                    event('score_and_select')
                    apply(state,await nodes.refine_pro_arguments(state))
                    apply(state,await nodes.refine_contra_arguments(state))
                    apply(state,nodes.merge_refined_arguments(state));event('refinement')
                    nodes.add_arguments_to_history(state)
                    nodes.reset_arguments_and_increment_iteration(state)
                await nodes.prepare_final_arguments(state)
                nodes.decide_final_investment_decision(state);event('final_aggregation')
                review=await get_llm(temperature=0).with_structured_output(EvidenceReviewOutput).ainvoke([
                    HumanMessage(json.dumps(dict(instruction=EVIDENCE_REVIEW_INSTRUCTION,
                        debate_trace=self.last_trace,
                        trace_semantics='Arguments and criticisms are analysis, not new verified facts. '
                            'Identify essential evidence gaps exposed by the debate; use only admitted facts as factual support.')))])
                event('evidence_review')
                cited=[]
                for argument in state.final_arguments:
                    for index in argument.qa_indices:
                        if type(index) is not int or not 0<=index<len(view.qa_pairs):raise ValueError('obsolete QA index')
                        cited.append(view.qa_pairs[index]['fact_id'])
                decision=Decision.MORE_DILIGENCE if review.essential_gaps else (Decision.INVEST if state.final_decision=='invest' else Decision.PASS)
                return CommitteeResult(decision,review.rationale,tuple(review.essential_gaps),view.fact_revision,
                    view.argument_revision,tuple(dict.fromkeys(cited)))
            finally:self.last_calls=list(binding.calls)
