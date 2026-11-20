"""Approval/preflight tests; no real SDK, key, network or model is used."""
from contextlib import redirect_stdout, redirect_stderr
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'experiments/closed_loop_offline/weekly_smoke.py'
SPEC = importlib.util.spec_from_file_location('weekly_smoke', PATH)
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


class WeeklySmokeTests(unittest.TestCase):
    def test_company_selection_is_historical_deterministic_and_separate_from_abel(self):
        plan = smoke.prepare_plan()
        self.assertEqual(plan['company']['name'], 'Adagy Robotics')
        self.assertEqual(plan['company']['domain'], 'www.adagyrobotics.com')
        self.assertEqual(plan, smoke.prepare_plan())
        self.assertFalse(plan['y_read'])
        self.assertFalse(plan['original_abel_pilot_reused'])
        self.assertEqual(plan['as_of'], '2024-04-04T23:59:59+00:00')

    def test_default_saves_plan_without_credentials_provider_or_outcome_reads(self):
        actual_open = Path.open
        reads = []
        allowed_reads = {
            smoke.COHORT.resolve(),
            (smoke.ROOT / 'src/closed_loop/vendor/dialectic_committee_nodes.py').resolve(),
            (smoke.ROOT / 'src/closed_loop/vendor/dialectic_decision.py').resolve(),
        }
        def guarded_open(path, mode='r', *args, **kwargs):
            if 'r' in mode:
                reads.append(path.resolve())
                self.assertIn(path.resolve(), allowed_reads)
            return actual_open(path, mode, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'new/nested/plan.json'
            with patch.object(Path, 'open', guarded_open), \
                    patch.object(smoke, 'create_live_backend', side_effect=AssertionError('live backend forbidden')), \
                    patch.object(smoke, 'run_live', side_effect=AssertionError('live call forbidden')), \
                    redirect_stdout(io.StringIO()):
                plan = smoke.main(['--plan-output', str(output), '--env-file', 'MUST_NOT_BE_READ'])
            saved = json.loads(output.read_text())
            self.assertEqual(saved['plan_sha256'], plan['plan_sha256'])
            self.assertEqual(plan['status'], 'NOT_RUN_USER_DEFERRED_PAID_EXECUTION')
            self.assertTrue(reads)

    def test_invalid_limits_and_missing_exact_plan_approval_never_create_backend(self):
        invalid = ['0', '-1', '0.21', 'NaN', 'Infinity', 'bad']
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(smoke, 'create_live_backend', side_effect=AssertionError('live backend forbidden')), \
                redirect_stderr(io.StringIO()):
            for value in invalid:
                with self.subTest(value=value), self.assertRaises(SystemExit):
                    smoke.main(['--approve-api-usd', value, '--plan-output', str(Path(folder) / 'plan.json')])
            with self.assertRaises(SystemExit):
                smoke.main(['--approve-api-usd', '0.20', '--plan-output', str(Path(folder) / 'plan.json')])
            with self.assertRaises(PermissionError):
                smoke.run_live(smoke.prepare_plan(), limit='0.20', approved_plan_sha256='wrong')

    def test_company_change_fails_before_credential_loading(self):
        plan = smoke.prepare_plan()
        plan['company']['name'] = 'A different company'
        with patch.object(smoke, 'create_live_backend', side_effect=AssertionError('live backend forbidden')):
            with self.assertRaisesRegex(ValueError, 'contents changed'):
                smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])

    def test_self_consistent_forged_caps_or_seed_are_rejected_before_backend(self):
        for field, value in [('max_api_requests', 1), ('input_seed_sha256', 'forged-seed-hash')]:
            with self.subTest(field=field):
                plan = smoke.prepare_plan()
                plan[field] = value
                plan['plan_sha256'] = smoke.sha256_json(
                    {key: entry for key, entry in plan.items() if key != 'plan_sha256'})
                with patch.object(smoke, 'create_live_backend', side_effect=AssertionError('live backend forbidden')):
                    with self.assertRaisesRegex(ValueError, 'canonical current plan'):
                        smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])

    def test_prompt_bundle_changes_invalidate_saved_plan_before_backend(self):
        plan = smoke.prepare_plan()
        with patch.object(smoke, 'prompt_fingerprint', return_value='changed-prompt-bundle'), \
                patch.object(smoke, 'create_live_backend', side_effect=AssertionError('live backend forbidden')):
            changed = smoke.prepare_plan()
            self.assertEqual(plan['input_seed_sha256'], changed['input_seed_sha256'])
            self.assertNotEqual(plan['plan_sha256'], changed['plan_sha256'])
            with self.assertRaisesRegex(ValueError, 'canonical current plan'):
                smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])

    def test_missing_invalid_or_negative_usage_stops_further_calls(self):
        class FakeBackend:
            def __init__(self, usage):
                self.attempts = []
                self.call_budget = SimpleNamespace(check=lambda: None,
                                                   stop=lambda: setattr(self, 'stopped', True))
                self.usage = usage
                self.stopped = False
            def generate(self, *args):
                self.attempts.append(self.usage)
                return 'valid typed result'
        for incoming, outgoing in [(None, None), (True, 1), (1, -1), (1, None)]:
            backend = FakeBackend(dict(input_tokens=incoming, output_tokens=outgoing))
            with self.assertRaisesRegex(smoke.BudgetStopped, 'USAGE_UNKNOWN_OR_INVALID'):
                smoke.UsageRequiredBackend(backend).generate(None, [], 0)
            self.assertTrue(backend.stopped)
        good = FakeBackend(dict(input_tokens=0, output_tokens=3))
        self.assertEqual(smoke.UsageRequiredBackend(good).generate(None, [], 0), 'valid typed result')

    def test_async_committee_failure_stops_queued_sibling_physical_attempts(self):
        from closed_loop.fixtures import request
        from closed_loop.native_support import ArgumentCritique, HumanMessage, NativeBinding, get_llm

        async def exercise(failure):
            req = request(concurrency=1)
            budget = smoke.CallBudget(req)
            class FailingBackend:
                def __init__(self):
                    self.call_budget = budget
                    self.attempts = []
                def generate(self, *args):
                    # This is the physical-dispatch seam, equivalent to the
                    # metered live backend's shared-budget check/reservation.
                    budget.check()
                    with budget.reserve('model'):
                        self.attempts.append(dict(status='DISPATCHED'))
                        raise failure
            backend = FailingBackend()
            view = SimpleNamespace(company_id=req.company.company_id, mandate=req.mandate,
                                   as_of=req.as_of.isoformat(), fact_revision=0,
                                   argument_revision=0, qa_pairs=())
            binding = NativeBinding(smoke.UsageRequiredBackend(backend), budget, view)
            with binding.activate():
                model = get_llm(temperature=0).with_structured_output(ArgumentCritique)
                outcomes = await asyncio.gather(
                    *(model.ainvoke([HumanMessage('synthetic sibling')]) for _ in range(3)),
                    return_exceptions=True)
            self.assertTrue(all(isinstance(outcome, smoke.BudgetStopped) for outcome in outcomes))
            self.assertEqual(len(backend.attempts), 1)
            self.assertEqual(budget.used['model'], 1)
            self.assertTrue(budget.stopped)
            self.assertEqual(budget.active, 0)
            self.assertTrue(all(str(outcome) == 'STOP_OR_DEADLINE' for outcome in outcomes[1:]))

        for failure in [smoke.BudgetStopped('API_PROVIDER_ERROR'),
                        smoke.BudgetStopped('API_ACCOUNTING_BOUND_BREACH'),
                        smoke.BudgetStopped('API_INVALID_STRUCTURED_OUTPUT'),
                        RuntimeError('unexpected backend failure')]:
            with self.subTest(failure=str(failure)):
                asyncio.run(exercise(failure))

    def test_async_semantic_validation_stops_siblings_after_valid_usage(self):
        from closed_loop.fixtures import request
        from closed_loop.native_support import (ArgumentCritique, ArgumentOutput, ArgumentsOutput,
                                                HumanMessage, NativeBinding, get_llm)

        async def exercise(schema, response, expected_reason):
            req = request(concurrency=1)
            budget = smoke.CallBudget(req)
            class TypedBackend:
                def __init__(self):
                    self.call_budget = budget
                    self.attempts = []
                def generate(self, *args):
                    budget.check()
                    with budget.reserve('model'):
                        self.attempts.append(dict(status='SUCCEEDED', input_tokens=10, output_tokens=5))
                        return response
            backend = TypedBackend()
            view = SimpleNamespace(company_id=req.company.company_id, mandate=req.mandate,
                                   as_of=req.as_of.isoformat(), fact_revision=0,
                                   argument_revision=0, qa_pairs=())
            binding = NativeBinding(smoke.UsageRequiredBackend(backend), budget, view)
            with binding.activate():
                model = get_llm(temperature=0).with_structured_output(schema)
                outcomes = await asyncio.gather(
                    *(model.ainvoke([HumanMessage('synthetic sibling')]) for _ in range(3)),
                    return_exceptions=True)
            self.assertEqual(str(outcomes[0]), expected_reason)
            self.assertTrue(all(str(outcome) == 'STOP_OR_DEADLINE' for outcome in outcomes[1:]))
            self.assertEqual(len(backend.attempts), 1)
            self.assertEqual(budget.used['model'], 1)
            self.assertTrue(budget.stopped)
            self.assertEqual(budget.active, 0)

        for schema, response, reason in [
                (ArgumentCritique, ArgumentCritique(''), 'EMPTY_CRITIQUE'),
                (ArgumentsOutput, ArgumentsOutput([ArgumentOutput('typed content', [42])]), 'INVALID_QA_CITATION')]:
            with self.subTest(reason=reason):
                asyncio.run(exercise(schema, response, reason))

    def test_ordinary_backend_validation_failure_keeps_existing_budget_policy(self):
        from closed_loop.fixtures import request
        from closed_loop.native_support import ArgumentCritique, HumanMessage, NativeBinding, get_llm
        req = request()
        budget = smoke.CallBudget(req)
        backend = SimpleNamespace(generate=lambda *args: ArgumentCritique(''))
        view = SimpleNamespace(company_id=req.company.company_id, mandate=req.mandate,
                               as_of=req.as_of.isoformat(), fact_revision=0,
                               argument_revision=0, qa_pairs=())
        binding = NativeBinding(backend, budget, view)
        with binding.activate():
            model = get_llm(temperature=0).with_structured_output(ArgumentCritique)
            with self.assertRaisesRegex(smoke.BudgetStopped, 'EMPTY_CRITIQUE'):
                model.invoke([HumanMessage('synthetic')])
            self.assertFalse(budget.stopped)
            backend.generate = lambda *args: ArgumentCritique('valid later fixture')
            self.assertEqual(model.invoke([HumanMessage('synthetic')]).critique, 'valid later fixture')

    def test_seed_hash_excludes_cohort_modern_or_outcome_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'cohort.csv'
            source.write_text('Company Name,Company Website,funding_total,outcome\n'
                              'Abel,https://www.tryabel.com,9000,success\n'
                              'Adagy Robotics,https://www.adagyrobotics.com,99999999,success\n')
            before = smoke.prepare_plan(source)
            source.write_text(source.read_text().replace('99999999,success', '0,failure'))
            after = smoke.prepare_plan(source)
            self.assertEqual(before['input_seed_sha256'], after['input_seed_sha256'])
            self.assertEqual(set(before['company']), {'company_id', 'name', 'domain'})
            self.assertNotEqual(before['cohort_sha256'], after['cohort_sha256'])

    def test_injected_live_assembly_shares_budget_saves_outputs_and_seals_once(self):
        events = []
        backend_holder = []
        def backend_factory(**kwargs):
            envelope = SimpleNamespace(
                snapshot=lambda: {'actual_invoice_known': False},
                seal_completed=lambda: events.append('sealed'),
                close=lambda: events.append('closed'))
            backend = SimpleNamespace(call_budget=kwargs['call_budget'], attempts=[], envelope=envelope)
            backend_holder.append(backend)
            self.assertEqual(kwargs['pilot_id'], smoke.PILOT_ID)
            self.assertEqual(kwargs['journal_path'], smoke.LIVE_DIR / 'api_budget.jsonl')
            return backend
        def runtime_factory(request, gateway, budget, lead, committee, provider):
            from closed_loop.research_backend import MeteredResearchProvider
            self.assertIsInstance(provider, MeteredResearchProvider)
            self.assertIs(provider.backend, lead.backend)
            self.assertIs(provider.backend, committee.backend)
            self.assertIs(provider.call_budget, budget)
            self.assertIs(provider.archive_provider.call_budget, budget)
            self.assertEqual(request.max_model_calls, 24)
            self.assertEqual(request.max_search_calls, 6)
            self.assertLessEqual((request.deadline - smoke.datetime.now(smoke.timezone.utc)).total_seconds(), 480)
            return SimpleNamespace(run=lambda: dict(decision='MORE_DILIGENCE', stop_reason='FIXTURE_ONLY'))
        with tempfile.TemporaryDirectory() as folder, patch.object(smoke, 'LIVE_DIR', Path(folder)), \
                patch.object(smoke, 'create_live_backend', side_effect=backend_factory), \
                patch.object(smoke, 'ClosedLoopRuntime', side_effect=runtime_factory):
            plan = smoke.prepare_plan()
            result = smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])
            self.assertEqual(result['actual_api_request_attempts'], 0)
            self.assertEqual(result['archive_http_requests'], 0)
            self.assertEqual(json.loads((Path(folder) / 'result.json').read_text())['stop_reason'], 'FIXTURE_ONLY')
        self.assertEqual(events, ['sealed', 'closed'])
        self.assertEqual(len(backend_holder), 1)

    def test_setup_failure_saves_redacted_failure_without_retries(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(smoke, 'LIVE_DIR', Path(folder)), \
                patch.object(smoke, 'create_live_backend', side_effect=RuntimeError('SECRET_MUST_NOT_BE_SAVED')) as factory:
            plan = smoke.prepare_plan()
            result = smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])
            saved = (Path(folder) / result['output_file']).read_text()
            self.assertNotIn('SECRET', saved)
            self.assertEqual(result['actual_api_request_attempts'], 0)
            self.assertEqual(result['status'], 'NOT_RUN_BACKEND_SETUP_FAILED')
            self.assertEqual(factory.call_count, 1)

    def test_sealed_or_leased_prior_result_is_preserved_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(smoke, 'LIVE_DIR', Path(folder)):
            prior_path = Path(folder) / 'result.json'
            prior_bytes = b'{"status":"ONE_COMPANY_SMOKE_NOT_A_BACKTEST","preserve":"prior artifact"}\n'
            prior_path.write_bytes(prior_bytes)
            failure_paths = []
            for reason in ['API_PILOT_ALREADY_COMPLETED', 'API_PILOT_LEASE_ALREADY_HELD']:
                with patch.object(smoke, 'create_live_backend', side_effect=smoke.BudgetStopped(reason)):
                    plan = smoke.prepare_plan()
                    result = smoke.run_live(plan, limit='0.20', approved_plan_sha256=plan['plan_sha256'])
                    failure_paths.append(result['output_file'])
                    self.assertEqual(prior_path.read_bytes(), prior_bytes)
                    self.assertEqual(result['actual_api_request_attempts'], 0)
                    self.assertTrue((Path(folder) / result['output_file']).exists())
            self.assertEqual(len(set(failure_paths)), 2)


if __name__ == '__main__':
    unittest.main()
