"""Finite handoff persistence tests; all model workers injected."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from workflow_automation import controller as c


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.calls = []; self.clock = [1000]
        self.sources = {'controller': 'v1'}
        self.patcher = patch.object(c, 'source_identity', side_effect=lambda root: self.sources.copy())
        self.patcher.start(); self.addCleanup(self.patcher.stop)

    def worker(self, role, root, directory, draft, timeout):
        self.calls.append(role)
        self.assertGreater(timeout, 0)
        if role == 'claude': self.assertTrue(draft)
        return {'status': 'OK', 'text': 'draft rubric' if role == 'codex' else
                json.dumps({'verdict': 'ACCEPT', 'summary': 'OK', 'findings': []})}

    def run_it(self, **kwargs):
        return c.run('case', root=self.root, output=self.root/'runs', now=lambda:self.clock[0],
                     worker=kwargs.pop('worker', self.worker), **kwargs)

    def load(self):
        return json.loads((self.root/'runs/case/receipt.json').read_text())

    def save(self, s): c.save(self.root/'runs/case/receipt.json',s)

    def test_dry_run_never_invokes_models(self):
        s=self.run_it(); self.assertEqual(s['attempts'],0); self.assertEqual(self.calls,[])

    def test_real_adapter_not_called_by_default(self):
        with patch.object(c,'execute_process',side_effect=AssertionError('must not launch')):
            self.assertEqual(self.run_it()['status'],'READY')

    def test_handoff_and_completed_resume(self):
        s=self.run_it(live=True); self.assertEqual(s['status'],'DONE')
        self.assertEqual(self.calls,['codex','claude']); self.assertEqual(s['attempts'],2)
        self.run_it(live=True,resume=True); self.assertEqual(len(self.calls),2)
        self.assertFalse(s['writeback_verified'])

    def test_existing_without_resume_refuses(self):
        self.run_it()
        with self.assertRaisesRegex(ValueError,'Run exists'): self.run_it()

    def test_source_change_refuses_resume(self):
        self.run_it(); self.sources['controller']='changed'
        with self.assertRaisesRegex(ValueError,'mismatch'):self.run_it(resume=True,live=True)
        self.assertEqual(self.calls,[])

    def test_live_mode_cannot_repurpose_dry_run(self):
        self.run_it()
        with self.assertRaisesRegex(ValueError,'mismatch'): self.run_it(live=True,resume=True)

    def test_saved_artifact_tamper_refused(self):
        self.run_it(live=True); (self.root/'runs/case/codex.md').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'tampered'):self.run_it(live=True,resume=True)

    def test_preexisting_lease_refused(self):
        folder=self.root/'runs/case';folder.mkdir(parents=True);(folder/'.run.lock').write_text('owner')
        with self.assertRaises(FileExistsError): self.run_it(live=True)
        self.assertEqual(self.calls,[])

    def test_stop_before_first_call(self):
        stop=self.root/'STOP';stop.touch()
        self.assertEqual(self.run_it(live=True,stop_file=stop)['status'],'STOPPED')
        self.assertEqual(self.calls,[])

    def test_stop_between_workers(self):
        stop=self.root/'STOP'
        def work(*args):
            v=self.worker(*args);stop.touch();return v
        s=self.run_it(live=True,stop_file=stop,worker=work)
        self.assertEqual(s['status'],'STOPPED');self.assertEqual(self.calls,['codex'])

    def test_deadline_not_reset_on_resume(self):
        def crash(*args):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_it(live=True,worker=crash)
        s=self.load();deadline=s['deadline_epoch'];s['status']='READY';self.save(s)
        self.clock[0]=deadline+1
        r=self.run_it(live=True,resume=True)
        self.assertEqual(r['deadline_epoch'],deadline);self.assertEqual(r['status'],'STOPPED')
        self.assertEqual(r['attempts'],1)

    def test_crash_after_intent_not_redispatched(self):
        def crash(*args):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_it(live=True,worker=crash)
        s=self.run_it(live=True,resume=True)
        self.assertEqual(s['status'],'BLOCKED');self.assertEqual(s['attempts'],1)
        self.assertEqual(self.calls,[])

    def test_clean_checkpoint_resumes_only_review(self):
        original=c.save
        def save_then_crash(path,value):
            original(path,value)
            if value['status']=='REVIEW':raise KeyboardInterrupt()
        with patch.object(c,'save',side_effect=save_then_crash):
            with self.assertRaises(KeyboardInterrupt):self.run_it(live=True)
        self.assertEqual(self.run_it(live=True,resume=True)['status'],'DONE')
        self.assertEqual(self.calls,['codex','claude'])

    def test_quota_has_no_automatic_retry(self):
        def quota(*args):return {'status':'WAITING_QUOTA','reason':'provider quota','text':''}
        s=self.run_it(live=True,worker=quota)
        self.assertEqual(s['status'],'WAITING_QUOTA');self.assertEqual(s['attempts'],1)
        self.assertEqual(self.run_it(live=True,resume=True)['attempts'],1)

    def test_failed_worker_stops_and_preserves_intent(self):
        def bad(*args): raise RuntimeError('failure')
        s=self.run_it(live=True,worker=bad)
        self.assertEqual(s['status'],'BLOCKED');self.assertEqual(s['attempts'],1)
        self.assertEqual(len(s['events']),1)

    def test_malformed_review_blocks(self):
        def bad(*args):
            v=self.worker(*args)
            if args[0]=='claude':v['text']='not json'
            return v
        self.assertEqual(self.run_it(live=True,worker=bad)['reason'],'MALFORMED_WORKER_RESULT')

    def test_revise_does_not_start_another_model_loop(self):
        def revise(*args):
            v=self.worker(*args)
            if args[0]=='claude':v['text']=json.dumps({'verdict':'REVISE','summary':'needs correction','findings':['issue']})
            return v
        s=self.run_it(live=True,worker=revise)
        self.assertEqual(s['status'],'BLOCKED');self.assertEqual(s['attempts'],2)

    def test_global_cap_persists(self):
        def crash(*args):raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):self.run_it(live=True,worker=crash)
        s=self.load();s['status']='READY';s['attempts']=2;s['events'].append({'role':'claude','attempt':2});self.save(s)
        self.assertEqual(self.run_it(live=True,resume=True)['status'],'STOPPED')
        self.assertEqual(self.calls,[])

    def test_wrong_run_identity_refused(self):
        self.run_it();s=self.load();s['run_id']='other';self.save(s)
        with self.assertRaisesRegex(ValueError,'mismatch'):self.run_it(resume=True)

    def test_quota_word_in_successful_draft_not_quota(self):
        def work(*args):
            v=self.worker(*args)
            if args[0]=='codex':v['text']='how to handle quota and rate limits'
            return v
        self.assertEqual(self.run_it(live=True,worker=work)['status'],'DONE')

    def test_review_with_unresolved_findings_cannot_accept(self):
        with self.assertRaises(ValueError):
            c.validate_review(json.dumps({'verdict':'ACCEPT','summary':'ok','findings':['issue']}))

    def test_source_changes_between_workers_block_review(self):
        def work(*args):
            result=self.worker(*args);self.sources['controller']='changed';return result
        self.assertEqual(self.run_it(live=True,worker=work)['reason'],'SOURCE_CHANGED_DURING_RUN')
        self.assertEqual(self.calls,['codex'])

    def test_persisted_budget_inconsistency_refused(self):
        self.run_it();s=self.load();s['attempts']=1;self.save(s)
        with self.assertRaisesRegex(ValueError,'budget'):self.run_it(resume=True)

    def test_process_timeout_kills_actual_child(self):
        code,out,err=c.execute_process([sys.executable,'-c','import time;time.sleep(30)'],self.root,0.2)
        self.assertEqual(code,124)


if __name__=='__main__':unittest.main()
