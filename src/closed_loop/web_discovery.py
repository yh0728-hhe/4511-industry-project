"""Reusable adapter over the installed Claude Code CLI's own WebSearch agent.

This is plumbing, not fact research: it dispatches one managed CLI process
whose output must show exactly one WebSearch call and returns only the URLs it
actually observed, as unverified leads. No fact is ever admitted here, no
source whitelist or fixed feature list is enforced, and host CLI auth/billing
approval is the caller's responsibility -- this class never implies a
subscription or bills from its own name.
"""
from .model_identity import model_subject_id
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json
import re
import subprocess

from .cli_backend import ProcessExecutor
from .cli_limits import find_primary_rate_limit_rejection, is_quota_result_envelope
from .contracts import ResearchRequest, RunRequest
from .guards import BudgetStopped

WEB_DISCOVERY_SYSTEM = (
    'You are an isolated managed web-discovery capability adapter reusing the '
    'installed WebSearch tool. Only WebSearch and StructuredOutput are '
    'permitted. No file access, coding, fact admission, date certification or '
    'company evaluation. Formulate exactly one WebSearch query targeting '
    'historical leads for the given role/question/subject, perform exactly '
    'one WebSearch call, then return only the URLs actually present in that '
    'search result via StructuredOutput. Results are unverified leads.'
)
DISCOVERY_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string'},
        'urls': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 5},
    },
    'required': ['status', 'urls'],
    'additionalProperties': False,
}
ALLOWED_TOOLS = frozenset(('WebSearch', 'StructuredOutput'))
RESOURCE_UNIT_NOTE = (
    'One logical "search" budget reservation represents this single managed '
    'discovery invocation; one separate "model" budget reservation represents '
    'the outer CLI process, used sequentially (not nested) because '
    'concurrency is 1. Internal HTTP calls and model inferences made inside '
    'the managed CLI are UNKNOWN and are never implied or covered by these '
    'two outer reservations.'
)
_LINKS_LINE = re.compile(r'^Links: ', re.MULTILINE)


@dataclass(frozen=True)
class DiscoveryResult:
    status: str
    source_urls: tuple
    admitted_fact_count: int
    historical_availability: str
    verified: bool
    managed_http: str
    observed_websearch_count: int
    budget_snapshot: dict
    resource_unit_note: str


def _valid_lead_url(value):
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return (parts.scheme in ('http', 'https') and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and not any(c.isspace() or ord(c) < 32 for c in value)
                and parts.port != 0)
    except ValueError:
        return False


class ManagedWebDiscoveryAgent:
    """Dispatches one managed CLI WebSearch probe; never admits facts."""

    def __init__(self, request, budget, *, approved=False, executable_path,
            output_dir, executor=None, per_call_timeout_seconds=90, package_leads=False):
        if approved is not True:
            raise PermissionError('Separate existing-agent usage approval required; subscription billing is not implied by this class')
        if not isinstance(request, RunRequest):
            raise ValueError('explicit RunRequest required')
        if budget.bound_request is not request:
            raise ValueError('budget must be bound to the same explicit request')
        if not isinstance(executable_path, str) or not executable_path.strip():
            raise ValueError('explicit CLI executable path required')
        if type(per_call_timeout_seconds) is not int or not 1 <= per_call_timeout_seconds <= 90:
            raise ValueError('explicit per-call timeout in 1..90 seconds required')
        if type(package_leads) is not bool:
            raise ValueError('explicit package-lead capability boolean required')
        self.package_leads=package_leads
        self.request = request
        self.call_budget = budget
        self.executable_path = executable_path
        self.model_id = request.model_version
        self.per_call_timeout_seconds = per_call_timeout_seconds
        self.executor = executor if executor is not None else ProcessExecutor()
        self.output_dir = Path(output_dir)
        self.process_count = 0
        self._used = False
        try:
            self.output_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise BudgetStopped('WEB_DISCOVERY_OUTPUT_DIR_EXISTS') from None

    def _build_argv(self):
        return [
            self.executable_path, '--safe-mode', '--permission-mode', 'dontAsk',
            '--tools', 'WebSearch', '--allowedTools', 'WebSearch',
            '--max-turns', '3', '--disable-slash-commands', '--no-session-persistence',
            '--output-format', 'stream-json', '--verbose',
            '--model', self.model_id, '--system-prompt', WEB_DISCOVERY_SYSTEM,
            '--json-schema', json.dumps(DISCOVERY_SCHEMA), '-p',
        ]

    def _build_prompt(self, task):
        seed = self.request.company
        lines = (
            f'identity_seed: company_id={model_subject_id(seed.company_id)} name={seed.name} domain={seed.domain}',
            f'mandate: {self.request.mandate}',
            f'as_of: {self.request.as_of.isoformat()}',
            f'role: {task.role}',
            f'question: {task.question}',
            f'subject: {model_subject_id(task.company_id, task.subject_id)}',
            'Formulate exactly one WebSearch query targeting historical leads for '
            'this subject and question. Perform exactly one WebSearch call. Return '
            'only the URLs actually present in that search result as unverified leads.',
        )
        if self.package_leads:
            lines += ('Downstream capability: when relevant to this question, an independent '
                'verifier can inspect historical artifacts from unversioned public PyPI/npm '
                'package URLs. This is an optional source type, not a required package, '
                'source whitelist or evidence. Return such a URL only if actually observed '
                'in the one search result; do not invent a package or assert its date/content.',)
        return ('\n'.join(lines)).encode('utf-8')

    def _write_intent(self, prompt_hash, argv_hash):
        with (self.output_dir / 'intent.json').open('x', encoding='utf-8') as stream:
            json.dump(dict(prompt_hash=prompt_hash, argv_hash=argv_hash), stream, sort_keys=True)

    def _save_raw(self, stdout, stderr):
        try:
            with (self.output_dir / 'raw_stream.jsonl').open('xb') as stream:
                stream.write(stdout)
            with (self.output_dir / 'raw_stderr.txt').open('xb') as stream:
                stream.write(stderr)
        except OSError:
            self.call_budget.stop('WEB_DISCOVERY_PERSISTENCE_FAILED')
            raise BudgetStopped(self.call_budget.stop_reason) from None

    def _write_result(self, status, urls, observed_count=0):
        result = DiscoveryResult(
            status=status, source_urls=tuple(urls), admitted_fact_count=0,
            historical_availability='UNVERIFIED', verified=False, managed_http='UNKNOWN',
            observed_websearch_count=observed_count, budget_snapshot=self.call_budget.snapshot(),
            resource_unit_note=RESOURCE_UNIT_NOTE,
        )
        try:
            with (self.output_dir / 'result.json').open('x', encoding='utf-8') as stream:
                json.dump(dict(status=result.status, source_urls=list(result.source_urls),
                    admitted_fact_count=result.admitted_fact_count,
                    historical_availability=result.historical_availability, verified=result.verified,
                    managed_http=result.managed_http, observed_websearch_count=result.observed_websearch_count,
                    budget_snapshot=result.budget_snapshot, resource_unit_note=result.resource_unit_note,
                    stop_reason=self.call_budget.stop_reason if self.call_budget.stopped else None),
                    stream, sort_keys=True)
        except OSError:
            self.call_budget.stop('WEB_DISCOVERY_PERSISTENCE_FAILED')
            raise BudgetStopped(self.call_budget.stop_reason) from None
        return result

    @staticmethod
    def _quota_signal_from_timeout_output(output):
        """Inspect only complete top-level JSONL frames captured before a timeout.

        Stops at the first incomplete/malformed/non-dict frame without losing an
        earlier trusted rejection already found; never looks at nested tool text,
        stderr, or ordinary words.
        """
        if not isinstance(output, (bytes, bytearray)):
            return None
        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                break
            if not isinstance(event, dict):
                break
            if (find_primary_rate_limit_rejection((event,)) is not None or
                    (event.get('type') == 'result' and is_quota_result_envelope(event))):
                return 'CLI_QUOTA_EXHAUSTED'
        return None

    @staticmethod
    def _content_text(content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return '\n'.join(block.get('text', '') for block in content if isinstance(block, dict))
        return ''

    @staticmethod
    def _extract_links(text):
        match = _LINKS_LINE.search(text)
        if match is None:
            return None
        try:
            value, _ = json.JSONDecoder().raw_decode(text, match.end())
        except ValueError:
            return None
        if not isinstance(value, list):
            return None
        links = set()
        for item in value:
            if isinstance(item, dict) and _valid_lead_url(item.get('url')):
                links.add(item['url'])
        return links

    @staticmethod
    def _validate_structured(structured, actual_links):
        if not isinstance(structured, dict) or set(structured) != {'status', 'urls'}:
            return None, 'SCHEMA_INVALID'
        status_text, urls = structured['status'], structured['urls']
        if not isinstance(status_text, str) or not isinstance(urls, list):
            return None, 'SCHEMA_INVALID'
        if len(urls) > 5 or not all(isinstance(u, str) for u in urls):
            return None, 'SCHEMA_INVALID'
        if len(set(urls)) != len(urls) or not all(_valid_lead_url(u) for u in urls):
            return None, 'SCHEMA_INVALID'
        if not set(urls) <= actual_links:
            return None, 'UNOBSERVED_URL'
        return tuple(urls), None

    def discover(self, task):
        if self._used:
            raise BudgetStopped('WEB_DISCOVERY_ALREADY_USED')
        self._used = True
        if not isinstance(task, ResearchRequest):
            raise ValueError('explicit ResearchRequest task required')
        if task.company_id != self.request.company.company_id:
            raise ValueError('task company_id does not match the bound request; rejected before dispatch')
        self.call_budget.check()
        prompt_bytes = self._build_prompt(task)
        argv = self._build_argv()
        prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()
        argv_hash = hashlib.sha256(json.dumps(argv, sort_keys=True).encode('utf-8')).hexdigest()
        with self.call_budget.reserve('search'):
            pass
        self._write_intent(prompt_hash, argv_hash)
        try:
            with self.call_budget.reserve('model'):
                self.call_budget.check()
                self.process_count += 1
                timeout = min(self.per_call_timeout_seconds, self.call_budget.remaining_seconds())
                returncode, stdout, stderr = self.executor.run(argv, prompt_bytes, timeout)
        except Exception as exc:
            if isinstance(exc, BudgetStopped):
                reason = str(exc)
            elif isinstance(exc, subprocess.TimeoutExpired):
                quota_reason = self._quota_signal_from_timeout_output(exc.output)
                if quota_reason is not None:
                    reason = quota_reason
                else:
                    try:
                        self.call_budget.check()
                        reason = 'WEB_DISCOVERY_PROCESS_TIMEOUT'
                    except BudgetStopped as deadline_exc:
                        reason = str(deadline_exc)
            else:
                reason = 'WEB_DISCOVERY_PROCESS_FAILED'
            self.call_budget.stop(reason)
            self._write_result('STOPPED', ())
            raise BudgetStopped(self.call_budget.stop_reason) from None
        self._save_raw(stdout, stderr)
        self.call_budget.check()
        return self._parse(returncode, stdout)

    def _parse(self, returncode, stdout):
        try:
            text = stdout.decode('utf-8')
        except UnicodeDecodeError:
            self.call_budget.stop('WEB_DISCOVERY_MALFORMED_STREAM')
            self._write_result('MALFORMED_STREAM', ())
            raise BudgetStopped('WEB_DISCOVERY_MALFORMED_STREAM') from None
        events = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event=json.loads(line)
                if not isinstance(event,dict):raise ValueError('STREAM_EVENT_NOT_OBJECT')
                events.append(event)
            except ValueError:
                self.call_budget.stop('WEB_DISCOVERY_MALFORMED_STREAM')
                self._write_result('MALFORMED_STREAM', ())
                raise BudgetStopped('WEB_DISCOVERY_MALFORMED_STREAM') from None
            quota_signal = (find_primary_rate_limit_rejection((event,)) is not None or
                (event.get('type')=='result' and is_quota_result_envelope(event)))
            if quota_signal:
                self.call_budget.stop('CLI_QUOTA_EXHAUSTED')
                self._write_result('QUOTA_EXHAUSTED', ())
                raise BudgetStopped(self.call_budget.stop_reason)
        if returncode != 0:
            self.call_budget.stop('WEB_DISCOVERY_NONZERO_RETURNCODE')
            self._write_result('NONZERO_RETURNCODE', ())
            raise BudgetStopped('WEB_DISCOVERY_NONZERO_RETURNCODE')

        tool_use_events = []
        tool_result_events = {}
        for event in events:
            message = event.get('message') if isinstance(event, dict) else None
            content = message.get('content') if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            if event.get('type') == 'assistant':
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'tool_use':
                        tool_use_events.append((item.get('id'), item.get('name')))
            elif event.get('type') == 'user':
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'tool_result':
                        result_id = item.get('tool_use_id')
                        if not isinstance(result_id, str) or result_id in tool_result_events:
                            self.call_budget.stop('WEB_DISCOVERY_DUPLICATE_OR_INVALID_TOOL_RESULT')
                            self._write_result('DUPLICATE_OR_INVALID_TOOL_RESULT', ())
                            raise BudgetStopped(self.call_budget.stop_reason)
                        tool_result_events[result_id] = (bool(item.get('is_error', False)), item.get('content'))

        for _id, name in tool_use_events:
            if name not in ALLOWED_TOOLS:
                self.call_budget.stop('WEB_DISCOVERY_UNEXPECTED_TOOL')
                self._write_result('UNEXPECTED_TOOL', ())
                raise BudgetStopped('WEB_DISCOVERY_UNEXPECTED_TOOL')

        ids = [i for i, _ in tool_use_events]
        if any(not isinstance(i, str) or not i for i in ids) or len(ids) != len(set(ids)):
            self.call_budget.stop('WEB_DISCOVERY_DUPLICATE_OR_INVALID_TOOL_ID')
            self._write_result('DUPLICATE_OR_INVALID_TOOL_ID', ())
            raise BudgetStopped(self.call_budget.stop_reason)
        websearch_ids = [i for i, n in tool_use_events if n == 'WebSearch']
        successful_search_ids = [i for i in websearch_ids
            if i in tool_result_events and tool_result_events[i][0] is False]
        if len(websearch_ids) != 1 or len(successful_search_ids) != 1:
            self.call_budget.stop('WEB_DISCOVERY_WEBSEARCH_COUNT')
            self._write_result('WEBSEARCH_COUNT', (), observed_count=len(successful_search_ids))
            raise BudgetStopped('WEB_DISCOVERY_WEBSEARCH_COUNT')

        _, content = tool_result_events[successful_search_ids[0]]
        actual_links = self._extract_links(self._content_text(content))
        if actual_links is None:
            self.call_budget.stop('WEB_DISCOVERY_LINKS_PARSE_FAILED')
            self._write_result('LINKS_PARSE_FAILED', (), observed_count=1)
            raise BudgetStopped('WEB_DISCOVERY_LINKS_PARSE_FAILED')

        final = next((e for e in reversed(events) if isinstance(e, dict) and e.get('type') == 'result'), None)
        if final is None or final.get('is_error') is not False:
            self.call_budget.stop('WEB_DISCOVERY_SCHEMA_INVALID')
            self._write_result('SCHEMA_INVALID', (), observed_count=1)
            raise BudgetStopped('WEB_DISCOVERY_SCHEMA_INVALID')

        urls, reason = self._validate_structured(final.get('structured_output'), actual_links)
        if reason is not None:
            self.call_budget.stop(f'WEB_DISCOVERY_{reason}')
            self._write_result(reason, (), observed_count=1)
            raise BudgetStopped(f'WEB_DISCOVERY_{reason}')

        status = 'HELD_FOR_VERIFICATION' if urls else 'NO_LEADS'
        return self._write_result(status, urls, observed_count=1)
