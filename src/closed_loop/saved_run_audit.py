"""Offline consistency audit over one saved discovery-run artifact directory.

This only checks that plan.json/result.json/proposal.json/committee_trace.json
are internally and mutually consistent with each other (hashes, declared call
caps/usage, decision plumbing, fact-id plumbing, citation bounds). It never
re-derives, fetches, or judges source authenticity, semantic truth, model
accuracy, or archived-identity validity, and it never mutates or writes inside
the run directory. Missing/malformed inputs become findings, never raised
exceptions or leaked raw text.
"""
import argparse
import hashlib
import json
from pathlib import Path

CONSISTENT = 'CONSISTENT_ARTIFACTS_NOT_SEMANTIC_CERTIFICATION'
INCONSISTENT = 'INCONSISTENT_ARTIFACTS'

_MAX_BYTES = 4 * 1024 * 1024
_FIXED_NAMES = ('plan.json', 'result.json', 'proposal.json', 'committee_trace.json')
_REQUIRED = ('plan.json', 'result.json')
_DECISIONS = ('INVEST', 'PASS', 'MORE_DILIGENCE')
_PROHIBITED_TRUE_FLAGS = ('Y_changed', 'training_run', 'predictive_accuracy_evaluated', 'semantic_support_certified')


def _is_strict_nonneg_int(value):
    return type(value) is int and value >= 0


def _reject_constant(_text):
    raise ValueError('NON_FINITE_NUMBER')


def _dedup_object_pairs(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError('DUPLICATE_KEY')
        seen[key] = value
    return seen


def _strict_json_loads(raw_bytes):
    text = raw_bytes.decode('utf-8')
    return json.loads(text, object_pairs_hook=_dedup_object_pairs, parse_constant=_reject_constant)


def _read_fixed_file(root, name, findings):
    """Bounded, read-only load of one fixed filename directly under root."""
    path = root / name
    try:
        if not path.is_file():
            return None, None
        if path.resolve().parent != root:
            findings.append({'code':'INPUT_OUTSIDE_RUN','file':name})
            return None,None
        if path.stat().st_size > _MAX_BYTES:
            findings.append({'code': 'OVERSIZED_FILE', 'file': name})
            return None, None
        with path.open('rb') as stream:
            raw = stream.read(_MAX_BYTES+1)
    except OSError:
        findings.append({'code': 'UNREADABLE_FILE', 'file': name})
        return None, None
    if len(raw) > _MAX_BYTES:
        findings.append({'code': 'OVERSIZED_FILE', 'file': name})
        return None, None
    sha256 = hashlib.sha256(raw).hexdigest()
    try:
        value = _strict_json_loads(raw)
    except (ValueError, UnicodeDecodeError):
        findings.append({'code': 'MALFORMED_JSON', 'file': name})
        return None, sha256
    return value, sha256


def _check_plan_fingerprint(plan, findings):
    if not isinstance(plan, dict):
        findings.append({'code': 'PLAN_NOT_OBJECT'})
        return
    fingerprint = plan.get('fingerprint')
    if not isinstance(fingerprint, str) or not fingerprint:
        findings.append({'code': 'PLAN_FINGERPRINT_MISSING'})
        return
    without = {k: v for k, v in plan.items() if k != 'fingerprint'}
    expected = hashlib.sha256(json.dumps(without, sort_keys=True).encode('utf-8')).hexdigest()
    if expected != fingerprint:
        findings.append({'code': 'PLAN_FINGERPRINT_MISMATCH'})


def _budget_snapshot(result):
    budget = result.get('logical_call_budget')
    return budget if isinstance(budget, dict) else None


def _check_caps(plan, result, findings):
    if not isinstance(plan, dict) or not isinstance(result, dict):
        return
    budget = _budget_snapshot(result)
    if budget is None:
        findings.append({'code': 'MISSING_LOGICAL_CALL_BUDGET'})
        return
    caps = budget.get('caps')
    used = budget.get('used')
    active = budget.get('active')
    if not isinstance(caps, dict) or not isinstance(used, dict):
        findings.append({'code': 'MALFORMED_LOGICAL_CALL_BUDGET'})
        return
    plan_model_cap = plan.get('max_model_calls')
    plan_search_cap = plan.get('max_search_reservations')
    if not _is_strict_nonneg_int(plan_model_cap) or not _is_strict_nonneg_int(caps.get('model')) or caps.get('model') != plan_model_cap:
        findings.append({'code': 'MODEL_CAP_MISMATCH'})
    if not _is_strict_nonneg_int(plan_search_cap) or not _is_strict_nonneg_int(caps.get('search')) or caps.get('search') != plan_search_cap:
        findings.append({'code': 'SEARCH_CAP_MISMATCH'})
    used_model = used.get('model')
    used_search = used.get('search')
    if not _is_strict_nonneg_int(used_model):
        findings.append({'code': 'USED_MODEL_NOT_NONNEGATIVE_INT'})
        used_model = None
    if not _is_strict_nonneg_int(used_search):
        findings.append({'code': 'USED_SEARCH_NOT_NONNEGATIVE_INT'})
        used_search = None
    if used_model is not None and _is_strict_nonneg_int(caps.get('model')) and used_model > caps['model']:
        findings.append({'code': 'USED_MODEL_EXCEEDS_CAP'})
    if used_search is not None and _is_strict_nonneg_int(caps.get('search')) and used_search > caps['search']:
        findings.append({'code': 'USED_SEARCH_EXCEEDS_CAP'})
    if type(active) is not int or active != 0:
        findings.append({'code': 'ACTIVE_RESERVATION_NOT_ZERO'})
    _check_observed_processes(result, used_model, used_search, findings)


def _nonneg_int_or_none(value):
    return value if _is_strict_nonneg_int(value) else None


def _check_observed_processes(result, used_model, used_search, findings):
    for key in ('backend_process_attempts','managed_discovery_process_attempts','direct_archive_http_attempts'):
        if result.get(key) is not None and not _is_strict_nonneg_int(result[key]):
            findings.append({'code':'INVALID_OBSERVED_COUNT','field':key})
    backend = _nonneg_int_or_none(result.get('backend_process_attempts'))
    managed = _nonneg_int_or_none(result.get('managed_discovery_process_attempts'))
    direct = _nonneg_int_or_none(result.get('direct_archive_http_attempts'))
    if backend is not None and managed is not None and used_model is not None:
        if backend + managed > used_model:
            findings.append({'code': 'OBSERVED_MODEL_PROCESSES_EXCEED_USED'})
    if direct is not None and managed is not None and used_search is not None:
        if direct + managed > used_search:
            findings.append({'code': 'OBSERVED_SEARCH_PROCESSES_EXCEED_USED'})


def _check_prohibited_flags(result, findings):
    if not isinstance(result, dict):
        return
    for key in _PROHIBITED_TRUE_FLAGS:
        if result.get(key) is not False:
            findings.append({'code': 'PROHIBITED_FLAG_TRUE', 'field': key})


def _check_acceptance(result, findings):
    if not isinstance(result, dict):
        return
    status = result.get('status')
    if status not in ('DISCOVERY_RUNTIME_EXECUTED','DISCOVERY_RUNTIME_STOPPED','DISCOVERY_RUNTIME_FAILED'):
        findings.append({'code':'INVALID_RUN_STATUS'})
    decision = result.get('decision')
    if decision not in _DECISIONS:
        findings.append({'code':'INVALID_DECISION'})
    if status in ('DISCOVERY_RUNTIME_STOPPED','DISCOVERY_RUNTIME_FAILED') and (decision!='MORE_DILIGENCE' or result.get('thesis') is not None):
        findings.append({'code':'TERMINAL_FAILURE_SUBSTANTIVE_RESULT'})
    if not isinstance(result.get('stop_reason'),str) or not result['stop_reason'].strip():
        findings.append({'code':'MISSING_STOP_REASON'})
    acceptance = result.get('acceptance')
    if acceptance is not None:
        if not isinstance(acceptance, dict) or acceptance.get('decision') != decision:
            findings.append({'code': 'ACCEPTANCE_DECISION_MISMATCH'})
        return
    if decision != 'MORE_DILIGENCE':
        findings.append({'code': 'MISSING_ACCEPTANCE_FOR_SUBSTANTIVE_DECISION'})
        return
    if status not in ('DISCOVERY_RUNTIME_STOPPED', 'DISCOVERY_RUNTIME_FAILED'):
        findings.append({'code': 'MISSING_ACCEPTANCE_FOR_EXECUTED'})


def _check_executed_against_proposal(result, proposal, findings):
    if not isinstance(result, dict) or result.get('status') != 'DISCOVERY_RUNTIME_EXECUTED':
        return
    if not isinstance(proposal, dict):
        findings.append({'code': 'MISSING_PROPOSAL_FOR_EXECUTED'})
        return
    if not isinstance(result.get('admitted_fact_ids'),list):
        findings.append({'code':'MISSING_EXECUTED_FACT_LIST'})
    if proposal.get('decision') in ('INVEST','PASS') and not proposal.get('admitted_fact_ids'):
        findings.append({'code':'UNSUPPORTED_SUBSTANTIVE_PROPOSAL'})
    if proposal.get('stop_reason') != result.get('stop_reason'):
        findings.append({'code': 'STOP_REASON_MISMATCH'})
    if proposal.get('admitted_fact_ids') != result.get('admitted_fact_ids'):
        findings.append({'code': 'ADMITTED_FACT_IDS_MISMATCH'})
    if proposal.get('decision') != result.get('proposed_decision'):
        findings.append({'code': 'PROPOSED_DECISION_MISMATCH'})


def _check_zero_facts_not_substantive(result, findings):
    if not isinstance(result, dict):
        return
    admitted = result.get('admitted_fact_ids')
    if admitted is not None and (not isinstance(admitted,list) or not all(isinstance(x,str) and x for x in admitted) or len(admitted)!=len(set(admitted))):
        findings.append({'code':'INVALID_ADMITTED_FACT_IDS'})
    if result.get('decision') in ('INVEST','PASS') and not admitted:
        findings.append({'code':'SUBSTANTIVE_WITHOUT_FACTS'})
    if isinstance(admitted, list) and len(admitted) == 0:
        if result.get('decision') in ('INVEST', 'PASS'):
            findings.append({'code': 'ZERO_FACTS_SUBSTANTIVE_DECISION'})
        if result.get('thesis') is not None:
            findings.append({'code': 'ZERO_FACTS_SUBSTANTIVE_THESIS'})


def _check_committee_trace(committee_trace, findings):
    if committee_trace is None:
        return
    if not isinstance(committee_trace, list):
        findings.append({'code': 'MALFORMED_COMMITTEE_TRACE'})
        return
    for stage_index, entry in enumerate(committee_trace):
        if not isinstance(entry, dict):
            findings.append({'code':'MALFORMED_COMMITTEE_TRACE_ENTRY','stage_index':stage_index})
            continue
        arguments = entry.get('arguments')
        qa_fact_ids = entry.get('qa_fact_ids')
        if arguments is None:
            continue
        if not isinstance(arguments, list) or not isinstance(qa_fact_ids, list) or not all(isinstance(x, str) for x in qa_fact_ids):
            findings.append({'code': 'MALFORMED_COMMITTEE_TRACE_ENTRY', 'stage_index': stage_index})
            continue
        stage_fact_ids = set(qa_fact_ids)
        for argument_index, argument in enumerate(arguments):
            if not isinstance(argument, dict):
                findings.append({'code': 'MALFORMED_COMMITTEE_TRACE_ENTRY', 'stage_index': stage_index, 'argument_index': argument_index})
                continue
            cited = argument.get('cited_fact_ids')
            if not isinstance(cited, list) or not all(isinstance(x, str) for x in cited):
                findings.append({'code': 'MALFORMED_COMMITTEE_TRACE_ENTRY', 'stage_index': stage_index, 'argument_index': argument_index})
                continue
            if not set(cited).issubset(stage_fact_ids):
                findings.append({'code': 'CITATION_NOT_SUBSET_OF_STAGE_FACTS', 'stage_index': stage_index, 'argument_index': argument_index})


def audit_run(run_dir):
    """Read-only artifact-consistency audit; never certifies truth/accuracy."""
    findings = []
    try:
        root = Path(run_dir)
        if not root.is_dir():
            return {'status': INCONSISTENT, 'findings': [{'code': 'RUN_DIR_NOT_FOUND'}], 'input_sha256': {}}
        root = root.resolve(strict=True)
        values = {}
        hashes = {}
        for name in _FIXED_NAMES:
            value, sha256 = _read_fixed_file(root, name, findings)
            values[name] = value
            hashes[name] = sha256
        for name in _REQUIRED:
            if hashes[name] is None:
                findings.append({'code': 'MISSING_REQUIRED_FILE', 'file': name})
        if not isinstance(values['result.json'],dict):
            findings.append({'code':'RESULT_NOT_OBJECT'})
        if not isinstance(values['plan.json'],dict):
            findings.append({'code':'PLAN_NOT_OBJECT'})
        plan = values['plan.json']
        result = values['result.json']
        proposal = values['proposal.json']
        committee_trace = values['committee_trace.json']
        if plan is not None:
            _check_plan_fingerprint(plan, findings)
        if plan is not None and result is not None:
            _check_caps(plan, result, findings)
        if isinstance(result,dict):
            if result.get('status')=='DISCOVERY_RUNTIME_EXECUTED' and not isinstance(committee_trace,list):
                findings.append({'code':'MISSING_COMMITTEE_TRACE_FOR_EXECUTED'})
            _check_prohibited_flags(result, findings)
            _check_acceptance(result, findings)
            _check_executed_against_proposal(result, proposal, findings)
            _check_zero_facts_not_substantive(result, findings)
        _check_committee_trace(committee_trace, findings)
        status = INCONSISTENT if findings else CONSISTENT
        return {
            'status': status,
            'findings': findings,
            'input_sha256': {name: sha for name, sha in hashes.items() if sha is not None},
        }
    except Exception as exc:
        return {
            'status': INCONSISTENT,
            'findings': [{'code': 'AUDIT_INTERNAL_ERROR', 'error_type': type(exc).__name__}],
            'input_sha256': {},
        }


def _parse_args(argv):
    parser = argparse.ArgumentParser(description='Offline saved discovery-run artifact consistency audit.')
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--output', required=True)
    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)
    run_dir = Path(args.run_dir)
    output = Path(args.output)
    resolved_run_dir = run_dir.resolve()
    resolved_output = output.resolve()
    if resolved_output == resolved_run_dir or resolved_run_dir in resolved_output.parents:
        print(json.dumps({'status':'REFUSED_OUTPUT_INSIDE_RUN'}));return 2
    if output.exists():
        print(json.dumps({'status':'REFUSED_OUTPUT_EXISTS'}));return 2
    report = audit_run(run_dir)
    try:
        with output.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(report, indent=2, sort_keys=True) + '\n')
    except OSError:
        print(json.dumps({'status':'REFUSED_OUTPUT_WRITE'}));return 2
    print(json.dumps({'status':report['status'],'finding_count':len(report['findings'])}))
    return 0 if report['status'] == CONSISTENT else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
