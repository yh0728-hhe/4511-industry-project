"""Injected, metered model seam for reused DIALECTIC stage bodies.

No API/SDK client or credential loader is imported. A backend must be supplied
explicitly. Context variables isolate companies when adapted nodes run concurrently.
"""
import asyncio
from contextlib import contextmanager,nullcontext
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
import json

from .contracts import digest,aware
from .agent_prompts import HISTORICAL_GUARD, VERSION, prompt_fingerprint
from .guards import BudgetStopped


@dataclass
class Message:
    content: str

@dataclass
class SystemMessage(Message):
    role: str = 'system'


@dataclass
class HumanMessage(Message):
    role: str = 'user'


@dataclass
class ArgumentOutput:
    content: str
    qa_indices: list[int]


@dataclass
class ArgumentsOutput:
    arguments: list[ArgumentOutput]


@dataclass
class ArgumentCritique:
    critique: str


@dataclass
class CriterionScore:
    score: int
    reasoning: str


@dataclass
class SingleArgumentScore:
    scores: list[CriterionScore]


@dataclass
class IndividualRefinedArgumentOutput:
    content: str
    qa_indices: list[int]


@dataclass
class EvidenceReviewOutput:
    essential_gaps: list[str]
    rationale: str


@dataclass
class Argument:
    content: str
    argument_type: str
    qa_indices: list[int]
    tracking_id: str = ''
    qa_pairs: list[dict] = field(default_factory=list)
    score: int = 0
    argument_feedback: str | None = None
    critique: str | None = None
    refined_content: str | None = None
    refined_qa_indices: list[int] | None = None
    former_critique: str | None = None
    id: str = ''

    def __post_init__(self):
        if not self.id:self.id=digest(json.dumps([self.content,self.argument_type,self.qa_indices,self.tracking_id]))


_binding=ContextVar('closed_loop_native_binding',default=None)


@dataclass
class NativeBinding:
    backend: object
    budget: object
    view: object
    prompt_byte_cap: int = 64000
    calls: list = field(default_factory=list)
    semaphore: object = None

    def __post_init__(self):
        owned=getattr(self.backend,'call_budget',None)
        if owned is not None and owned is not self.budget:
            raise ValueError('backend and binding must share the same call budget')

    @contextmanager
    def activate(self):
        token=_binding.set(self)
        try:yield self
        finally:_binding.reset(token)

    def messages(self, supplied):
        cutoff=aware(datetime.fromisoformat(self.view.as_of))
        for row in self.view.qa_pairs:
            try:available=aware(datetime.fromisoformat(row['available_by']))
            except (TypeError,KeyError,ValueError):raise BudgetStopped('UNVERIFIED_QA_DATE') from None
            if available>cutoff:raise BudgetStopped('FUTURE_QA_DATE')
        context=dict(company_id=self.view.company_id,mandate=self.view.mandate,
            as_of=self.view.as_of,fact_revision=self.view.fact_revision,
            evidence=list(self.view.qa_pairs))
        context['prompt_bundle']=dict(version=VERSION, fingerprint=prompt_fingerprint())
        guard=SystemMessage(HISTORICAL_GUARD+json.dumps(context,sort_keys=True))
        messages=[guard,*supplied]
        if sum(len(m.content.encode('utf-8')) for m in messages)>self.prompt_byte_cap:
            raise BudgetStopped('PROMPT_BYTE_CAP')
        return messages

    def validate(self, schema, value):
        if not isinstance(value,schema):raise BudgetStopped('INVALID_MODEL_SCHEMA')
        if isinstance(value,ArgumentsOutput):
            if not isinstance(value.arguments,list) or not value.arguments:raise BudgetStopped('EMPTY_ARGUMENTS')
            arguments=value.arguments
        elif isinstance(value,IndividualRefinedArgumentOutput):arguments=[value]
        else:arguments=[]
        for argument in arguments:
            if not isinstance(argument.content,str) or not argument.content.strip():raise BudgetStopped('EMPTY_ARGUMENT')
            indices=argument.qa_indices
            if not isinstance(indices,list) or not indices or any(type(i) is not int or not 0<=i<len(self.view.qa_pairs) for i in indices):
                raise BudgetStopped('INVALID_QA_CITATION')
        if isinstance(value,SingleArgumentScore):
            if not isinstance(value.scores,list) or any(not isinstance(c,CriterionScore) or type(c.score) is not int or not 1<=c.score<=7 for c in value.scores):
                raise BudgetStopped('INVALID_CRITERION_SCORE')
            # Upstream retries an incorrect criterion COUNT; each retry remains metered.
        if isinstance(value,ArgumentCritique) and (not isinstance(value.critique,str) or not value.critique.strip()):
            raise BudgetStopped('EMPTY_CRITIQUE')
        if isinstance(value,EvidenceReviewOutput):
            if not isinstance(value.essential_gaps,list) or not all(isinstance(x,str) and x.strip() for x in value.essential_gaps):
                raise BudgetStopped('INVALID_EVIDENCE_REVIEW')
            if not isinstance(value.rationale,str) or not value.rationale.strip():raise BudgetStopped('EMPTY_EVIDENCE_REVIEW')
        return value


class StructuredModel:
    def __init__(self, binding, schema, temperature):
        self.binding=binding;self.schema=schema;self.temperature=temperature

    def reservation(self):
        # A concrete live transport owns physical-request metering; fixture
        # backends use this wrapper's logical reservation. Never charge twice.
        if getattr(self.binding.backend,'call_budget',None) is self.binding.budget:return nullcontext()
        return self.binding.budget.reserve('model')

    def invoke(self, supplied):
        messages=self.binding.messages(supplied)
        with self.reservation():
            self.binding.calls.append(dict(schema=self.schema.__name__,temperature=self.temperature,
                fact_revision=self.binding.view.fact_revision,argument_revision=self.binding.view.argument_revision))
            try:value=self.binding.backend.generate(self.schema,messages,self.temperature)
            except BudgetStopped:raise
            except Exception:raise BudgetStopped('MODEL_PROVIDER_ERROR') from None
            return self.binding.validate(self.schema,value)

    async def ainvoke(self, supplied):
        messages=self.binding.messages(supplied)
        if self.binding.semaphore is None:self.binding.semaphore=asyncio.Semaphore(self.binding.budget.concurrency)
        async with self.binding.semaphore:
            with self.reservation():
                self.binding.calls.append(dict(schema=self.schema.__name__,temperature=self.temperature,
                    fact_revision=self.binding.view.fact_revision,argument_revision=self.binding.view.argument_revision))
                try:
                    if hasattr(self.binding.backend,'agenerate'):
                        value=await self.binding.backend.agenerate(self.schema,messages,self.temperature)
                    else:value=await asyncio.to_thread(self.binding.backend.generate,self.schema,messages,self.temperature)
                except BudgetStopped:raise
                except Exception:raise BudgetStopped('MODEL_PROVIDER_ERROR') from None
                return self.binding.validate(self.schema,value)


class BoundModel:
    def __init__(self,binding,temperature):self.binding=binding;self.temperature=temperature
    def with_structured_output(self,schema):return StructuredModel(self.binding,schema,self.temperature)


def get_llm(temperature=0.5,**kwargs):
    active=_binding.get()
    if active is None:raise RuntimeError('No explicit metered model backend bound; live fallback forbidden')
    return BoundModel(active,temperature)


class LazyModel:
    def with_structured_output(self,schema):return get_llm(temperature=0.5).with_structured_output(schema)


llm=LazyModel()
