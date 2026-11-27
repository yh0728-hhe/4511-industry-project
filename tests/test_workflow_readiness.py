"""Readiness runner persistence/failure tests: fake commands, no network or model."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from workflow_automation import readiness as w


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.calls = []
        self.fingerprint = 'source-v1'
        self.plan_patch = patch.object(w, 'plan', side_effect=lambda root: {'fingerprint': self.fingerprint})
        self.assessment_patch = patch.object(w, 'training_assessment', return_value={'supervised_training_ready': False})
        self.plan_patch.start(); self.assessment_patch.start()
        self.addCleanup(self.plan_patch.stop); self.addCleanup(self.assessment_patch.stop)
        self.catalog = [('one', ['fake-one'], []), ('two', ['fake-two'], [])]

    def good(self, command, root, timeout):
        self.calls.append(command)
        self.assertGreater(timeout, 0)
        return 0, b'offline checked'

    def run_workflow(self, **kw):
        return w.run('case', output=self.folder, executor=self.good, catalog=self.catalog, **kw)

    def test_completed_run_resume_does_not_dispatch_again(self):
        result = self.run_workflow()
        self.assertEqual(result['status'], 'OFFLINE_CHECKS_PASSED_LIVE_AND_TRAINING_NOT_RUN')
        self.assertEqual(len(self.calls), 2)
        self.run_workflow(resume=True)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result['paid_api_calls'], 0)
        self.assertFalse(result['training_run'])

    def test_existing_run_is_preserved_without_resume(self):
        self.run_workflow()
        before = (self.folder/'case/receipt.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Run exists'):
            self.run_workflow()
        self.assertEqual(before, (self.folder/'case/receipt.json').read_bytes())
        self.assertEqual(len(self.calls), 2)

    def test_copied_receipt_cannot_misattribute_a_different_run(self):
        import shutil
        self.run_workflow()
        shutil.copytree(self.folder/'case',self.folder/'other-case')
        with self.assertRaisesRegex(ValueError, 'identity/mode mismatch'):
            w.run('other-case',output=self.folder,executor=self.good,catalog=self.catalog,resume=True)
        self.assertEqual(len(self.calls),2)

    def test_failed_exit_keeps_exit_code_even_if_expected_output_was_not_created(self):
        result=w.run('case',output=self.folder,executor=lambda *args:(7,b'failure'),
                     catalog=[('one',['fake'],['not-created.json'])])
        self.assertEqual(result['status'],'STOPPED_STEP_FAILED')
        self.assertEqual(result['steps']['one']['exit_code'],7)
        self.assertIn('one.log',result['steps']['one']['sha256'])

    def test_changed_source_refuses_resume(self):
        self.run_workflow(); self.fingerprint = 'source-v2'
        with self.assertRaisesRegex(ValueError, 'Source inputs changed'):
            self.run_workflow(resume=True)
        self.assertEqual(len(self.calls), 2)

    def test_tampered_log_refuses_resume(self):
        self.run_workflow()
        (self.folder/'case/one.log').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            self.run_workflow(resume=True)

    def test_tampered_plan_refuses_resume(self):
        self.run_workflow()
        (self.folder/'case/plan.json').write_text('{}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Saved plan changed'):
            self.run_workflow(resume=True)

    def test_failed_step_stops_next_stage_and_can_resume(self):
        calls = []
        def failing(command, root, timeout):
            calls.append(command)
            return (1 if command == ['fake-two'] else 0), b'failure'
        result = w.run('case', output=self.folder, executor=failing, catalog=self.catalog + [('third', ['never'], [])])
        self.assertEqual(result['status'], 'STOPPED_STEP_FAILED')
        self.assertEqual(len(calls), 2)
        self.run_workflow(resume=True)
        self.assertEqual(self.calls, [['fake-two']])

    def test_timeout_stops_next_stage_and_saves_receipt(self):
        def timeout(*args):
            raise subprocess.TimeoutExpired('fake-one', 1)
        result = w.run('case', output=self.folder, executor=timeout, catalog=self.catalog)
        self.assertEqual(result['status'], 'STOPPED_DEADLINE')
        self.assertEqual(list(result['steps']), ['one'])
        self.assertTrue((self.folder/'case/receipt.json').is_file())

    def test_missing_artifact_is_failure(self):
        result = w.run('case', output=self.folder, executor=self.good, catalog=[('one', ['fake'], ['missing.json'])])
        self.assertEqual(result['status'], 'STOPPED_STAGE_ERROR')
        self.assertEqual(result['steps']['one']['error_type'], 'FileNotFoundError')

    def test_lock_refuses_concurrent_run(self):
        target=self.folder/'case'; target.mkdir()
        with w.lease(target), self.assertRaises(FileExistsError):
            self.run_workflow()
        self.assertFalse((target/'.run.lock').exists())

    def test_bad_ids_and_deadlines_are_rejected(self):
        for name in ['../escape', '/absolute', 'a/b', '', 'a'*65]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                w.run(name, output=self.folder)
        for value in [0, True, 1801]:
            with self.assertRaises(ValueError):
                self.run_workflow(max_seconds=value)

    def test_actual_child_timeout_saves_checkpoint_and_stops(self):
        import sys
        result=w.run('case',output=self.folder,max_seconds=1,
                     catalog=[('slow',[sys.executable,'-c','import time;time.sleep(10)'],[])])
        self.assertEqual(result['status'],'STOPPED_DEADLINE')
        self.assertEqual(result['steps']['slow']['status'],'TIMED_OUT')
        self.assertFalse((self.folder/'case/.run.lock').exists())

    def test_cli_reports_lock_refusal_without_starting_work(self):
        from contextlib import redirect_stdout
        import io
        output=io.StringIO()
        with patch.object(w,'run',side_effect=FileExistsError),redirect_stdout(output):
            code=w.main(['--run-id','case'])
        self.assertEqual(code,2)
        self.assertEqual(json.loads(output.getvalue())['status'],'REFUSED_RUN_LOCK_HELD')

    def test_resume_requires_existing_receipt(self):
        with self.assertRaisesRegex(ValueError, 'missing receipt'):
            self.run_workflow(resume=True)

    def test_assessment_failure_never_reports_ready(self):
        with patch.object(w, 'training_assessment', side_effect=ValueError('bad labels')):
            result=self.run_workflow()
        self.assertEqual(result['status'], 'STOPPED_ASSESSMENT_ERROR')

    def test_real_assessment_keeps_unknown_separate_and_blocks_training(self):
        self.assessment_patch.stop()
        result=w.training_assessment()
        self.assertEqual(result['cohort'], 240)
        self.assertEqual(result['verified_financing_negatives'], 0)
        self.assertFalse(result['supervised_training_ready'])
        self.assertIn('UNKNOWN is not zero', result['rule'])

    def test_fixed_catalog_contains_no_paid_flags_or_live_entrypoints(self):
        jobs=w.steps(w.ROOT,self.folder)
        self.assertEqual(len(jobs),6)
        commands=' '.join(' '.join(x[1]) for x in jobs)
        self.assertNotIn('--approve-api-usd',commands)
        self.assertNotIn('--env-file',commands)
        self.assertNotIn('archive_smoke.py',commands)
        self.assertIn('--plan-output',commands)


if __name__=='__main__': unittest.main()
