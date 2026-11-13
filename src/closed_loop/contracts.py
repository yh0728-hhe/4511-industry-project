"""Strict runtime contracts. Facts are acquired during execution, not input packets."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import re


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone-aware datetime required')
    return value


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


class Decision(str, Enum):
    INVEST='INVEST'
    PASS='PASS'
    MORE_DILIGENCE='MORE_DILIGENCE'


@dataclass(frozen=True)
class CompanySeed:
    company_id: str
    name: str
    domain: str

    def __post_init__(self):
        if not all(isinstance(v,str) and v.strip() for v in (self.company_id,self.name,self.domain)):
            raise ValueError('company identity required; no example fallback')
        if not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', self.domain) or len(self.domain)>253:
            raise ValueError('bare lower-case domain required')

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value,dict) or set(value)!={'company_id','name','domain'}:
            raise ValueError('seed requires exactly company_id/name/domain; modern analytical fields forbidden')
        return cls(**value)


@dataclass(frozen=True)
class RunRequest:
    company: CompanySeed
    mandate: str
    as_of: datetime
    source_policy: str
    model_version: str
    prompt_version: str
    deadline: datetime
    max_model_calls: int
    max_search_calls: int
    concurrency: int = 1
    max_research_passes: int = 3

    def __post_init__(self):
        if not isinstance(self.company,CompanySeed):raise ValueError('validated company seed required')
        for value in (self.mandate,self.source_policy,self.model_version,self.prompt_version):
            if not isinstance(value,str) or not value.strip():raise ValueError('explicit mandate and versions required')
        aware(self.as_of);aware(self.deadline)
        for value in (self.max_model_calls,self.max_search_calls):
            if type(value) is not int or value<0:raise ValueError('nonnegative integer call caps required')
        for value in (self.concurrency,self.max_research_passes):
            if type(value) is not int or value<1:raise ValueError('positive integer bounds required')

    def cache_key(self, role, question, subject_id=None,source_path=None):
        # UTC-equivalent timestamps share a namespace, unlike genuinely different cutoffs.
        from datetime import timezone
        from .agent_prompts import prompt_fingerprint
        context=dict(company_id=self.company.company_id,domain=self.company.domain,
            as_of=self.as_of.astimezone(timezone.utc).isoformat(),mandate=self.mandate,
            source_policy=self.source_policy,model=self.model_version,prompt=self.prompt_version,
            role=role,question=question,subject_id=subject_id or self.company.company_id,source_path=source_path,
            prompt_bundle=prompt_fingerprint())
        return digest(json.dumps(context,sort_keys=True,separators=(',',':')))


@dataclass(frozen=True)
class ResearchRequest:
    role: str
    question: str
    company_id: str
    subject_id: str | None = None
    source_path: str | None = None

    def __post_init__(self):
        if not all(isinstance(v,str) and v.strip() for v in (self.role,self.question,self.company_id)):
            raise ValueError('explicit specialist/question/identity required')
        if self.subject_id is not None and (not isinstance(self.subject_id,str) or not self.subject_id.strip()):
            raise ValueError('explicit peer/market subject identity required')
        if self.source_path is not None and (not isinstance(self.source_path,str) or not self.source_path.startswith('/') or
                self.source_path.startswith('//') or len(self.source_path)>512 or '..' in self.source_path.split('/')):
            raise ValueError('bounded relative historical source path required')


@dataclass(frozen=True)
class Fact:
    fact_id: str
    source_id: str
    company_id: str
    topic: str
    text: str
    url: str
    availability_upper_bound: datetime
    content_sha256: str
    proof_kind: str


@dataclass(frozen=True)
class CommitteeResult:
    decision: Decision
    rationale: str
    essential_gaps: tuple[str,...]
    fact_revision: int
    argument_revision: int
    cited_fact_ids: tuple[str,...]

    def __post_init__(self):
        if not isinstance(self.decision,Decision) or not isinstance(self.rationale,str) or not self.rationale.strip():
            raise ValueError('typed decision and rationale required')
        for values in (self.essential_gaps,self.cited_fact_ids):
            if not isinstance(values,tuple) or not all(isinstance(x,str) and x.strip() for x in values):
                raise ValueError('immutable nonempty gap/citation strings required')
        if any(type(x) is not int or x<0 for x in (self.fact_revision,self.argument_revision)):
            raise ValueError('nonnegative integer revisions required')
