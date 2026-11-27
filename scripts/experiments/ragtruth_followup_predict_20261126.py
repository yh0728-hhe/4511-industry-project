"""RAGTruth source-disjoint whole-response follow-up prediction: fixed 12-case arm.

Reuses whole_response_nli from whole_response_reference_predict_20261126.py via
importlib (that script is not edited or re-executed as __main__). Reuses the
same contracts/native-backend auth helpers as the prior arms. NEVER reads any
gold/label file; carries only a gold hash for a later, separate offline grader.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from closed_loop.contracts import CompanySeed, RunRequest
from closed_loop.runtime import CommitteeInput
from closed_loop.guards import CallBudget, BudgetStopped
from closed_loop.discovery_workflow import make_backend_factory
from closed_loop.package_workflow import (
    _forbidden_env_present,
    _resolve_executable,
    _verify_subscription_auth,
)

PROTOCOL_ID = 'RAGTRUTH-SOURCE-DISJOINT-12-20261126-001'
_RUN_CASE_COUNT = 12
_REQUIRED_RECORD_FIELDS = frozenset({'case_id', 'source_id', 'question', 'context', 'response'})
_MAX_CONTEXT_BYTES = 6000
_MAX_RESPONSE_BYTES = 1200
_MAX_QUESTION_BYTES = 1024
_EXCLUDED_SOURCE_COUNT = 6
_CLOSED_LOOP_DIR = Path(__file__).resolve().parents[2] / 'src/closed_loop'

_WHOLE_RESPONSE_PATH = Path(__file__).with_name('whole_response_reference_predict_20261126.py')
_spec = importlib.util.spec_from_file_location('whole_response_reference_predict_20261126', _WHOLE_RESPONSE_PATH)
_whole_response_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_whole_response_module)
whole_response_nli = _whole_response_module.whole_response_nli
_WHOLE_RESPONSE_SHA256 = hashlib.sha256(_WHOLE_RESPONSE_PATH.read_bytes()).hexdigest()


def load_protocol(protocol_path):
    """Read and sha256-verify the protocol file against its own 'script_sha256' entry."""
    protocol_path = Path(protocol_path)
    with protocol_path.open("rb") as stream:
        protocol_bytes = stream.read(100001)
    if len(protocol_bytes) > 100000:
        raise ValueError('PROTOCOL_TOO_LARGE')
    protocol = json.loads(protocol_bytes.decode('utf-8'))
    if not isinstance(protocol, dict):
        raise ValueError('PROTOCOL_OBJECT_REQUIRED')
    if protocol.get('protocol_id') != PROTOCOL_ID:
        raise ValueError('UNEXPECTED_PROTOCOL_ID')
    if protocol.get('max_model_cli_attempts') != _RUN_CASE_COUNT or type(protocol.get('max_model_cli_attempts')) is not int:
        raise ValueError('MAX_MODEL_CLI_ATTEMPTS_MUST_BE_TWELVE')
    if protocol.get('max_seconds') != 240 or type(protocol.get('max_seconds')) is not int:
        raise ValueError('MAX_SECONDS_MUST_BE_240')
    if not isinstance(protocol.get('model'), str) or not protocol['model'].strip():
        raise ValueError('EXPLICIT_MODEL_REQUIRED')
    stamp = datetime.fromisoformat(protocol['as_of'])
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError('AWARE_REFERENCE_TIME_REQUIRED')

    required_code = frozenset(name for name in os.listdir(_CLOSED_LOOP_DIR) if name.endswith('.py'))
    code = protocol.get('code_sha256')
    if not isinstance(code, dict) or set(code) != required_code:
        raise ValueError('COMPLETE_CURRENT_CODE_HASHES_REQUIRED')
    if any(not isinstance(name, str) or Path(name).name != name for name in code):
        raise ValueError('CODE_FILENAMES_REQUIRED')

    if protocol.get('whole_response_script_sha256') != _WHOLE_RESPONSE_SHA256:
        raise ValueError('WHOLE_RESPONSE_SCRIPT_HASH_MISMATCH')
    prior_path = Path(__file__).with_name('ragtruth_reference_predict_20261126.py')
    if protocol.get('prior_predictor_script_sha256') != hashlib.sha256(prior_path.read_bytes()).hexdigest():
        raise ValueError('TRANSITIVE_PREDICTOR_HASH_MISMATCH')
    script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if protocol.get('script_sha256') != script_sha256:
        raise ValueError('SCRIPT_HASH_MISMATCH')
    for name, expected in code.items():
        actual = hashlib.sha256((_CLOSED_LOOP_DIR / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('CODE_HASH_MISMATCH:' + name)

    excluded = protocol.get('excluded_source_ids')
    if (not isinstance(excluded, list) or len(excluded) != _EXCLUDED_SOURCE_COUNT
            or any(not isinstance(s, str) or not s.strip() for s in excluded)
            or len(set(excluded)) != _EXCLUDED_SOURCE_COUNT):
        raise ValueError('EXCLUDED_SOURCE_IDS_MUST_BE_SIX_UNIQUE_NONBLANK')

    return protocol, hashlib.sha256(protocol_bytes).hexdigest()


def parse_inputs(inputs_path, excluded_source_ids):
    """Strict twelve-record QA evidence file -> list of validated dict records.

    Raises ValueError on any schema, size, uniqueness, or source-overlap
    violation. Never accepts extra fields (including any labels/annotations
    field); never opens a gold/label path.
    """
    inputs_path = Path(inputs_path)
    with inputs_path.open("rb") as stream:
        inputs_bytes = stream.read(200001)
    if len(inputs_bytes) > 200000:
        raise ValueError('INPUT_FILE_TOO_LARGE')
    records = json.loads(inputs_bytes.decode('utf-8'))
    if not isinstance(records, list) or len(records) != _RUN_CASE_COUNT:
        raise ValueError('EXACTLY_TWELVE_RECORDS_REQUIRED')

    excluded = set(excluded_source_ids)
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
        if len(record['case_id']) > 256 or len(record['source_id']) > 256:
            raise ValueError('BOUNDED_CASE_IDENTIFIERS_REQUIRED')
        if record['case_id'] in case_ids:
            raise ValueError('DUPLICATE_CASE_ID')
        if record['source_id'] in source_ids:
            raise ValueError('DUPLICATE_SOURCE_ID')
        if record['source_id'] in excluded:
            raise ValueError('SOURCE_ID_NOT_DISJOINT_FROM_EXCLUDED_SET')
        case_ids.add(record['case_id'])
        source_ids.add(record['source_id'])

    return records, hashlib.sha256(inputs_bytes).hexdigest()


def run(inputs_path, protocol_path, output_dir, approved):
    if approved is not True:
        print('APPROVAL_REQUIRED: no auth, output, or model actions taken.')
        return 1

    protocol, protocol_sha256 = load_protocol(protocol_path)
    records, input_sha256 = parse_inputs(inputs_path, protocol['excluded_source_ids'])
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
        prompt_version='ragtruth-source-disjoint-predict-v1',
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
        arm='whole_response_source_disjoint12',
        protocol_id=protocol['protocol_id'],
        protocol_sha256=protocol_sha256,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        whole_response_script_sha256=_WHOLE_RESPONSE_SHA256,
        input_sha256=input_sha256,
        excluded_source_ids=list(protocol['excluded_source_ids']),
        case_ids=list(protocol['case_ids']),
        as_of=request.as_of.isoformat(),
        deadline=request.deadline.isoformat(),
        max_model_calls=request.max_model_calls,
        logical_call_budget_cap=dict(model=request.max_model_calls, search=request.max_search_calls),
    ))

    budget = CallBudget(request)
    backend = None

    completed = []
    failed = []
    not_run = []
    status = 'RAGTRUTH_SOURCE_DISJOINT12_PREDICT_EXECUTED'
    reason = None
    active_idx = None

    try:
        backend = make_backend_factory(request, exe)(budget, out)
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
            calls = []
            journal = {}
            d = None
            try:
                d, calls = whole_response_nli(backend, budget, view,
                    question=record['question'], response=record['response'], cited_fact_id=fact_id, journal=journal)
            finally:
                save('row_%02d_calls.json' % i, journal.get('calls', calls))
                if d is not None:
                    save('row_%02d_assessment.json' % i, d)
            prediction = int(d['score'])
            completed.append(dict(
                case_id=record['case_id'],
                score=d['score'],
                prediction=prediction,
                statement_count=1,
            ))
            save('completed_rows.json', completed)
            print('CASE %s: score=%s prediction=%s' % (record['case_id'], d['score'], prediction))
    except BudgetStopped as exc:
        budget.stop(str(exc))
        status = 'RAGTRUTH_SOURCE_DISJOINT12_PREDICT_STOPPED'
        reason = budget.stop_reason
        if active_idx is not None:
            failed.append(dict(case_id=records[active_idx]['case_id'], error='BudgetStopped'))
        not_run = [dict(case_id=r['case_id']) for r in records[(active_idx + 1) if active_idx is not None else 0:]]
    except Exception:
        budget.stop('RAGTRUTH_SOURCE_DISJOINT12_PREDICT_FAILED')
        status = 'RAGTRUTH_SOURCE_DISJOINT12_PREDICT_FAILED'
        reason = budget.stop_reason
        if active_idx is not None:
            failed.append(dict(case_id=records[active_idx]['case_id'], error='Exception'))
        not_run = [dict(case_id=r['case_id']) for r in records[(active_idx + 1) if active_idx is not None else 0:]]

    if backend is None and active_idx is None:
        not_run = [dict(case_id=r['case_id']) for r in records]

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
        whole_response_script_sha256=_WHOLE_RESPONSE_SHA256,
        model_cli_attempts=getattr(backend, 'process_count', 0 if backend is None else None),
        logical_call_budget=budget.snapshot(),
        arm='whole_response_source_disjoint12',
        excluded_source_ids=list(protocol['excluded_source_ids']),
        limitation=('Single whole-response NLI call per case; no atomic-statement decomposition '
            'or recall; not an official Ragas metric; no label/gold agreement is computed or claimed here; '
            'gold grading, if any, must run in a separate later process that never shares this process.'),
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
    parser = argparse.ArgumentParser(prog='ragtruth_followup_predict')
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
