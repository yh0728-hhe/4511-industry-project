"""Bounded discovery -> independent archive verification -> research/debate entry.

Caller verifies existing CLI authentication/billing. No implicit network/model
clients, credentials, training inputs, or outcome labels are constructed here.
"""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib

from .agent_prompts import prompt_fingerprint
from .analysis_acceptance import gate_analysis
from .archive_transport import ArchivedWebsiteProvider
from .archived_publisher import ArchivedPublisherVerifier
from .discovered_package import DiscoveredPackageVerifier
from .contracts import RunRequest, CompanySeed, digest
from .discovered_research import DiscoveredResearchProvider
from .guards import BudgetStopped, CallBudget, TemporalGateway
from .model_lead import ModelLead
from .native_committee import NativeConfig, NativeDialecticCommittee
from .progressive_committee import ProgressiveCommittee
from .runtime import ClosedLoopRuntime
from .single_analyst import SingleAnalystBaseline
from .thesis_synthesis import ThesisSynthesizer

_NORMAL_STOPS={'EVIDENCE_REVIEW_COMPLETE','NO_NEW_EVIDENCE','RESEARCH_PASS_CAP','NO_RESEARCH_TASKS','NO_ADMITTED_FACTS'}

def execute_discovery_run(*,request,output_dir,backend_factory,discovery_factory,http_client,
                          approved=False,domain_anchors=None,check_argument_support=True,max_sources=2,verify_publishers=False,
                          max_specialists=2,publisher_max_body_bytes=262144,preliminary_screen=False,
                          verify_packages=False,registry_http_client=None):
    """One exclusive bounded run; no retry, fallback, scheduler or resume.

    Search reservations count managed discovery invocations plus direct archive
    requests; managed internal HTTP/inference counts remain unknown.
    """
    if approved is not True:raise PermissionError('explicit existing-agent usage approval required')
    if not isinstance(request,RunRequest):raise ValueError('explicit validated request required')
    if request.as_of.astimezone(timezone.utc).isoformat()!='2024-04-04T23:59:59+00:00':
        raise ValueError('project historical cutoff required')
    remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
    if (not 0<remaining<=480 or not 1<=request.max_model_calls<=24 or
        not 1<=request.max_search_calls<=12 or request.concurrency!=1 or
        not 1<=request.max_research_passes<=2):raise ValueError('bounded discovery request required')
    if type(max_specialists) is not int or not 1<=max_specialists<=2:
        raise ValueError('max_specialists must be 1..2')
    if type(publisher_max_body_bytes) is not int or not 128<=publisher_max_body_bytes<=1048576:
        raise ValueError('publisher body bound must be 128..1048576 bytes')
    if type(verify_packages) is not bool:raise ValueError('explicit package-verification boolean required')
    if verify_packages and not callable(getattr(registry_http_client,'get',None)):
        raise ValueError('explicit registry HTTP client required for package verification')
    if not verify_packages and registry_http_client is not None:
        raise ValueError('registry client requires explicit package-verification opt-in')
    if type(verify_publishers) is not bool:raise ValueError('explicit publisher-verification boolean required')
    if type(preliminary_screen) is not bool:raise ValueError('explicit preliminary-screen boolean required')
    if type(check_argument_support) is not bool:raise ValueError('explicit support boolean required')
    if type(max_sources) is not int or not 1<=max_sources<=3:raise ValueError('max_sources must be 1..3')
    if not callable(backend_factory) or not callable(discovery_factory) or not callable(getattr(http_client,'get',None)):
        raise ValueError('explicit backend, discovery and HTTP implementations required')
    anchors=dict(domain_anchors) if domain_anchors is not None else {request.company.company_id:request.company.domain}
    for subject,domain in anchors.items():CompanySeed(subject,subject,domain)
    if anchors.get(request.company.company_id)!=request.company.domain:
        raise ValueError('run company anchor must match seed')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        (root/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    code_names=('discovery_runner.py','discovered_research.py','web_discovery.py','archive_transport.py',
        'ragas_faithfulness.py','evidence_checked_committee.py','native_committee.py','model_lead.py',
        'archive_process.py','archive_worker.py','agent_prompts.py','cli_backend.py','cli_limits.py','thesis_synthesis.py','evidence_gap_triage.py','archived_publisher.py','runtime.py','guards.py','contracts.py','native_support.py','model_identity.py',
        'progressive_committee.py','single_analyst.py','discovered_package.py','package_registry.py','package_source.py','npm_source.py','npm_names.py','registry_process.py','registry_worker.py')
    plan=dict(company=asdict(request.company),mandate=request.mandate,as_of=request.as_of.isoformat(),
        model=request.model_version,source_policy=request.source_policy,prompt_version=request.prompt_version,
        prompt_bundle_sha256=prompt_fingerprint(),
        component_sha256={name:digest(Path(__file__).with_name(name).read_text(encoding='utf-8')) for name in code_names},
        domain_anchors=anchors,deadline=request.deadline.isoformat(),max_model_calls=request.max_model_calls,
        max_search_reservations=request.max_search_calls,max_research_passes=request.max_research_passes,
        max_sources=max_sources,argument_support_check_enabled=check_argument_support,
        publisher_verification_enabled=verify_publishers,package_verification_enabled=verify_packages,max_specialists=max_specialists,
        publisher_max_body_bytes=publisher_max_body_bytes,
        preliminary_screen_enabled=preliminary_screen,
        analysis_strategy='baseline_first' if preliminary_screen else 'full_committee',
        resource_units='Search=managed discovery invocation OR direct archive/registry HTTP attempt; model=outer dispatch reservation. Managed internal HTTP/inferences UNKNOWN.',
        historical_domain_ownership_independently_proven=False,Y_read=False,training=False)
    plan['fingerprint']=digest(json.dumps(plan,sort_keys=True));save('plan.json',plan)
    budget=CallBudget(request);gateway=TemporalGateway(request,[])
    class RecordingHTTP:
        def __init__(self,client,prefix):self.count=0;self.client=client;self.prefix=prefix
        def get(self,url,timeout,max_bytes,check_deadline=lambda:None):
            self.count+=1
            name=f'{self.prefix}_http_{self.count:03d}'
            attempt=dict(status='DISPATCHING',url=url,timeout_seconds=timeout,max_bytes=max_bytes)
            save(name+'.attempt.json',attempt)
            try:
                response=self.client.get(url,timeout,max_bytes,check_deadline=check_deadline)
                if len(response.body)>max_bytes:raise ValueError('oversized HTTP response')
            except Exception as exc:
                attempt.update(status='FAILED',error_type=type(exc).__name__)
                try:save(name+'.attempt.json',attempt)
                except OSError:pass  # Keep original exception and prior dispatch intent.
                raise
            attempt.update(status='COMPLETED',http_status=response.status)
            save(name+'.attempt.json',attempt)
            (root/(name+'.body')).write_bytes(response.body)
            save(name+'.json',dict(url=response.url,status=response.status,headers=response.headers,
                body_sha256=hashlib.sha256(response.body).hexdigest()))
            return response
    recording=RecordingHTTP(http_client,'archive')
    registry_recording=RecordingHTTP(registry_http_client,'registry') if verify_packages else None
    archive=ArchivedWebsiteProvider(request,gateway,budget,client=recording,domain_anchors=anchors,
                                    max_requests=request.max_search_calls)
    publisher=ArchivedPublisherVerifier(request,gateway,budget,client=recording,domain_anchors=anchors,
        max_requests=request.max_search_calls,max_body_bytes=publisher_max_body_bytes) if verify_publishers else None
    agents=[];backend=None;provider=None;proposal=None;committee=None;package=None
    try:
        backend=backend_factory(budget,root)
        if getattr(backend,'call_budget',budget) is not budget:raise ValueError('backend budget mismatch')
        def factory(task):
            agent=discovery_factory(task,budget,root);agents.append(agent);return agent
        if verify_packages:
            package=DiscoveredPackageVerifier(request,gateway,budget,registry_recording,root/'registry_verification')
        provider=DiscoveredResearchProvider(request,gateway,budget,factory,archive,max_sources=max_sources,publisher_verifier=publisher,package_verifier=package)
        committee=NativeDialecticCommittee(backend,budget,NativeConfig(selection_policy='balanced_per_side'))
        if check_argument_support:
            from .evidence_checked_committee import EvidenceCheckedCommittee
            from .ragas_faithfulness import RagasFaithfulnessChecker
            from .evidence_gap_triage import EvidenceGapTriage
            committee=EvidenceCheckedCommittee(committee,RagasFaithfulnessChecker(backend,budget),budget,
                gap_triage=EvidenceGapTriage(backend,budget))
        if preliminary_screen is True:
            committee=ProgressiveCommittee(SingleAnalystBaseline(backend,budget),committee,budget)
        runtime=ClosedLoopRuntime(request,gateway,budget,ModelLead(backend,budget,max_specialists=max_specialists),committee,provider,
                                  thesis=ThesisSynthesizer(backend,budget))
        proposal=runtime.run();save('proposal.json',proposal)
        packet={key:proposal[key] for key in ('decision','rationale','admitted_fact_ids','essential_gaps','thesis')}
        acceptance=gate_analysis(packet,plan['fingerprint'])
        result=dict(proposal)
        result.update(status='DISCOVERY_RUNTIME_EXECUTED' if proposal['stop_reason'] in _NORMAL_STOPS else 'DISCOVERY_RUNTIME_STOPPED',
                      proposed_decision=proposal['decision'],decision=acceptance['decision'],acceptance=acceptance)
        if proposal['decision'] in ('INVEST','PASS') and acceptance['decision']=='MORE_DILIGENCE':
            result.update(proposed_thesis=proposal['thesis'],thesis=None,proposed_rationale=proposal['rationale'],
                rationale='Final source-bound analysis review is pending.',
                essential_gaps=list(dict.fromkeys([*proposal['essential_gaps'],'final_analysis_review'])))
    except BudgetStopped as exc:
        budget.stop(str(exc))
        result=dict(status='DISCOVERY_RUNTIME_STOPPED',decision='MORE_DILIGENCE',stop_reason=budget.stop_reason)
    except Exception as exc:
        budget.stop('DISCOVERY_RUN_FAILED')
        result=dict(status='DISCOVERY_RUNTIME_FAILED',decision='MORE_DILIGENCE',
                    stop_reason=budget.stop_reason,error_type=type(exc).__name__)
    result.update(logical_call_budget=budget.snapshot(),direct_archive_http_attempts=recording.count,
        direct_registry_http_attempts=registry_recording.count if registry_recording else 0,
        direct_source_http_attempts=recording.count+(registry_recording.count if registry_recording else 0),
        managed_discovery_process_attempts=(sum(a.process_count for a in agents)
            if all(type(getattr(a,'process_count',None)) is int for a in agents) else None),
        backend_process_attempts=getattr(backend,'process_count',None),managed_internal_http='UNKNOWN',
        internal_inference_requests='UNKNOWN',invoice='UNKNOWN',Y_changed=False,training_run=False,
        semantic_support_certified=False,predictive_accuracy_evaluated=False)
    save('committee_trace.json',list(getattr(committee,'last_trace',())))
    save('model_calls.json',list(getattr(committee,'last_calls',())))
    result['committee_trace_file']='committee_trace.json'
    save('provider_trace.json',provider.trace if provider else [])
    save('archive_receipts.json',archive.receipts);save('archive_attempts.json',archive.attempts)
    save('publisher_receipts.json',publisher.receipts if publisher else [])
    save('publisher_attempts.json',publisher.attempts if publisher else [])
    save('registry_receipts.json',package.receipts if package else [])
    save('registry_trace.json',package.trace if package else [])
    save('result.json',result)
    return result
