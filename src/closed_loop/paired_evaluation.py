"""Fixed-evidence baseline/committee comparison, not an outcome backtest.

Both arms see the exact same gateway-admitted QA rows, use one backend/budget,
and retain failures. No retrieval, Y access, implicit client or model fallback.
"""
from dataclasses import asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import time

from .agent_prompts import prompt_fingerprint
from .contracts import digest
from .guards import CallBudget,TemporalGateway,BudgetStopped,SourceCandidate,VerifiedRecord
from .package_source import verify_wheel_source
from .npm_source import verify_npm_source
from .runtime import FactStore,committee_input,RunContext
from .native_committee import NativeDialecticCommittee,NativeConfig
from .single_analyst import SingleAnalystBaseline,SINGLE_ANALYST_INSTRUCTION
from .thesis_synthesis import ThesisSynthesizer
from .analysis_acceptance import gate_analysis


_VALID_ARM_ORDERS=(('single_analyst','committee'),('committee','single_analyst'))


def _validate_approval_order_and_bounds(approved,arm_order,request):
    if approved is not True:raise PermissionError('explicit paired execution approval required')
    if type(arm_order) is not tuple or not all(type(arm) is str for arm in arm_order) or arm_order not in _VALID_ARM_ORDERS:
        raise ValueError('arm_order must be an exact two-name permutation of single_analyst/committee')
    remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
    if (not 0<remaining<=480 or not 1<=request.max_model_calls<=24 or
        request.max_search_calls!=0 or request.concurrency!=1):raise ValueError('bounded paired run required')


def _validate_source_items(source_items):
    if type(source_items) is not tuple or not (1<=len(source_items)<=8):
        raise ValueError('source_items must be a 1..8 length tuple of trusted verified records')
    for item in source_items:
        if (type(item) is not tuple or len(item)!=2 or
                not isinstance(item[0],SourceCandidate) or not isinstance(item[1],VerifiedRecord)):
            raise ValueError('each source item must be an exact (SourceCandidate, VerifiedRecord) pair from a trusted internal verifier')
    return source_items


def execute_fixed_evidence_pair(*,request,artifact_bytes,file_metadata,expected_package,
        artifact_format,output_dir,backend_factory,approved=False,arm_order=('single_analyst','committee')):
    _validate_approval_order_and_bounds(approved,arm_order,request)
    if artifact_format not in ('wheel','npm') or not callable(backend_factory):raise ValueError('explicit source/backend required')
    budget=CallBudget(request);budget.check()
    verifier=verify_wheel_source if artifact_format=='wheel' else verify_npm_source
    candidate,record=verifier(artifact_bytes,file_metadata,expected_package,request)
    fact,error=TemporalGateway(request,[record]).admit(candidate)
    if error or fact is None:raise ValueError('paired source preflight failed')
    plan_extra=dict(source_id=fact.source_id,source_sha256=fact.content_sha256)
    return _run_pair_core(request=request,facts=(fact,),plan_extra=plan_extra,
        output_dir=output_dir,backend_factory=backend_factory,arm_order=arm_order,budget=budget)


def execute_verified_evidence_pair(*,request,source_items,output_dir,backend_factory,
        approved=False,arm_order=('single_analyst','committee')):
    _validate_approval_order_and_bounds(approved,arm_order,request)
    if not callable(backend_factory):raise ValueError('explicit backend required')
    _validate_source_items(source_items)
    budget=CallBudget(request);budget.check()
    gateway=TemporalGateway(request,[record for _,record in source_items])
    facts=[]
    for candidate,record in source_items:
        fact,error=gateway.admit(candidate)
        if error or fact is None:raise ValueError('verified source preflight failed')
        facts.append(fact)
    if len({fact.fact_id for fact in facts})!=len(facts):raise ValueError('duplicate admitted fact IDs rejected')
    source_proofs=[dict(source_id=fact.source_id,proof_kind=fact.proof_kind,
        availability_upper_bound=fact.availability_upper_bound.isoformat(),
        content_sha256=fact.content_sha256) for fact in facts]
    plan_extra=dict(source_proofs=source_proofs,trusted_verifier_input=True,
        assessment_scope='fixed_evidence_analysis_only_not_research')
    return _run_pair_core(request=request,facts=tuple(facts),plan_extra=plan_extra,
        output_dir=output_dir,backend_factory=backend_factory,arm_order=arm_order,budget=budget)


def _run_pair_core(*,request,facts,plan_extra,output_dir,backend_factory,arm_order,budget):
    store=FactStore();store.merge(list(facts));view=committee_input(request,store,1)
    config=NativeConfig(selection_policy='balanced_per_side')
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
    evidence_sha=digest(json.dumps(list(view.qa_pairs),sort_keys=True))
    admitted_fact_ids=[fact.fact_id for fact in store.facts]
    plan=dict(mode='FIXED_EVIDENCE_PAIR_NOT_AN_OUTCOME_BACKTEST',company=asdict(request.company),
        mandate=request.mandate,as_of=request.as_of.isoformat(),model=request.model_version,
        source_policy=request.source_policy,evidence_sha256=evidence_sha,
        prompt_bundle_sha256=prompt_fingerprint(),baseline_instruction_sha256=digest(SINGLE_ANALYST_INSTRUCTION),
        native_config=asdict(config),arm_order=list(arm_order),
        max_total_model_calls=request.max_model_calls,deadline=request.deadline.isoformat(),
        max_http_requests=0,http_budget_scope='source retrieval only; CLI transport network requests remain unknown',research_disabled=True,Y_read=False,predictive_accuracy_evaluated=False,
        independent_human_gold=False,semantic_support_certified=False,
        fairness=dict(shared_budget=True,equal_per_arm_allowance=False,equal_cost=False,
            randomized_order=False,note='order must be frozen by caller; changed order alone cannot establish superiority'),
        **plan_extra)
    plan['fingerprint']=digest(json.dumps(plan,sort_keys=True))
    (root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    try:
        budget.check()
        backend=backend_factory(budget,root)
        if getattr(backend,'call_budget',budget) is not budget:raise ValueError('paired backend budget mismatch')
    except Exception:
        budget.stop('PAIRED_BACKEND_SETUP_FAILED')
        cap=budget.caps['model'];used=budget.used['model']
        result=dict(status='PAIRED_BACKEND_SETUP_FAILED',arms=[dict(arm=arm,status='NOT_RUN_NO_BACKEND',
            remaining_model_reservations_before=cap-used,remaining_model_reservations_after=cap-used)
            for arm in plan['arm_order']],logical_call_budget=budget.snapshot(),actual_network_calls=None,actual_source_http_requests=0,managed_network_requests='UNKNOWN',
            Y_changed=False,training_run=False,semantic_support_certified=False,
            arm_order=list(arm_order),fairness=plan['fairness'],stop_reason=budget.stop_reason if budget.stopped else None)
        (root/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        return result
    results=[]
    for arm in plan['arm_order']:
        before=budget.used['model'];remaining_before=budget.caps['model']-before
        start=time.monotonic();committee=None
        try:
            budget.check()
            proposal,committee=_assess_arm(arm,backend,budget,view,request,store,config,root,admitted_fact_ids)
            acceptance=gate_analysis(proposal,plan['fingerprint']+':'+arm)
            entry=dict(arm=arm,status='EXECUTED_REVIEW_PENDING',proposal=proposal,acceptance=acceptance)
        except BudgetStopped as exc:
            budget.stop(str(exc));entry=dict(arm=arm,status='STOPPED_NO_RETRY',reason=budget.stop_reason)
        except Exception:
            budget.stop('PAIRED_ARM_FAILED');entry=dict(arm=arm,status='FAILED_NO_RETRY',reason=budget.stop_reason)
        if committee is not None:
            (root/'committee_draft_trace.json').write_text(json.dumps(committee.last_trace,indent=2)+'\n',encoding='utf-8')
        entry.update(evidence_sha256=evidence_sha,model_reservations=budget.used['model']-before,
            remaining_model_reservations_before=remaining_before,
            remaining_model_reservations_after=budget.caps['model']-budget.used['model'],
            budget_snapshot=budget.snapshot(),
            elapsed_seconds=round(time.monotonic()-start,3),semantic_support_certified=False)
        results.append(entry)
        (root/'arms.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    result=dict(status='PAIRED_EXECUTION_RECORDED_NOT_A_QUALITY_RESULT',plan_fingerprint=plan['fingerprint'],
        arms=results,logical_call_budget=budget.snapshot(),actual_network_calls=None,actual_source_http_requests=0,managed_network_requests='UNKNOWN',
        cli_process_attempts=getattr(backend,'process_count',None),invoice='UNKNOWN',inner_inference_count='UNKNOWN',
        Y_changed=False,training_run=False,predictive_accuracy_evaluated=False,semantic_support_certified=False,
        arm_order=list(arm_order),fairness=plan['fairness'],stop_reason=budget.stop_reason if budget.stopped else None)
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def _assess_arm(arm,backend,budget,view,request,store,config,root,admitted_fact_ids):
    """Shared assessment path; caller owns allocation and failure policy."""
    committee=None
    if arm=='single_analyst':
        raw=SingleAnalystBaseline(backend,budget).assess(view)
        (root/'single_analyst_raw.json').write_text(json.dumps(raw,indent=2)+'\n',encoding='utf-8')
        proposal={key:raw[key] for key in ('decision','rationale','essential_gaps','thesis','admitted_fact_ids')}
    else:
        committee=NativeDialecticCommittee(backend,budget,config)
        try:
            value=committee.evaluate(view)
            thesis=None
            if value.decision.value!='MORE_DILIGENCE' and not value.essential_gaps:
                thesis=asdict(ThesisSynthesizer(backend,budget).synthesize(request,RunContext(store=store,argument_revision=1),value))
            proposal=dict(decision=value.decision.value,rationale=value.rationale,
                essential_gaps=list(value.essential_gaps),thesis=thesis,admitted_fact_ids=list(admitted_fact_ids))
        finally:
            # Preserve partial trace even if evaluate fails before returning.
            (root/'committee_draft_trace.json').write_text(json.dumps(committee.last_trace,indent=2)+'\n',encoding='utf-8')
    return proposal,committee
