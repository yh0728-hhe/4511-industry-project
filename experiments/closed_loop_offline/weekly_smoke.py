"""Plan a separate real-company smoke test; paid execution requires fresh approval.

The default command reads historical cohort identity and hashes the prompt
sources before writing a plan. It does not inspect credentials, contact a
provider, or load outcome tables.
"""
import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from closed_loop.archive_transport import ArchivedWebsiteProvider
from closed_loop.agent_prompts import prompt_fingerprint
from closed_loop.contracts import CompanySeed, RunRequest
from closed_loop.guards import BudgetStopped, CallBudget, TemporalGateway
from closed_loop.model_lead import ModelLead
from closed_loop.native_committee import NativeConfig, NativeDialecticCommittee
from closed_loop.openai_backend import MODEL, RATE_SOURCE, create_live_backend
from closed_loop.runtime import ClosedLoopRuntime

COHORT = ROOT / 'data/processed/w24_spreadsheet_2024-03-25.csv'
PLAN_DIR = ROOT / 'data/weekly_smoke_20261119'
LIVE_DIR = ROOT / 'results/candidates/weekly_smoke_20261119'
CUTOFF = datetime(2024, 4, 4, 23, 59, 59, tzinfo=timezone.utc)
MAX_USD = Decimal('0.20')
MAX_MODEL_CALLS = 24
MAX_HTTP_REQUESTS = 6
MAX_MINUTES = 8
PILOT_ID = 'weekly-20261119-adagy-w24-asof20240404'


def sha256_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def select_company(cohort=COHORT):
    """Use only historical name/domain; alphabetical selection excludes Abel."""
    with Path(cohort).open(encoding='utf-8-sig', newline='') as stream:
        rows = sorted(csv.DictReader(stream), key=lambda row: row['Company Name'].casefold())
    for row in rows:
        name = row['Company Name'].strip()
        if name.casefold() == 'abel':
            continue
        parsed = urlparse(row['Company Website'])
        if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
            continue
        domain = (parsed.hostname or '').lower()
        try:
            return CompanySeed('w24:' + domain, name, domain)
        except ValueError:
            continue
    raise ValueError('No eligible non-Abel historical company; no fallback selection')


def prepare_plan(cohort=COHORT):
    company = select_company(cohort)
    seed = asdict(company)
    plan = dict(
        status='NOT_RUN_USER_DEFERRED_PAID_EXECUTION',
        user_execution_choice='On 2026-11-19 the user requested code and plan upload without paid execution.',
        pilot_id=PILOT_ID,
        companies=1,
        company=seed,
        selection='first alphabetical valid historical cohort name/domain, excluding Abel; no Y selection',
        input_seed_sha256=sha256_json(seed),
        cohort_path='data/processed/w24_spreadsheet_2024-03-25.csv',
        cohort_sha256=hashlib.sha256(Path(cohort).read_bytes()).hexdigest(),
        model_input_fields=['company_id', 'name', 'domain', 'mandate', 'cutoff', 'gateway-admitted historical evidence'],
        as_of=CUTOFF.isoformat(),
        model=MODEL,
        prompt_bundle_sha256=prompt_fingerprint(),
        rate_source=RATE_SOURCE,
        proposed_api_budget_usd=str(MAX_USD),
        max_api_requests=MAX_MODEL_CALLS,
        max_archive_http_requests=MAX_HTTP_REQUESTS,
        max_wall_minutes=MAX_MINUTES,
        max_research_passes=2,
        research_backend='MeteredResearchProvider',
        max_navigation_steps_per_task=2,
        max_output_tokens_per_request=1000,
        max_request_bytes=32768,
        native_config=asdict(NativeConfig(selection_policy='balanced_per_side')),
        no_sdk_retries=True,
        no_automatic_model_fallback=True,
        no_current_web_fallback=True,
        y_read=False,
        post_cutoff_source_content_allowed=False,
        original_abel_pilot_reused=False,
        pretrained_future_knowledge_exclusion_proven=False,
        historical_domain_ownership_independently_verified=False,
        stop_rules=['24 API request attempts', '$0.20 conservative reservation cap',
                    '6 archive HTTP requests', '8 minute deadline',
                    'missing/invalid provider token usage', 'provider/schema/validation failure',
                    'no new admissible evidence', '2 research passes'],
        outputs=['plan.json', 'result.json', 'api_budget.jsonl'],
        limits='One-company wiring/retrieval smoke test; no predictive accuracy or investment-performance claim.',
    )
    plan['plan_sha256'] = sha256_json(plan)
    return plan


def approved_limit(value):
    try:
        limit = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError('approval must be a positive dollar amount at most 0.20') from None
    if not limit.is_finite() or not Decimal('0') < limit <= MAX_USD:
        raise ValueError('approval must be a positive dollar amount at most 0.20')
    return limit


class UsageRequiredBackend:
    """Stop immediately if a successful call lacks auditable token accounting."""
    stop_on_validation_error = True

    def __init__(self, backend):
        self.backend = backend
        self.call_budget = backend.call_budget

    def generate(self, schema, messages, temperature):
        try:
            self.call_budget.check()
            before = len(self.backend.attempts)
            value = self.backend.generate(schema, messages, temperature)
            attempts = self.backend.attempts[before:]
            if len(attempts) != 1 or any(
                    type(attempt.get(field)) is not int or attempt[field] < 0
                    for attempt in attempts for field in ('input_tokens', 'output_tokens')):
                for attempt in attempts:
                    attempt['status'] = 'USAGE_UNKNOWN_OR_INVALID'
                raise BudgetStopped('API_USAGE_UNKNOWN_OR_INVALID')
            return value
        except BaseException:
            # Native committee stages queue asynchronous siblings. Stop before
            # unwinding/releasing their semaphore so none can dispatch after a
            # provider, accounting, schema or unexpected backend failure.
            self.call_budget.stop()
            raise


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def run_live(plan, *, limit, approved_plan_sha256, env_file=None):
    """The caller must already possess explicit user approval for this plan."""
    limit = approved_limit(limit)
    if approved_plan_sha256 != plan['plan_sha256']:
        raise PermissionError('Explicit approval of this exact saved plan is required')
    content = {key: value for key, value in plan.items() if key != 'plan_sha256'}
    if sha256_json(content) != plan['plan_sha256']:
        raise ValueError('Plan contents changed after fingerprinting; obtain new approval')
    if sha256_json(plan) != sha256_json(prepare_plan()):
        raise ValueError('Only the canonical current plan may execute; regenerate the plan and obtain approval')
    expected = CompanySeed('w24:www.adagyrobotics.com', 'Adagy Robotics', 'www.adagyrobotics.com')
    company = CompanySeed.from_dict(plan['company'])
    if company != expected:
        raise ValueError('Planned identity changed; obtain a new plan and approval')
    started = datetime.now(timezone.utc)
    request = RunRequest(
        company,
        'Seed-stage due diligence: inspect product, team, market, competition and traction; '
        'identify essential unknowns using only admitted evidence available by the cutoff.',
        CUTOFF, 'archive-raw-replay-weekly-v1', MODEL, 'weekly-20261119-v1',
        started + timedelta(minutes=MAX_MINUTES), MAX_MODEL_CALLS, MAX_HTTP_REQUESTS, 1, 2)
    budget = CallBudget(request)
    gateway = TemporalGateway(request, [])
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    # Fixed journal/pilot identity cannot be reset through an output-directory flag.
    try:
        backend = create_live_backend(
            approved=True, limit_usd=str(limit), call_budget=budget, env_file=env_file,
            journal_path=LIVE_DIR / 'api_budget.jsonl', pilot_id=PILOT_ID)
    except Exception as exc:
        result = dict(status='NOT_RUN_BACKEND_SETUP_FAILED', decision='MORE_DILIGENCE',
                      stop_reason='BACKEND_SETUP_FAILED', error_type=type(exc).__name__,
                      plan_sha256=plan['plan_sha256'], input_seed_sha256=plan['input_seed_sha256'],
                      company=plan['company'], actual_api_request_attempts=0,
                      archive_http_requests=0, y_read=False,
                      rationale='No provider dispatch occurred in this invocation.')
        # A sealed/leased prior pilot can reject setup. Preserve its result and
        # keep each rejected invocation's diagnostics in a distinct artifact.
        failure_path = LIVE_DIR / ('setup_failure_' + uuid.uuid4().hex + '.json')
        result['output_file'] = failure_path.name
        save_json(failure_path, result)
        return result
    archive = None
    provider = None
    try:
        try:
            from closed_loop.research_backend import MeteredResearchProvider
            metered_backend = UsageRequiredBackend(backend)
            archive = ArchivedWebsiteProvider(request, gateway, budget, max_requests=MAX_HTTP_REQUESTS,
                                              max_body_bytes=2097152)
            provider = MeteredResearchProvider(request, gateway, budget, metered_backend,
                                               archive, max_navigation_steps=2)
            committee = NativeDialecticCommittee(metered_backend, budget,
                                                 NativeConfig(selection_policy='balanced_per_side'))
            runtime = ClosedLoopRuntime(request, gateway, budget,
                                        ModelLead(metered_backend, budget), committee, provider)
            result = runtime.run()
        except Exception as exc:
            # Do not save provider exception text, which can contain credentials.
            result = dict(decision='MORE_DILIGENCE', stop_reason='VALIDATION_OR_RUNTIME_FAILURE',
                          error_type=type(exc).__name__, rationale='No supported decision after failure.')
        result.update(
            status='ONE_COMPANY_SMOKE_NOT_A_BACKTEST', company=plan['company'],
            plan_sha256=plan['plan_sha256'], input_seed_sha256=plan['input_seed_sha256'],
            started_utc=started.isoformat(), finished_utc=datetime.now(timezone.utc).isoformat(),
            actual_api_request_attempts=len(backend.attempts),
            provider_usage_attempt_records=backend.attempts,
            api_spend_envelope=backend.envelope.snapshot(),
            archive_http_requests=budget.used['search'],
            archive_attempts=archive.attempts if archive else [],
            archive_receipts=archive.receipts if archive else [],
            research_trace=provider.trace if provider else [],
            y_read=False, raw_bodies_saved=False,
            pretrained_future_knowledge_exclusion_proven=False,
            historical_domain_ownership_independently_verified=False)
        save_json(LIVE_DIR / 'result.json', result)
        return result
    finally:
        # A completed/failed dispatch is a single pilot; unused balance is sealed.
        try:
            backend.envelope.seal_completed()
        finally:
            backend.envelope.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-api-usd', default=None,
                        help='Set only after explicit user approval of separate API spending.')
    parser.add_argument('--approved-plan-sha256', default=None,
                        help='Fingerprint of the exact plan the user approved.')
    parser.add_argument('--env-file', default=None,
                        help='Existing OpenAI application configuration; not read by a dry run.')
    parser.add_argument('--plan-output', type=Path, default=PLAN_DIR / 'plan.json')
    args = parser.parse_args(argv)
    plan = prepare_plan()
    save_json(args.plan_output, plan)
    if args.approve_api_usd is None:
        if args.approved_plan_sha256 is not None:
            parser.error('plan fingerprint alone does not approve API spending')
        print(json.dumps(dict(status=plan['status'], company=plan['company']['name'],
                              plan_sha256=plan['plan_sha256'], actual_api_requests=0,
                              actual_archive_requests=0)))
        return plan
    try:
        limit = approved_limit(args.approve_api_usd)
        if args.approved_plan_sha256 != plan['plan_sha256']:
            parser.error('approve the exact saved plan fingerprint before live execution')
        result = run_live(plan, limit=str(limit), approved_plan_sha256=args.approved_plan_sha256,
                          env_file=args.env_file)
    except (ValueError, PermissionError) as exc:
        parser.error(str(exc))
    print(json.dumps(dict(status=result['status'], company=plan['company']['name'],
                          decision=result['decision'], stop_reason=result['stop_reason'],
                          actual_api_requests=result['actual_api_request_attempts'])))
    return result


if __name__ == '__main__':
    main()
