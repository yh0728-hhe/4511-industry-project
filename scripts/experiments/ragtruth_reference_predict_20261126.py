"""RAGTruth QA-support reference prediction harness: evidence-only faithfulness scoring.

Reuses the existing RagasFaithfulnessChecker, make_backend_factory, RunRequest/
CommitteeInput contracts and the local claude.ai CLI auth helpers exactly as in
package_workflow.py; no new model wrapper, framework, or dependency is added.

This script NEVER reads any gold/label file and NEVER computes reference
agreement. It only produces per-case predictions from the context+response
evidence supplied in --inputs. Protocol id RAGTRUTH-QA-SUPPORT-20261126-001 is
expected to be created by the operator before execution; this script only
verifies the hashes it names.
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from closed_loop.contracts import CompanySeed, RunRequest
from closed_loop.runtime import CommitteeInput
from closed_loop.guards import CallBudget, BudgetStopped
from closed_loop.ragas_faithfulness import RagasFaithfulnessChecker
from closed_loop.discovery_workflow import make_backend_factory
from closed_loop.package_workflow import (
    _forbidden_env_present,
    _resolve_executable,
    _verify_subscription_auth,
)

PROTOCOL_ID = 'RAGTRUTH-QA-SUPPORT-20261126-001'
_REQUIRED_RECORD_FIELDS = frozenset({'case_id', 'source_id', 'question', 'context', 'response'})
_MAX_CONTEXT_BYTES = 6000
_MAX_RESPONSE_BYTES = 1200
_MAX_QUESTION_BYTES = 1024
_RUN_CASE_COUNT = 6
_REQUIRED_CODE = frozenset({'ragas_faithfulness.py','native_support.py','agent_prompts.py',
    'model_identity.py','cli_backend.py','cli_limits.py','guards.py','contracts.py',
    'runtime.py','discovery_workflow.py','package_workflow.py'})


def load_protocol(protocol_path):
    """Read and sha256-verify the protocol file against its own 'script_sha256' entry."""
    protocol_path = Path(protocol_path)
    with protocol_path.open("rb") as stream:
        protocol_bytes = stream.read(65537)
    if len(protocol_bytes)>65536:raise ValueError('PROTOCOL_TOO_LARGE')
    protocol = json.loads(protocol_bytes.decode('utf-8'))
    if not isinstance(protocol,dict):raise ValueError('PROTOCOL_OBJECT_REQUIRED')
    if protocol.get('protocol_id') != PROTOCOL_ID:
        raise ValueError('UNEXPECTED_PROTOCOL_ID')
    for key,limit in [('max_model_cli_attempts',18),('max_seconds',360),('nli_batch_size',8)]:
        if type(protocol.get(key)) is not int or not 1<=protocol[key]<=limit:
            raise ValueError('BOUNDED_REFERENCE_PROTOCOL_REQUIRED')
    if not isinstance(protocol.get('model'),str) or not protocol['model'].strip():
        raise ValueError('EXPLICIT_MODEL_REQUIRED')
    stamp=datetime.fromisoformat(protocol['as_of'])
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError('AWARE_REFERENCE_TIME_REQUIRED')
    code=protocol.get('code_sha256')
    if not isinstance(code,dict) or not _REQUIRED_CODE<=set(code):raise ValueError('COMPLETE_CODE_HASHES_REQUIRED')
    if any(not isinstance(name,str) or Path(name).name!=name or not name.endswith('.py') for name in code):
        raise ValueError('CODE_FILENAMES_REQUIRED')
    script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if protocol.get('script_sha256') != script_sha256:
        raise ValueError('SCRIPT_HASH_MISMATCH')
    for name, expected in protocol['code_sha256'].items():
        actual = hashlib.sha256((Path('src/closed_loop') / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('CODE_HASH_MISMATCH:' + name)
    return protocol, hashlib.sha256(protocol_bytes).hexdigest()


def parse_inputs(inputs_path):
    """Strict six-record QA evidence file -> list of validated dict records.

    Raises ValueError on any schema, size, or uniqueness violation. Never
    accepts extra fields (including any labels/annotations field).
    """
    inputs_path = Path(inputs_path)
    with inputs_path.open("rb") as stream:
        inputs_bytes = stream.read(100001)
    if len(inputs_bytes)>100000:raise ValueError('INPUT_FILE_TOO_LARGE')
    records = json.loads(inputs_bytes.decode('utf-8'))
    if not isinstance(records, list) or len(records) != _RUN_CASE_COUNT:
        raise ValueError('EXACTLY_SIX_RECORDS_REQUIRED')

    case_ids = set()
    source_ids = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != _REQUIRED_RECORD_FIELDS:
            raise ValueError('EXACT_RECORD_FIELDS_REQUIRED')
        for key in _REQUIRED_RECORD_FIELDS:
            value = record[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError('NONBLANK_STRING_FIELD_REQUIRED:' + key)
        if len(record['context'].encode('utf-8')) > _MAX_CONTEXT_BYTES:
            raise ValueError('CONTEXT_TOO_LARGE')
        if len(record['response'].encode('utf-8')) > _MAX_RESPONSE_BYTES:
            raise ValueError('RESPONSE_TOO_LARGE')
        if len(record['question'].encode('utf-8')) > _MAX_QUESTION_BYTES:
            raise ValueError('QUESTION_TOO_LARGE')
        if len(record['case_id'])>256 or len(record['source_id'])>256:raise ValueError('BOUNDED_CASE_IDENTIFIERS_REQUIRED')
        if record['case_id'] in case_ids:
            raise ValueError('DUPLICATE_CASE_ID')
        if record['source_id'] in source_ids:
            raise ValueError('DUPLICATE_SOURCE_ID')
        case_ids.add(record['case_id'])
        source_ids.add(record['source_id'])

    return records, hashlib.sha256(inputs_bytes).hexdigest()


def run(inputs_path, protocol_path, output_dir, approved):
    if approved is not True:
        print('APPROVAL_REQUIRED: no auth, output, or model actions taken.')
        return 1

    protocol, protocol_sha256 = load_protocol(protocol_path)
    records, input_sha256 = parse_inputs(inputs_path)
    if input_sha256 != protocol['input_sha256']:
        raise ValueError('INPUT_HASH_MISMATCH')
    if [r['case_id'] for r in records] != list(protocol['case_ids']):
        raise ValueError('CASE_ID_ORDER_MISMATCH')

    out = Path(output_dir)
    if out.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')

    if _forbidden_env_present():
        print('REJECTED: direct API credential environment variables are not permitted.')
        return 1
    exe = _resolve_executable(None)
    if exe is None or not _verify_subscription_auth(exe):
        print('REJECTED: local claude.ai subscription login not verified.')
        return 1

    as_of = datetime.fromisoformat(protocol['as_of'])
    request = RunRequest(
        company=CompanySeed('external-ragtruth-reference', 'External RAG reference', 'github.com'),
        mandate='assess source-grounding only, no company/investment assessment',
        as_of=as_of,
        source_policy='external-reference-no-search-v1',
        model_version=protocol['model'],
        prompt_version='ragtruth-reference-predict-v1',
        deadline=datetime.now(timezone.utc) + timedelta(seconds=protocol['max_seconds']),
        max_model_calls=protocol['max_model_cli_attempts'],
        max_search_calls=0,
        concurrency=1,
        max_research_passes=1,
    )

    out.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        (out / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    save('plan.json', dict(
        protocol_id=protocol['protocol_id'],
        protocol_sha256=protocol_sha256,
        input_sha256=input_sha256,
        case_ids=list(protocol['case_ids']),
        as_of=request.as_of.isoformat(),
        deadline=request.deadline.isoformat(),
        max_model_calls=request.max_model_calls,
        logical_call_budget_cap=dict(model=request.max_model_calls, search=request.max_search_calls),
    ))

    budget = CallBudget(request)
    backend = None
    checker = None

    completed = []
    failed = []
    not_run = []
    status = 'RAGTRUTH_REFERENCE_PREDICT_EXECUTED'
    reason = None
    active_idx = None

    try:
        backend = make_backend_factory(request, exe)(budget, out)
        checker = RagasFaithfulnessChecker(backend, budget, max_statements_per_call=protocol['nli_batch_size'])
        for i, record in enumerate(records):
            active_idx = i
            fact_id = 'ragtruth-' + record['source_id']
            row = dict(
                answer=record['context'],
                fact_id=fact_id,
                source_id=record['source_id'],
                available_by=request.as_of.isoformat(),
                subject_id=request.company.company_id,
                reliability='EXTERNAL_REFERENCE_DATASET_INPUT',
            )
            view = CommitteeInput(
                company_id=request.company.company_id,
                mandate=request.mandate,
                as_of=request.as_of.isoformat(),
                fact_revision=0,
                argument_revision=i,
                qa_pairs=(row,),
            )
            try:
                d = checker.assess(view, question=record['question'], response=record['response'],
                    cited_fact_ids=[fact_id])
            finally:
                save('row_%02d_trace.json' % i, checker.last_trace)
                save('row_%02d_calls.json' % i, checker.last_calls)
            save('row_%02d_assessment.json' % i, d)
            prediction = 1 if d['score'] == 1 else 0
            completed.append(dict(
                case_id=record['case_id'],
                score=d['score'],
                prediction=prediction,
                statement_count=len(d['judgments']),
            ))
            save('completed_rows.json', completed)
            print('CASE %s: score=%s prediction=%s' % (record['case_id'], d['score'], prediction))
    except BudgetStopped as exc:
        budget.stop(str(exc))
        status = 'RAGTRUTH_REFERENCE_PREDICT_STOPPED'
        reason = budget.stop_reason
        if active_idx is not None:failed.append(dict(case_id=records[active_idx]['case_id'], error='BudgetStopped'))
        not_run = [dict(case_id=r['case_id']) for r in records[(active_idx+1) if active_idx is not None else 0:]]
    except Exception:
        budget.stop('RAGTRUTH_REFERENCE_PREDICT_FAILED')
        status = 'RAGTRUTH_REFERENCE_PREDICT_FAILED'
        reason = budget.stop_reason
        if active_idx is not None:failed.append(dict(case_id=records[active_idx]['case_id'], error='Exception'))
        not_run = [dict(case_id=r['case_id']) for r in records[(active_idx+1) if active_idx is not None else 0:]]

    all_complete = len(completed) == len(records) == _RUN_CASE_COUNT and not failed and not not_run

    result = dict(
        status=status,
        stop_reason=reason,
        last_case_index=active_idx,
        completed=completed,
        failed=failed,
        not_run=not_run,
        planned_rows=len(records),
        all_rows_completed=all_complete,
        case_ids=list(protocol['case_ids']),
        protocol_id=protocol['protocol_id'],
        protocol_sha256=protocol_sha256,
        input_sha256=input_sha256,
        model_cli_attempts=getattr(backend,'process_count',0 if backend is None else None),
        logical_call_budget=budget.snapshot(),
        aggregate_accuracy=None,
        company_quality_gold=False,
        training_run=False,
        Y_changed=False,
        actual_source_http_requests=0,
        managed_network_requests='UNKNOWN',
        invoice='UNKNOWN',
    )
    save('result.json', result)
    print(json.dumps(dict(status=status, completed=len(completed), failed=len(failed), not_run=len(not_run))))
    return 0 if all_complete else 2


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ragtruth_reference_predict')
    parser.add_argument('--inputs', required=True)
    parser.add_argument('--protocol', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--approve-cli', action='store_true')
    args = parser.parse_args(argv)

    if not args.approve_cli:
        print('APPROVAL_REQUIRED: no auth, output, or model actions taken.')
        return 1

    try:
        return run(args.inputs, args.protocol, args.output_dir, args.approve_cli)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        print('REJECTED: ' + type(exc).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
