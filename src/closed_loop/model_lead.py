"""Model-selected specialist work, using the same metered backend as committee."""
from dataclasses import asdict,dataclass
import json
import re
from types import SimpleNamespace
from datetime import datetime

from .contracts import ResearchRequest,aware
from .guards import BudgetStopped
from .agent_prompts import LEAD_INSTRUCTION, ROLE_BRIEFS
from .native_support import NativeBinding,get_llm,HumanMessage


@dataclass
class PlannedResearch:
    role: str
    question: str
    subject_id: str | None
    source_path: str | None = None


@dataclass
class LeadPlanOutput:
    tasks: list[PlannedResearch]


class ModelLead:
    def __init__(self,backend,budget,max_specialists=2):
        if backend is None:raise ValueError('explicit model backend required')
        if type(max_specialists) is not int or not 1<=max_specialists<=8:raise ValueError('bounded specialist count required')
        self.backend=backend;self.call_budget=budget;self.max_specialists=max_specialists;self.last_calls=[]

    def select(self,request,essential_gaps):
        return self.select_with_context(request,essential_gaps,(),())

    def select_with_context(self,request,essential_gaps,qa_pairs,link_hints,fact_revision=0):
        if request!=self.call_budget.bound_request:raise ValueError('lead budget/request mismatch')
        safe_hints=[]
        keys={'subject_id','url','path','label','observed_at','found_in_source_id','target_content_verified'}
        for hint in link_hints:
            if not isinstance(hint,dict) or set(hint)!=keys:raise ValueError('unexpected historical-link metadata')
            if aware(datetime.fromisoformat(hint['observed_at']))<=request.as_of:safe_hints.append(hint)
        view=SimpleNamespace(company_id=request.company.company_id,mandate=request.mandate,
            as_of=request.as_of.isoformat(),fact_revision=fact_revision,argument_revision=0,qa_pairs=tuple(qa_pairs))
        binding=NativeBinding(self.backend,self.call_budget,view)
        with binding.activate():
            try:
                plan=get_llm(temperature=0).with_structured_output(LeadPlanOutput).invoke([HumanMessage(json.dumps(dict(
                    company_seed=asdict(request.company),essential_gaps=list(essential_gaps),
                    historical_link_hints=safe_hints[:8],
                    role_briefs=ROLE_BRIEFS,
                    instruction=LEAD_INSTRUCTION.format(max_specialists=self.max_specialists))))])
            finally:self.last_calls=list(binding.calls)
        if not isinstance(plan.tasks,list) or len(plan.tasks)>self.max_specialists:raise BudgetStopped('SPECIALIST_PLAN_CAP')
        tasks=[]
        for item in plan.tasks:
            if not isinstance(item,PlannedResearch) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',item.role):raise BudgetStopped('INVALID_SPECIALIST_ROLE')
            if not isinstance(item.question,str) or not item.question.strip() or len(item.question)>1024:raise BudgetStopped('INVALID_RESEARCH_QUESTION')
            tasks.append(ResearchRequest(item.role,item.question,request.company.company_id,item.subject_id,item.source_path))
        return tuple(tasks)
