"""Opt-in independent equal call/time allowances, not equal cost or quality gold.

No automatic execution, retrieval, retries, borrowed reservations or outcome reads.
Trusted backend factories must bind each newly allocated budget and enforce its
transport timeout. This is an orchestration boundary, not an OS sandbox.
"""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .agent_prompts import prompt_fingerprint
from .contracts import digest
from .guards import CallBudget, TemporalGateway, BudgetStopped
from .runtime import FactStore, committee_input
from .native_committee import NativeConfig
from .single_analyst import SINGLE_ANALYST_INSTRUCTION
from .analysis_acceptance import gate_analysis
from .paired_evaluation import (_VALID_ARM_ORDERS, _validate_source_items, _assess_arm)


def execute_equal_allowance_pair(*, request, source_items, output_dir, backend_factory,
        per_arm_calls, per_arm_seconds, approved=False,
        arm_order=('single_analyst','committee')):
    """Run both arms under reserved, nontransferable logical-call/time ceilings.

    A local exhaustion retains that arm and leaves the other allocation intact.
    Account-quota rejection, unsafe setup, and global deadline stop the pair.
    Equal actual token usage, dollars, inner inference count and exact model
    weights are NOT verified by this API. No substantive quality claim follows.
    """
    if approved is not True:
        raise PermissionError('explicit equal-allowance execution approval required')
    if (type(arm_order) is not tuple or not all(type(a) is str for a in arm_order)
            or arm_order not in _VALID_ARM_ORDERS):
        raise ValueError('exact two-arm order required')
    if type(per_arm_calls) is not int or not 1<=per_arm_calls<=12:
        raise ValueError('per_arm_calls must be an integer in 1..12')
    if type(per_arm_seconds) is not int or not 1<=per_arm_seconds<=180:
        raise ValueError('per_arm_seconds must be an integer in 1..180')
    now=datetime.now(timezone.utc)
    remaining=(request.deadline-now).total_seconds()
    if (not 2*per_arm_seconds+5<=remaining<=480 or
            request.max_model_calls!=2*per_arm_calls or request.max_search_calls!=0 or
            request.concurrency!=1 or not callable(backend_factory)):
        raise ValueError('explicit bounded two-arm reservations and setup margin required')
    _validate_source_items(source_items)
    gateway=TemporalGateway(request,[record for _,record in source_items])
    facts=[]
    for candidate,_ in source_items:
        fact,error=gateway.admit(candidate)
        if error or fact is None:
            raise ValueError('verified source preflight failed')
        facts.append(fact)
    if len({f.fact_id for f in facts})!=len(facts):
        raise ValueError('duplicate admitted fact IDs rejected')
    store=FactStore();store.merge(facts)
    view=committee_input(request,store,1)
    evidence_sha=digest(json.dumps(list(view.qa_pairs),sort_keys=True))
    root=Path(output_dir);root.mkdir(parents=True,exist_ok=False)
    fairness=dict(equal_per_arm_logical_call_ceiling=True,
        equal_requested_arm_duration=True,unused_allowance_transfer=False,
        equal_actual_tokens=False,equal_actual_cost=False,
        physical_cli_ceiling_enforced_by='explicit trusted backend factory',
        shared_model_version_string=True,equal_per_arm_cli_process_ceiling=True,
        model_weights_independently_verified=False,
        order_randomized=False)
    plan=dict(mode='EQUAL_ALLOWANCE_FIXED_EVIDENCE_NOT_QUALITY_VALIDATION',
        company=asdict(request.company),mandate=request.mandate,
        as_of=request.as_of.isoformat(),model=request.model_version,
        evidence_sha256=evidence_sha,prompt_bundle_sha256=prompt_fingerprint(),
        baseline_instruction_sha256=digest(SINGLE_ANALYST_INSTRUCTION),
        source_policy=request.source_policy,prompt_version=request.prompt_version,
        native_config=asdict(NativeConfig(selection_policy='balanced_per_side')),source_proofs=[dict(source_id=f.source_id,
            content_sha256=f.content_sha256,proof_kind=f.proof_kind,
            availability_upper_bound=f.availability_upper_bound.isoformat()) for f in facts],
        arm_order=list(arm_order),per_arm_calls=per_arm_calls,
        per_arm_seconds=per_arm_seconds,max_total_model_calls=request.max_model_calls,
        global_deadline=request.deadline.isoformat(),fairness=fairness,
        source_retrieval_http_allowed=0,Y_read=False,training_run=False,
        independent_human_gold=False,predictive_accuracy_evaluated=False)
    plan['fingerprint']=digest(json.dumps(plan,sort_keys=True))
    (root/'plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
    results=[];global_stop=None;seen_backends=[]
    def save():
        value=dict(status='EQUAL_ALLOWANCE_EXECUTION_RECORDED_NOT_A_QUALITY_RESULT',
            plan_fingerprint=plan['fingerprint'],arms=results,
            model_reservations=sum(x.get('model_reservations',0) for x in results),
            max_total_model_calls=request.max_model_calls,
            fairness=fairness,global_stop_reason=global_stop,
            actual_source_http_requests=0,managed_network_requests='UNKNOWN',
            actual_tokens='UNKNOWN',invoice='UNKNOWN',Y_changed=False,
            training_run=False,semantic_support_certified=False,
            predictive_accuracy_evaluated=False)
        # Persist each arm before moving on; do not silently discard failures.
        temp=root/'result.json.tmp';temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        temp.replace(root/'result.json')
        return value
    config=NativeConfig(selection_policy='balanced_per_side')
    for arm in arm_order:
        start=time.monotonic();stamp=datetime.now(timezone.utc)
        if global_stop or (request.deadline-stamp).total_seconds()<per_arm_seconds:
            global_stop=global_stop or 'GLOBAL_TIME_ALLOWANCE_UNAVAILABLE'
            results.append(dict(arm=arm,status='NOT_RUN_GLOBAL_STOP',reason=global_stop,
                model_reservations=0,evidence_sha256=evidence_sha))
            save();continue
        # Includes factory setup time. No post-setup extension or budget reset.
        arm_req=replace(request,max_model_calls=per_arm_calls,
            deadline=stamp+timedelta(seconds=per_arm_seconds))
        budget=CallBudget(arm_req);backend=None
        arm_root=root/arm;arm_root.mkdir()
        try:
            backend=backend_factory(budget,arm_root)
            if getattr(backend,'call_budget',None) is not budget:
                raise ValueError('equal allowance backend must own exact arm budget')
            if any(backend is previous for previous in seen_backends):
                raise ValueError('backend reuse across independent arms forbidden')
            seen_backends.append(backend)
            if getattr(backend,'model_id',None)!=request.model_version:
                raise ValueError('explicit backend model must match frozen request')
            cap=getattr(backend,'max_process_count',None)
            if type(cap) is not int or cap!=per_arm_calls:
                raise ValueError('explicit backend process ceiling must equal arm allowance')
        except Exception:
            budget.stop('EQUAL_ALLOWANCE_BACKEND_SETUP_FAILED')
            global_stop=budget.stop_reason
            entry=dict(arm=arm,status='SETUP_FAILED_NO_RETRY',reason=global_stop)
        else:
            try:
                budget.check()
                proposal,_=_assess_arm(arm,backend,budget,view,arm_req,store,
                    config,arm_root,[f.fact_id for f in facts])
                budget.check()
                entry=dict(arm=arm,status='EXECUTED_REVIEW_PENDING',proposal=proposal,
                    acceptance=gate_analysis(proposal,plan['fingerprint']+':'+arm))
            except BudgetStopped as exc:
                budget.stop(str(exc))
                entry=dict(arm=arm,status='STOPPED_NO_RETRY',reason=budget.stop_reason)
                if budget.stop_reason=='CLI_QUOTA_EXHAUSTED':global_stop=budget.stop_reason
            except Exception:
                budget.stop('EQUAL_ALLOWANCE_ARM_FAILED')
                entry=dict(arm=arm,status='FAILED_NO_RETRY',reason=budget.stop_reason)
                # Unknown transport/programming failures fail the pair closed.
                global_stop=budget.stop_reason
        entry.update(model_reservations=budget.used['model'],budget_snapshot=budget.snapshot(),
            evidence_sha256=evidence_sha,elapsed_seconds=round(time.monotonic()-start,3),
            arm_deadline=arm_req.deadline.isoformat(),
            cli_process_attempts=getattr(backend,'process_count',None),
            semantic_support_certified=False)
        results.append(entry);save()
    return save()
