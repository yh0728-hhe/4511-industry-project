"""RAGTruth whole-response single-NLI-call reference prediction: exploratory arm.

Distinct experimental arm from ragtruth_reference_predict_20261126.py: instead of
decomposing the response into statements and running one NLI call per batch of
statements, this script issues exactly ONE NLI call per record, treating the
entire response as a single statement. It reuses the same already-selected six
public reference cases, the same CommitteeInput/CallBudget/NativeBinding
contracts, the same local claude.ai CLI auth helpers, and the same literal
upstream Ragas NLI instruction text as ragas_faithfulness.py -- but it does NOT
call RagasFaithfulnessChecker and makes no production code changes.

This is not an official Ragas metric (Ragas faithfulness is defined over
decomposed atomic statements, not a whole response) and this script makes no
claim of atomic-statement recall or label/gold agreement. It NEVER reads any
gold/label file; only a gold hash field carried by a separate offline grader
may later be used to grade result.json.
"""
import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from closed_loop.contracts import CompanySeed, RunRequest, digest
from closed_loop.runtime import CommitteeInput
from closed_loop.guards import CallBudget, BudgetStopped
from closed_loop.native_support import NativeBinding, HumanMessage, get_llm
from closed_loop.ragas_faithfulness import (
    NLI_STATEMENT_INSTRUCTION,
    BINDING_INSTRUCTION,
    NLI_OUTPUT_BINDING,
    FaithfulnessVerdicts,
    StatementFaithfulnessVerdict,
)
from closed_loop.discovery_workflow import make_backend_factory
from closed_loop.package_workflow import (
    _forbidden_env_present,
    _resolve_executable,
    _verify_subscription_auth,
)

PROTOCOL_ID = 'RAGTRUTH-WHOLE-RESPONSE-20261126-001'
_RUN_CASE_COUNT = 6
_REQUIRED_CODE = frozenset({'ragas_faithfulness.py','native_support.py','agent_prompts.py',
    'model_identity.py','cli_backend.py','cli_limits.py','guards.py','contracts.py',
    'runtime.py','discovery_workflow.py','package_workflow.py'})

_PRIOR_PREDICTOR_PATH = Path(__file__).with_name('ragtruth_reference_predict_20261126.py')
_spec = importlib.util.spec_from_file_location('ragtruth_reference_predict_20261126', _PRIOR_PREDICTOR_PATH)
_prior_predictor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prior_predictor)
parse_inputs = _prior_predictor.parse_inputs
_PRIOR_PREDICTOR_SHA256 = hashlib.sha256(_PRIOR_PREDICTOR_PATH.read_bytes()).hexdigest()


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
    if type(protocol.get('max_model_cli_attempts')) is not int or protocol['max_model_cli_attempts'] != _RUN_CASE_COUNT:
        raise ValueError('MAX_MODEL_CLI_ATTEMPTS_MUST_BE_SIX')
    if type(protocol.get('max_seconds')) is not int or not 1<=protocol['max_seconds']<=240:
        raise ValueError('BOUNDED_REFERENCE_PROTOCOL_REQUIRED')
    if not isinstance(protocol.get('model'),str) or not protocol['model'].strip():
        raise ValueError('EXPLICIT_MODEL_REQUIRED')
    stamp=datetime.fromisoformat(protocol['as_of'])
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError('AWARE_REFERENCE_TIME_REQUIRED')
    code=protocol.get('code_sha256')
    if not isinstance(code,dict) or not _REQUIRED_CODE<=set(code):raise ValueError('COMPLETE_CODE_HASHES_REQUIRED')
    if any(not isinstance(name,str) or Path(name).name!=name or not name.endswith('.py') for name in code):
        raise ValueError('CODE_FILENAMES_REQUIRED')
    if protocol.get('prior_predictor_script_sha256') != _PRIOR_PREDICTOR_SHA256:
        raise ValueError('PRIOR_PREDICTOR_SCRIPT_HASH_MISMATCH')
    script_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if protocol.get('script_sha256') != script_sha256:
        raise ValueError('SCRIPT_HASH_MISMATCH')
    for name, expected in protocol['code_sha256'].items():
        actual = hashlib.sha256((Path('src/closed_loop') / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('CODE_HASH_MISMATCH:' + name)
    return protocol, hashlib.sha256(protocol_bytes).hexdigest()


def whole_response_nli(backend, budget, view, *, question, response, cited_fact_id, journal=None):
    """One NLI call treating the entire response as a single statement.

    Reuses the literal upstream NLI_STATEMENT_INSTRUCTION plus the local
    BINDING_INSTRUCTION/NLI_OUTPUT_BINDING text from ragas_faithfulness.py,
    with no decomposition stage. Returns a dict with a single judgment.
    """
    budget.check()
    cited_rows = tuple(row for row in view.qa_pairs if row['fact_id'] == cited_fact_id)
    if len(cited_rows) != 1:raise BudgetStopped('WHOLE_RESPONSE_UNAVAILABLE_CITATION')
    context_text = cited_rows[0]['answer']

    payload = dict(context=context_text, statements=[response])
    if question:payload['question'] = question

    binding = NativeBinding(backend, budget, view)
    calls = binding.calls
    if journal is not None:journal['calls'] = calls
    with binding.activate():
        verdicts_value = get_llm(temperature=0).with_structured_output(FaithfulnessVerdicts).invoke(
            [HumanMessage(NLI_STATEMENT_INSTRUCTION + '\n\n' + BINDING_INSTRUCTION + '\n' + NLI_OUTPUT_BINDING +
                '\n\nInput JSON: ' + json.dumps(payload, ensure_ascii=False))])

    judged = verdicts_value.statements
    if not isinstance(judged,list) or len(judged)!=1:raise BudgetStopped('WHOLE_RESPONSE_VERDICT_COUNT_MISMATCH')
    item = judged[0]
    if not isinstance(item,StatementFaithfulnessVerdict):raise BudgetStopped('WHOLE_RESPONSE_MALFORMED_VERDICT')
    if item.statement != response:raise BudgetStopped('WHOLE_RESPONSE_STATEMENT_NOT_EXACT_COPY')
    if type(item.verdict) is not int or item.verdict not in (0,1):raise BudgetStopped('WHOLE_RESPONSE_INVALID_VERDICT')
    if not isinstance(item.reason,str) or not item.reason.strip():raise BudgetStopped('WHOLE_RESPONSE_EMPTY_REASON')

    judgment = dict(statement=item.statement, reason=item.reason, verdict=item.verdict)
    binding_hashes = dict(response_sha256=digest(response), context_sha256=digest(context_text),
        question_sha256=digest(question or ''), citation_sha256=digest(cited_fact_id),
        source_rows_sha256=digest(json.dumps(cited_rows, sort_keys=True)),
        run_context_sha256=digest(json.dumps(dict(company_id=view.company_id,
            mandate=view.mandate, as_of=view.as_of), sort_keys=True)))

    return dict(arm='whole_response_single_nli', judgments=[judgment], score=float(item.verdict),
        binding=binding_hashes, logical_call_budget=budget.snapshot()), list(calls)


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
        prompt_version='ragtruth-whole-response-predict-v1',
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
        arm='whole_response_single_nli',
        protocol_id=protocol['protocol_id'],
        protocol_sha256=protocol_sha256,
        input_sha256=input_sha256,
        prior_predictor_script_sha256=_PRIOR_PREDICTOR_SHA256,
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
    status = 'RAGTRUTH_WHOLE_RESPONSE_PREDICT_EXECUTED'
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
                    question=record['question'], response=record['response'], cited_fact_id=fact_id,journal=journal)
            finally:
                save('row_%02d_calls.json' % i, journal.get('calls',calls))
                if d is not None:save('row_%02d_assessment.json' % i, d)
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
        status = 'RAGTRUTH_WHOLE_RESPONSE_PREDICT_STOPPED'
        reason = budget.stop_reason
        if active_idx is not None:failed.append(dict(case_id=records[active_idx]['case_id'], error='BudgetStopped'))
        not_run = [dict(case_id=r['case_id']) for r in records[(active_idx+1) if active_idx is not None else 0:]]
    except Exception:
        budget.stop('RAGTRUTH_WHOLE_RESPONSE_PREDICT_FAILED')
        status = 'RAGTRUTH_WHOLE_RESPONSE_PREDICT_FAILED'
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
        prior_predictor_script_sha256=_PRIOR_PREDICTOR_SHA256,
        model_cli_attempts=getattr(backend,'process_count',0 if backend is None else None),
        logical_call_budget=budget.snapshot(),
        arm='whole_response_single_nli',
        limitation=('Single whole-response NLI call per case; no atomic-statement decomposition '
            'or recall; not an official Ragas metric; no label/gold agreement is computed or claimed here.'),
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
    parser = argparse.ArgumentParser(prog='whole_response_reference_predict')
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
