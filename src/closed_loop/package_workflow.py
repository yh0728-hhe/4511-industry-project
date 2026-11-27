"""One-command composition of existing registry collection and package run.

No new agent/framework/provider: this module only wires PackageRegistryCollector
and execute_package_run behind a single reproducible entry point, plus a thin
CLI that gates local Claude Code CLI subscription routing before any action.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agent_prompts import prompt_fingerprint
from .cli_backend import ClaudeCliBackend
from .registry_process import IsolatedRegistryHTTPClient
from .contracts import CompanySeed, RunRequest
from .guards import BudgetStopped, CallBudget
from .package_registry import PackageRegistryCollector, RegistryHTTPClient
from .package_runner import execute_package_run

_REQUIRED_CONFIG_KEYS = frozenset({
    'company', 'mandate', 'as_of', 'package_name', 'artifact_format',
    'model', 'max_model_calls', 'max_seconds', 'check_argument_support',
})
_FORBIDDEN_ENV = (
    'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
    'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX',
)


def _parse_config(config):
    """Strict config -> (RunRequest, extra); raises ValueError, never touches disk/network."""
    if not isinstance(config, dict) or set(config) != _REQUIRED_CONFIG_KEYS:
        raise ValueError('EXACT_PACKAGE_WORKFLOW_CONFIG_KEYS_REQUIRED')

    company = config['company']
    if not isinstance(company, dict) or set(company) != {'company_id', 'name', 'domain'}:
        raise ValueError('EXACT_COMPANY_FIELDS_REQUIRED')
    seed = CompanySeed.from_dict(company)

    mandate = config['mandate']
    if not isinstance(mandate, str) or not mandate.strip():
        raise ValueError('EXPLICIT_MANDATE_REQUIRED')

    as_of_raw = config['as_of']
    if not isinstance(as_of_raw, str):
        raise ValueError('EXPLICIT_AS_OF_STRING_REQUIRED')
    try:
        as_of = datetime.fromisoformat(as_of_raw)
    except ValueError:
        raise ValueError('INVALID_AS_OF_TIMESTAMP') from None
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('TIMEZONE_AWARE_AS_OF_REQUIRED')

    if as_of != datetime(2024,4,4,23,59,59,tzinfo=timezone.utc):
        raise ValueError('PROJECT_HISTORICAL_CUTOFF_REQUIRED')

    package_name = config['package_name']
    if not isinstance(package_name, str) or not package_name.strip():
        raise ValueError('EXPLICIT_PACKAGE_NAME_REQUIRED')

    artifact_format = config['artifact_format']
    if artifact_format not in ('wheel', 'npm'):
        raise ValueError('UNSUPPORTED_ARTIFACT_FORMAT')

    model = config['model']
    if not isinstance(model, str) or not model.strip():
        raise ValueError('EXPLICIT_MODEL_REQUIRED')

    max_model_calls = config['max_model_calls']
    if type(max_model_calls) is not int or not 1 <= max_model_calls <= 24:
        raise ValueError('BOUNDED_MODEL_CALLS_REQUIRED')

    max_seconds = config['max_seconds']
    if type(max_seconds) is not int or not 1 <= max_seconds <= 480:
        raise ValueError('BOUNDED_SECONDS_REQUIRED')

    check_argument_support = config['check_argument_support']
    if type(check_argument_support) is not bool:
        raise ValueError('EXPLICIT_BOOLEAN_SUPPORT_FLAG_REQUIRED')

    components=('ragas_faithfulness.py','evidence_checked_committee.py','native_support.py','package_runner.py',
        'package_registry.py','package_source.py','npm_source.py','npm_names.py',
        'registry_process.py','registry_worker.py','cli_backend.py','cli_limits.py')
    build=hashlib.sha256(json.dumps({name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in components},sort_keys=True).encode()).hexdigest()
    prompt_version = f'package-workflow-v1:{prompt_fingerprint()}:{build}:support={check_argument_support}'
    deadline = datetime.now(timezone.utc) + timedelta(seconds=max_seconds)
    request = RunRequest(seed, mandate, as_of, 'registry-artifact-v1', model, prompt_version,
        deadline, max_model_calls, 2, 1, 2)
    return request, dict(package_name=package_name, artifact_format=artifact_format,
        check_argument_support=check_argument_support)


def execute_workflow(config, output_dir, *, http_client, backend_factory, approved=False):
    """Collect one historical artifact then run the existing committee on it.

    No implicit HTTP/model client is ever constructed here; the caller supplies
    both. The same CallBudget is shared across collection and analysis so no
    stage can reset a cap the other already spent.
    """
    if approved is not True:
        raise PermissionError('explicit workflow execution approval required')
    request, extra = _parse_config(config)
    if not callable(backend_factory) or not callable(getattr(http_client,'get',None)):
        raise ValueError('EXPLICIT_WORKFLOW_CLIENTS_REQUIRED')

    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=False)
    snapshot = dict(config=config, intent='PACKAGE_WORKFLOW_RUN',
        source_policy=request.source_policy, prompt_version=request.prompt_version,
        model=request.model_version, deadline=request.deadline.isoformat())
    (root / 'config_snapshot.json').write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + '\n', encoding='utf-8')

    budget = CallBudget(request)
    receipt = dict(status='WORKFLOW_FAILED', package_name=extra['package_name'],
        artifact_format=extra['artifact_format'], Y_changed=False, training_run=False)
    try:
        collector = PackageRegistryCollector(request, budget, http_client, root / 'registry.jsonl')
        collected = collector.collect(extra['package_name'], extra['artifact_format'])
        if collected is None:
            receipt.update(status='SOURCE_UNKNOWN', actual_model_calls=0,
                logical_call_budget=budget.snapshot())
        else:
            (root / ('source_artifact.whl' if extra['artifact_format']=='wheel' else 'source_artifact.tgz')).write_bytes(collected['artifact_bytes'])
            metadata_bytes=(json.dumps(collected['file_metadata'],indent=2,sort_keys=True)+'\n').encode('utf-8')
            (root/'source_metadata.json').write_bytes(metadata_bytes)
            receipt.update(artifact_sha256=hashlib.sha256(collected['artifact_bytes']).hexdigest(),
                source_metadata_sha256=hashlib.sha256(metadata_bytes).hexdigest())
            result = execute_package_run(request=request, output_dir=root / 'analysis',
                backend_factory=backend_factory, approved=True, call_budget=budget,
                check_argument_support=extra['check_argument_support'], **collected)
            normal_stops={'EVIDENCE_REVIEW_COMPLETE','NO_NEW_EVIDENCE','RESEARCH_PASS_CAP','NO_RESEARCH_TASKS','NO_ADMITTED_FACTS'}
            status=('PACKAGE_WORKFLOW_COMPLETED' if result.get('stop_reason') in normal_stops else 'WORKFLOW_STOPPED') if result['status']=='PACKAGE_SOURCE_RUNTIME_EXECUTED' else 'WORKFLOW_FAILED'
            receipt.update(status=status, analysis_status=result['status'],
                analysis_dir='analysis',analysis_decision=result.get('decision'),
                analysis_stop_reason=result.get('stop_reason'),logical_call_budget=budget.snapshot())
            if status!='PACKAGE_WORKFLOW_COMPLETED':
                receipt['stop_reason']=result.get('stop_reason') or budget.stop_reason or 'CHILD_ANALYSIS_FAILED'
    except BudgetStopped:
        receipt.update(status='WORKFLOW_STOPPED', stop_reason=budget.stop_reason,
            logical_call_budget=budget.snapshot())
    except Exception:
        receipt.update(status='WORKFLOW_FAILED',
            stop_reason=budget.stop_reason if budget.stopped else 'SANITIZED_EXECUTION_FAILURE',
            logical_call_budget=budget.snapshot())
    (root / 'workflow_receipt.json').write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return receipt


def _load_strict_config(path):
    with Path(path).open('rb') as stream:
        data=stream.read(32_001)
    if len(data) > 32_000:
        raise ValueError('CONFIG_TOO_LARGE')

    def _reject_duplicate(pairs):
        seen = set()
        result = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError('DUPLICATE_JSON_KEY')
            seen.add(key)
            result[key] = value
        return result

    def _reject_constant(_value):
        raise ValueError('INVALID_JSON_CONSTANT')

    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=_reject_duplicate,
            parse_constant=_reject_constant)
    except UnicodeDecodeError:
        raise ValueError('INVALID_CONFIG_ENCODING') from None


def _forbidden_env_present():
    return any(name in os.environ for name in _FORBIDDEN_ENV)


def _resolve_executable(explicit):
    if explicit:
        return explicit
    default = Path.home() / '.local' / 'bin' / 'claude.exe'
    if default.is_file():
        return str(default)
    return shutil.which('claude')


def _verify_subscription_auth(executable):
    """Separate local-CLI-auth check; never counted against the model-call budget."""
    try:
        completed = subprocess.run([executable, 'auth', 'status'],
            capture_output=True, timeout=20, check=False)
    except Exception:
        return False
    try:
        payload = json.loads(completed.stdout.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return False
    return (completed.returncode==0 and isinstance(payload, dict) and payload.get('loggedIn') is True
        and payload.get('authMethod') == 'claude.ai')


def _summarize_receipt(receipt):
    keys = ('status', 'package_name', 'artifact_format', 'analysis_status', 'stop_reason',
        'analysis_dir', 'analysis_decision', 'analysis_stop_reason', 'logical_call_budget')
    return {key: receipt[key] for key in keys if key in receipt}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='package_workflow')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--approve-cli', action='store_true')
    parser.add_argument('--claude-executable')
    args = parser.parse_args(argv)

    if not args.approve_cli:
        print('APPROVAL_REQUIRED: no auth, network, model, or output actions taken.')
        return 1

    try:
        config=_load_strict_config(args.config)
        _parse_config(config)
        if Path(args.output_dir).exists():raise ValueError('OUTPUT_ALREADY_EXISTS')
    except (ValueError,OSError,TypeError):
        print('REJECTED: invalid configuration or output already exists.')
        return 2

    if _forbidden_env_present():
        print('REJECTED: direct API credential environment variables are not permitted; '
              'only local claude.ai subscription login is supported.')
        return 1

    executable = _resolve_executable(args.claude_executable)
    if executable is None:
        print('REJECTED: no local Claude Code CLI executable found.')
        return 1

    if not _verify_subscription_auth(executable):
        print('REJECTED: local claude.ai subscription login not verified.')
        return 1

    def backend_factory(budget, root):
        return ClaudeCliBackend(approved=True, executable_path=executable,
            model_id=config.get('model'), call_budget=budget,
            max_process_count=config.get('max_model_calls'),
            journal_path=Path(root) / 'dispatch.jsonl',
            per_call_timeout_seconds=60, max_input_bytes=64000)

    try:
        receipt = execute_workflow(config, args.output_dir, http_client=IsolatedRegistryHTTPClient(),
            backend_factory=backend_factory, approved=True)
    except Exception:
        print('REJECTED: workflow could not complete; see local receipt file for sanitized detail.')
        return 1

    print(json.dumps(_summarize_receipt(receipt), indent=2, sort_keys=True))
    return 0 if receipt['status']=='PACKAGE_WORKFLOW_COMPLETED' else 2


if __name__ == '__main__':
    import sys
    sys.exit(main())
