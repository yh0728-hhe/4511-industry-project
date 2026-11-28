"""Explicit bounded runner for already acquired historical package documents.

No network, credentials, outcomes or implicit model clients. Caller supplies an
independently acquired artifact/metadata pair and explicit backend factory.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path

from .agent_prompts import prompt_fingerprint
from .analysis_acceptance import gate_analysis
from .contracts import digest
from .guards import CallBudget, TemporalGateway
from .model_lead import ModelLead
from .native_committee import NativeConfig, NativeDialecticCommittee
from .package_source import verify_wheel_source
from .npm_source import verify_npm_source
from .runtime import ClosedLoopRuntime
from .thesis_synthesis import ThesisSynthesizer


class VerifiedPackageProvider:
    """Finite document retrieval, not generated answers or current-web research."""
    def __init__(self,request,budget,candidate):
        self.request=request;self.call_budget=budget;self.candidate=candidate
        self.requests=[]

    def search(self,task):
        self.call_budget.check()
        if task.company_id!=self.request.company.company_id:raise ValueError('task identity mismatch')
        self.requests.append(dict(role=task.role,question=task.question,
            subject_id=task.subject_id or task.company_id,source_path=task.source_path))
        if (task.subject_id or task.company_id)!=self.candidate.company_id:return ()
        # No link target is fetched merely because documentation links to it.
        if task.source_path is not None:return ()
        return (self.candidate,)


def execute_package_run(*,request,artifact_bytes,file_metadata,expected_package,
                        output_dir,backend_factory,approved=False,artifact_format="wheel",call_budget=None,check_argument_support=False):
    """Source-first gate, exclusive output directory and existing full runtime.

    Limits count backend dispatch reservations, not inner RPCs or dollars.
    Auth/billing approval must be checked by the caller before invoking this.
    No retries or fallback. A new directory never authorizes replay of a sealed
    experiment; the caller owns the experiment-wide one-attempt lease.
    """
    if approved is not True:raise PermissionError('explicit execution approval required')
    if type(check_argument_support) is not bool:raise ValueError('explicit boolean support-check flag required')
    remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
    if (not 0<remaining<=480 or not 1<=request.max_model_calls<=24 or
        not 0<=request.max_search_calls<=2 or request.concurrency!=1 or
        not 1<=request.max_research_passes<=2):raise ValueError('bounded package run required')
    if not callable(backend_factory):raise ValueError('explicit backend factory required')
    budget=call_budget if call_budget is not None else CallBudget(request)
    if budget.bound_request!=request:raise ValueError('shared budget/request mismatch')
    budget.check()
    if artifact_format not in ('wheel','npm'):
        raise ValueError('explicit supported package artifact format required')
    verifier=verify_wheel_source if artifact_format=='wheel' else verify_npm_source
    candidate,record=verifier(artifact_bytes,file_metadata,expected_package,request)
    gateway=TemporalGateway(request,[record])
    fact,error=gateway.admit(candidate)
    if error or fact is None:raise ValueError('historical source preflight failed')
    budget.check()
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
    plan=dict(status='SOURCE_ADMITTED_BEFORE_MODEL_CONSTRUCTION',company=asdict(request.company),
        as_of=request.as_of.isoformat(),mandate=request.mandate,model=request.model_version,
        source_policy=request.source_policy,prompt_version=request.prompt_version,
        argument_support_check_enabled=check_argument_support,
        prompt_bundle_sha256=prompt_fingerprint(),max_model_calls=request.max_model_calls,
        max_http_requests=request.max_search_calls,
        registry_transport_attempts_before_model=budget.used['search'],
        deadline=request.deadline.isoformat(),
        source_id=candidate.source_id,source_sha256=record.content_sha256,
        artifact_sha256=hashlib.sha256(artifact_bytes).hexdigest(),artifact_format=artifact_format,source_url=candidate.url,
        uploaded=record.availability_upper_bound.isoformat(),
        evidence_scope='Embedded package README; publisher claims, not independently verified business metrics',
        historical_domain_ownership_independently_proven=False,Y_read=False,
        pretrained_future_knowledge_exclusion_proven=False)
    plan['fingerprint']=digest(json.dumps(plan,sort_keys=True))
    (root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    try:
        backend=backend_factory(budget,root)
        if getattr(backend,'call_budget',budget) is not budget:raise ValueError('backend budget mismatch')
        provider=VerifiedPackageProvider(request,budget,candidate)
        committee=NativeDialecticCommittee(backend,budget,NativeConfig(selection_policy='balanced_per_side'))
        if check_argument_support:
            from .evidence_checked_committee import EvidenceCheckedCommittee
            from .ragas_faithfulness import RagasFaithfulnessChecker
            from .evidence_gap_triage import EvidenceGapTriage
            committee=EvidenceCheckedCommittee(committee,RagasFaithfulnessChecker(backend,budget),budget,
                gap_triage=EvidenceGapTriage(backend,budget))
        runtime=ClosedLoopRuntime(request,gateway,budget,ModelLead(backend,budget),
            committee,provider,thesis=ThesisSynthesizer(backend,budget))
        proposal=runtime.run()
        (root/'proposal.json').write_text(json.dumps(proposal,indent=2)+'\n',encoding='utf-8')
        final_packet={key:proposal[key] for key in
            ('decision','rationale','admitted_fact_ids','essential_gaps','thesis')}
        acceptance=gate_analysis(final_packet,plan['fingerprint'])
        result=dict(proposal)
        result.update(proposed_decision=acceptance['proposed_decision'],
            decision=acceptance['decision'],acceptance=acceptance,
            unreviewed_draft_trace=True)
        if proposal['decision'] in ('INVEST','PASS') and acceptance['decision']=='MORE_DILIGENCE':
            result.update(proposed_thesis=proposal['thesis'],thesis=None,
                proposed_rationale=proposal['rationale'],
                rationale='A complete source-bound final-analysis review is required before accepting the proposal.',
                essential_gaps=list(dict.fromkeys([*proposal['essential_gaps'],'final_analysis_review'])))
        result.update(status='PACKAGE_SOURCE_RUNTIME_EXECUTED',
            argument_support_check_enabled=check_argument_support,
            source_scope=plan['evidence_scope'],cli_process_attempts=getattr(backend,'process_count',None),
            actual_model_calls=None,actual_network_calls=0 if budget.used['search']==0 else None,
            registry_transport_attempts=budget.used['search'],
            inference_requests='UNKNOWN',invoice='UNKNOWN',training_run=False,Y_changed=False,
            predictive_accuracy_evaluated=False,analysis_review_status=acceptance['acceptance_state'],
            semantic_support_certified=False,provider_requests=provider.requests,
            model_trace=runtime.committee.last_trace)
    except Exception:
        budget.stop('PACKAGE_RUN_FAILED')
        result=dict(status='PACKAGE_RUN_FAILED',reason='SANITIZED_EXECUTION_FAILURE',
            logical_call_budget=budget.snapshot(),training_run=False,Y_changed=False)
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result
