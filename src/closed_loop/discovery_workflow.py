"""Guarded single-command entry around the existing execute_discovery_run.

This module wires already-validated components (ClaudeCliBackend,
ManagedWebDiscoveryAgent, ArchiveHTTPClient, execute_discovery_run) behind one
CLI that checks existing local claude.ai authentication before execution; billing is not certified.
No new agent, model client, or network transport is introduced here.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .agent_prompts import prompt_fingerprint
from .archive_transport import ArchiveHTTPClient
from .cli_backend import ClaudeCliBackend, ProcessExecutor
from .contracts import CompanySeed, RunRequest
from .discovery_runner import execute_discovery_run
from .registry_process import IsolatedRegistryHTTPClient
from .package_workflow import (
    _forbidden_env_present,
    _load_strict_config,
    _resolve_executable,
    _verify_subscription_auth,
)
from .web_discovery import ManagedWebDiscoveryAgent

_REQUIRED_CONFIG_KEYS = frozenset({
    'company', 'mandate', 'as_of', 'model', 'max_model_calls',
    'max_search_reservations', 'max_seconds', 'max_research_passes',
    'max_specialists', 'max_sources', 'check_argument_support',
    'verify_publishers', 'publisher_max_body_bytes',
})
_OPTIONAL_CONFIG_KEYS = frozenset({'preliminary_screen','verify_packages'})
_SOURCE_POLICY = 'archived-web-discovery-managed-search-v1'


class RecordingExecutor:
    """Wraps ProcessExecutor to persist raw argv/stdin/stdout/stderr per call.

    Each instance owns one exclusive capture folder and one private counter;
    failures are logged with only the sanitized exception type, never the
    exception message (which may carry private diagnostic text).
    """
    def __init__(self, capture_dir):
        self.capture_dir = Path(capture_dir)
        self.capture_dir.mkdir(parents=True, exist_ok=False)
        self._count = 0
        self._inner = ProcessExecutor()

    def run(self, argv, stdin_bytes, timeout_seconds):
        self._count += 1
        name = f'call_{self._count:03d}'
        meta = dict(argv=list(argv), timeout_seconds=timeout_seconds)
        (self.capture_dir / (name + '.stdin')).write_bytes(stdin_bytes)
        meta['status']='DISPATCHING'
        (self.capture_dir / (name + '.json')).write_text(
            json.dumps(meta,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        try:
            returncode, stdout, stderr = self._inner.run(argv, stdin_bytes, timeout_seconds)
        except Exception as exc:
            partial_stdout = getattr(exc, 'output', None)
            partial_stderr = getattr(exc, 'stderr', None)
            captured = []
            for suffix, data in (('.stdout',partial_stdout),('.stderr',partial_stderr)):
                if isinstance(data,bytes):
                    try:
                        (self.capture_dir / (name + suffix)).write_bytes(data)
                        captured.append(suffix)
                    except OSError as capture_exc:
                        meta['capture_error_type']=type(capture_exc).__name__
            meta.update(status='FAILED', error_type=type(exc).__name__,partial=bool(captured))
            try:
                (self.capture_dir / (name + '.json')).write_text(
                    json.dumps(meta, indent=2, sort_keys=True) + '\n', encoding='utf-8')
            except OSError:
                pass  # Durable dispatch intent remains; never mask the original failure.
            raise
        (self.capture_dir / (name + '.stdout')).write_bytes(stdout)
        (self.capture_dir / (name + '.stderr')).write_bytes(stderr)
        meta.update(status='COMPLETED', returncode=returncode)
        (self.capture_dir / (name + '.json')).write_text(
            json.dumps(meta, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return returncode, stdout, stderr


def _bounded_int(config, name, lo, hi):
    value = config[name]
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'BOUNDED_{name.upper()}_REQUIRED')
    return value


def _parse_config(config):
    """Strict config -> (RunRequest, extra); raises ValueError, never touches disk/network."""
    if not isinstance(config, dict):
        raise ValueError('EXACT_DISCOVERY_WORKFLOW_CONFIG_KEYS_REQUIRED')
    present = set(config)
    if not _REQUIRED_CONFIG_KEYS <= present or not present <= _REQUIRED_CONFIG_KEYS | _OPTIONAL_CONFIG_KEYS:
        raise ValueError('EXACT_DISCOVERY_WORKFLOW_CONFIG_KEYS_REQUIRED')

    company = config['company']
    if not isinstance(company, dict) or set(company) != {'company_id', 'name', 'domain'}:
        raise ValueError('EXACT_COMPANY_FIELDS_REQUIRED')
    seed = CompanySeed.from_dict(company)

    mandate = config['mandate']
    if not isinstance(mandate, str) or not mandate.strip():
        raise ValueError('EXPLICIT_MANDATE_REQUIRED')

    model = config['model']
    if not isinstance(model, str) or not model.strip():
        raise ValueError('EXPLICIT_MODEL_REQUIRED')

    as_of_raw = config['as_of']
    if not isinstance(as_of_raw, str):
        raise ValueError('EXPLICIT_AS_OF_STRING_REQUIRED')
    try:
        as_of = datetime.fromisoformat(as_of_raw)
    except ValueError:
        raise ValueError('INVALID_AS_OF_TIMESTAMP') from None
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError('TIMEZONE_AWARE_AS_OF_REQUIRED')
    if as_of.astimezone(timezone.utc) != datetime(2024, 4, 4, 23, 59, 59, tzinfo=timezone.utc):
        raise ValueError('PROJECT_HISTORICAL_CUTOFF_REQUIRED')

    max_model_calls = _bounded_int(config, 'max_model_calls', 1, 24)
    max_search_reservations = _bounded_int(config, 'max_search_reservations', 1, 12)
    max_seconds = _bounded_int(config, 'max_seconds', 1, 480)
    max_research_passes = _bounded_int(config, 'max_research_passes', 1, 2)
    max_specialists = _bounded_int(config, 'max_specialists', 1, 2)
    max_sources = _bounded_int(config, 'max_sources', 1, 3)
    publisher_max_body_bytes = _bounded_int(config, 'publisher_max_body_bytes', 128, 1048576)

    check_argument_support = config['check_argument_support']
    if type(check_argument_support) is not bool:
        raise ValueError('EXPLICIT_BOOLEAN_SUPPORT_FLAG_REQUIRED')
    verify_publishers = config['verify_publishers']
    if type(verify_publishers) is not bool:
        raise ValueError('EXPLICIT_BOOLEAN_PUBLISHER_FLAG_REQUIRED')

    verify_packages = config.get('verify_packages', False)
    if type(verify_packages) is not bool:
        raise ValueError('EXPLICIT_BOOLEAN_PACKAGE_FLAG_REQUIRED')

    preliminary_screen = config.get('preliminary_screen', False)
    if type(preliminary_screen) is not bool:
        raise ValueError('EXPLICIT_BOOLEAN_PRELIMINARY_SCREEN_FLAG_REQUIRED')

    prompt_version = (f'discovery-workflow-v1:{prompt_fingerprint()}:'
        f'support={check_argument_support}:publishers={verify_publishers}:packages={verify_packages}')
    deadline = datetime.now(timezone.utc) + timedelta(seconds=max_seconds)
    request = RunRequest(seed, mandate, as_of, _SOURCE_POLICY, model, prompt_version,
        deadline, max_model_calls, max_search_reservations, 1, max_research_passes)
    return request, dict(max_specialists=max_specialists, max_sources=max_sources,
        check_argument_support=check_argument_support, verify_publishers=verify_publishers,
        publisher_max_body_bytes=publisher_max_body_bytes, preliminary_screen=preliminary_screen,verify_packages=verify_packages)


def make_backend_factory(request, executable):
    """Builds the ClaudeCliBackend factory used by execute_discovery_run."""
    def backend_factory(budget, root):
        root = Path(root)
        executor = RecordingExecutor(root / 'backend_wire')
        return ClaudeCliBackend(approved=True, executable_path=executable,
            model_id=request.model_version, call_budget=budget,
            max_process_count=request.max_model_calls, journal_path=root / 'dispatch.jsonl',
            executor=executor, per_call_timeout_seconds=60, max_input_bytes=64000)
    return backend_factory


def make_discovery_factory(request, executable, *, verify_packages=False):
    """Builds the ManagedWebDiscoveryAgent factory; one fresh agent per task."""
    if type(verify_packages) is not bool:
        raise ValueError('explicit package-verification boolean required')
    counter = {'n': 0}
    def discovery_factory(task, budget, root):
        counter['n'] += 1
        idx = counter['n']
        root = Path(root)
        sub_root = root / f'discovery_{idx:03d}'
        executor = RecordingExecutor(root / f'discovery_{idx:03d}_wire')
        return ManagedWebDiscoveryAgent(request, budget, approved=True,
            executable_path=executable, output_dir=sub_root, executor=executor,
            per_call_timeout_seconds=60,package_leads=verify_packages)
    return discovery_factory


def _summarize_result(result):
    keys = ('status', 'decision', 'stop_reason', 'logical_call_budget',
        'managed_discovery_process_attempts', 'backend_process_attempts',
        'direct_archive_http_attempts','direct_registry_http_attempts','direct_source_http_attempts')
    return {key: result[key] for key in keys if key in result}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='discovery_workflow')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--approve-cli', action='store_true')
    parser.add_argument('--claude-executable')
    args = parser.parse_args(argv)

    if not args.approve_cli:
        print('APPROVAL_REQUIRED: no auth, network, model, or output actions taken.')
        return 1

    try:
        config = _load_strict_config(args.config)
        request, extra = _parse_config(config)
        if Path(args.output_dir).exists():
            raise ValueError('OUTPUT_ALREADY_EXISTS')
    except (ValueError, OSError, TypeError):
        print('REJECTED: invalid configuration or output already exists.')
        return 1

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

    try:
        # Authentication has its own bounded check; analysis deadline starts now.
        request,extra=_parse_config(config)
        backend_factory=make_backend_factory(request,executable)
        def configured_backend(budget,root):
            with (Path(root)/'config_snapshot.json').open('x',encoding='utf-8') as stream:
                json.dump(config,stream,indent=2,sort_keys=True)
                stream.write('\n')
            return backend_factory(budget,root)
        result = execute_discovery_run(request=request, output_dir=args.output_dir,
            backend_factory=configured_backend,
            discovery_factory=make_discovery_factory(request, executable,verify_packages=extra['verify_packages']),
            http_client=ArchiveHTTPClient(), approved=True,
            check_argument_support=extra['check_argument_support'],
            max_sources=extra['max_sources'], verify_publishers=extra['verify_publishers'],
            max_specialists=extra['max_specialists'],
            publisher_max_body_bytes=extra['publisher_max_body_bytes'],
            preliminary_screen=extra['preliminary_screen'],
            verify_packages=extra['verify_packages'],
            registry_http_client=IsolatedRegistryHTTPClient() if extra['verify_packages'] else None)
    except Exception:
        print('REJECTED: discovery workflow could not complete; see local result file for sanitized detail.')
        return 1

    print(json.dumps(_summarize_result(result), indent=2, sort_keys=True))
    if result['status'] == 'DISCOVERY_RUNTIME_EXECUTED':
        return 0
    if result['status'] == 'DISCOVERY_RUNTIME_STOPPED':
        return 2
    return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
