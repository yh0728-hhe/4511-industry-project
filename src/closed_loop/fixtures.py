"""Invented companies/text and trusted fixture ledger; never target-company data."""
from dataclasses import replace
from datetime import datetime, timezone

from .contracts import CompanySeed, RunRequest, ResearchRequest, CommitteeResult, Decision, digest
from .guards import CallBudget, SourceCandidate, VerifiedRecord, TemporalGateway
from .runtime import ClosedLoopRuntime
from .dialectic_adapter import ScoredArgument, aggregate_arguments


def stamp(value):return datetime.fromisoformat(value.replace('Z','+00:00'))


def request(**updates):
    baseline=RunRequest(CompanySeed('SYNTHETIC_COMPANY','Synthetic Company','synthetic.example'),
        'Seed software mandate; inspect market and retention before investing.',
        stamp('2024-04-04T23:59:59Z'),'fixture-policy-v1','NO_MODEL_FIXTURE','fixture-prompts-v1',
        stamp('2099-01-01T00:00:00Z'),20,20,1,3)
    return replace(baseline,**updates)


def source(source_id,topic,text,available='2024-03-20T00:00:00Z',**updates):
    candidate=SourceCandidate(source_id,'https://synthetic.example/'+source_id,
        'SYNTHETIC_COMPANY',topic,text)
    record=VerifiedRecord(source_id,candidate.url,candidate.company_id,topic,digest(text),
        stamp(available),'READABLE_ARCHIVE',True,stamp(available),stamp(available))
    return candidate,replace(record,**updates)


class FixtureLead:
    def select(self, req, gaps):
        if gaps:return tuple(ResearchRequest('traction',gap,req.company.company_id) for gap in gaps)
        # A two-role choice, not the old hardcoded four specialist stages.
        return (ResearchRequest('market','market',req.company.company_id),
                ResearchRequest('traction','traction',req.company.company_id))


class FixtureCommittee:
    def evaluate(self, view):
        ids=tuple(row['fact_id'] for row in view.qa_pairs)
        answers=[row['answer'] for row in view.qa_pairs if row['subject_id']==view.company_id]
        if 'SYNTHETIC_RETENTION_GOOD' in answers:
            decision=aggregate_arguments((ScoredArgument('pro',80,ids),ScoredArgument('contra',30,ids)),ids)
            return CommitteeResult(decision,'Synthetic retention criterion met.',(),view.fact_revision,view.argument_revision,ids)
        if 'SYNTHETIC_RETENTION_POOR' in answers:
            decision=aggregate_arguments((ScoredArgument('pro',30,ids),ScoredArgument('contra',80,ids)),ids)
            return CommitteeResult(decision,'Observed synthetic poor retention; not missingness.',(),view.fact_revision,view.argument_revision,ids)
        return CommitteeResult(Decision.MORE_DILIGENCE,'Retention not yet established.',('retention',),view.fact_revision,view.argument_revision,ids)


class FixtureProvider:
    def __init__(self, good=True, empty=False):
        self.market,self.market_record=source('market-2024','market','SYNTHETIC_MARKET_CONTEXT')
        self.retention,self.retention_record=source('retention-2024','retention',
            'SYNTHETIC_RETENTION_GOOD' if good else 'SYNTHETIC_RETENTION_POOR')
        self.ledger={r.source_id:r for r in (self.market_record,self.retention_record)}
        self.empty=empty

    def search(self, task):
        if task.question=='market':return (self.market,)
        if task.question=='retention' and not self.empty:return (self.retention,)
        return ()


def run_case(good=True,empty=False,driver='python',**request_updates):
    req=request(**request_updates);provider=FixtureProvider(good,empty)
    runtime=ClosedLoopRuntime(req,TemporalGateway(req,provider.ledger),CallBudget(req),
        FixtureLead(),FixtureCommittee(),provider)
    if driver=='python':result=runtime.run()
    elif driver=='langgraph':
        from .graph_driver import run_graph
        result=run_graph(runtime)
    else:raise ValueError('unknown driver')
    result.update(status='OFFLINE_FIXTURE_ONLY_NOT_AN_INVESTMENT_PREDICTION',actual_model_calls=0,actual_network_calls=0,
        accounting_note='Only repository-owned deterministic fixture components executed; logical model/search reservations are not paid API calls.')
    return result
