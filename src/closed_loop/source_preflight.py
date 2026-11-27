"""Explicit source-only preflight sharing the real archive/gateway/budget.

No model/client/provider construction, credentials, outcomes or implicit I/O.
Domain ownership remains caller-anchored, not independently certified here.
"""
from dataclasses import dataclass
from enum import Enum
from .archive_transport import RetrievalFailed
from .contracts import ResearchRequest
from .guards import BudgetStopped


class PreflightState(str, Enum):
    ADMITTED_SOURCE = 'ADMITTED_SOURCE'
    NO_ADMISSIBLE_SOURCE = 'NO_ADMISSIBLE_SOURCE'
    ACCESS_RESTRICTED = 'ACCESS_RESTRICTED'
    RATE_LIMITED = 'RATE_LIMITED'
    STOPPED = 'STOPPED'
    TRANSPORT_ERROR = 'TRANSPORT_ERROR'


@dataclass(frozen=True)
class PreflightResult:
    state: PreflightState
    ready_for_dispatch: bool
    admitted_fact_ids: tuple[str, ...]
    stop_reason: str | None
    http_requests_delta: int
    total_http_requests: int
    historical_domain_ownership_independently_verified: bool = False


def source_readiness_preflight(request, gateway, budget, archive_provider):
    if gateway.request != request or budget.bound_request != request:
        raise ValueError('gateway/budget must be bound to the supplied request')
    if (archive_provider.request != request or archive_provider.gateway is not gateway
            or archive_provider.call_budget is not budget):
        raise ValueError('archive provider must share request/gateway/budget')
    before=budget.used['search'];attempt_start=len(archive_provider.attempts)
    admitted=[];retrieval_failed=False
    task=ResearchRequest('preflight','Historical homepage preflight',request.company.company_id,source_path='/')
    try:
        budget.check()  # Cached roots cannot bypass a stopped/expired run.
        for candidate in archive_provider.search(task):
            fact,_rejection=gateway.admit(candidate,task.subject_id)
            if fact is not None:admitted.append(fact.fact_id)
        budget.check()
    except BudgetStopped as exc:
        budget.stop(str(exc))
    except RetrievalFailed:
        retrieval_failed=True
    count=budget.used['search'];ids=tuple(dict.fromkeys(admitted))
    def result(state,ready,reason):
        return PreflightResult(state,ready,ids,reason,count-before,count)
    if budget.stopped:
        state={'ARCHIVE_ACCESS_RESTRICTED':PreflightState.ACCESS_RESTRICTED,
               'ARCHIVE_RATE_LIMITED':PreflightState.RATE_LIMITED}.get(budget.stop_reason,PreflightState.STOPPED)
        return result(state,False,budget.stop_reason)
    statuses=[x.get('status') for x in archive_provider.attempts[attempt_start:]]
    if retrieval_failed or 'HTTP_TRANSPORT_ERROR' in statuses:
        return result(PreflightState.TRANSPORT_ERROR,False,'SOURCE_PREFLIGHT_TRANSPORT_ERROR')
    if ids:return result(PreflightState.ADMITTED_SOURCE,True,None)
    reason=next((s for s in reversed(statuses) if s and s!='HTTP_200'),'NO_ADMISSIBLE_SOURCE')
    return result(PreflightState.NO_ADMISSIBLE_SOURCE,False,reason)
