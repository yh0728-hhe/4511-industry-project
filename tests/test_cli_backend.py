"""Fake executor only. Never shell out to a real Claude Code CLI process."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
import json
import subprocess
import sys
import time
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget,BudgetStopped
from closed_loop.native_support import NativeBinding, ArgumentCritique, HumanMessage
from closed_loop.cli_backend import ClaudeCliBackend, ProcessExecutor


def envelope(**overrides):
    body=dict(is_error=False,structured_output={'critique':'fixture critique'})
    body.update(overrides)
    return json.dumps(body).encode('utf-8')


class FakeExecutor:
    def __init__(self,outputs=None,fail=False,returncode=0):
        self.calls=[];self.fail=fail;self.returncode=returncode
        self.outputs=list(outputs) if outputs is not None else [envelope()]
    def run(self,argv,stdin_bytes,timeout_seconds):
        self.calls.append((argv,stdin_bytes,timeout_seconds))
        if self.fail:raise RuntimeError('SECRET_PROVIDER_DETAIL_SHOULD_NOT_BE_ECHOED')
        out=self.outputs.pop(0) if len(self.outputs)>1 else self.outputs[0]
        return self.returncode,out,b''


class SteppedClock:
    """Returns `before` for the first `switch_at`-1 calls, then `after`."""
    def __init__(self,switch_at,before,after):
        self.count=0;self.switch_at=switch_at;self.before=before;self.after=after
    def __call__(self):
        self.count+=1
        return self.before if self.count<self.switch_at else self.after


def setup(executor=None,journal=None,model_calls=5,max_process_count=5,**kwargs):
    req=request(max_model_calls=model_calls)
    budget=CallBudget(req)
    executor=executor or FakeExecutor()
    journal=journal or Path(mkdtemp())/'journal.jsonl'
    backend=ClaudeCliBackend(approved=True,executable_path='claude',model_id='claude-fixture-model',
        call_budget=budget,max_process_count=max_process_count,journal_path=journal,executor=executor,**kwargs)
    return backend,executor,budget,journal


class CliBackendTests(unittest.TestCase):
    def test_process_failure_journal_has_sanitized_type_only(self):
        backend,executor,budget,journal=setup(executor=FakeExecutor(fail=True))
        with self.assertRaises(BudgetStopped):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        text=journal.read_text()
        self.assertNotIn('SECRET_PROVIDER_DETAIL',text)
        record=json.loads(text.splitlines()[-1])
        self.assertEqual(record['error_type'],'RuntimeError')

    def test_import_and_construction_dispatch_nothing(self):
        backend,executor,budget,_=setup()
        self.assertEqual(executor.calls,[]);self.assertEqual(budget.used['model'],0)

    def test_no_approval_refuses_before_anything_else(self):
        with self.assertRaises(PermissionError):
            ClaudeCliBackend(approved=False,executable_path='claude',model_id='m',
                call_budget=CallBudget(request()),max_process_count=1,journal_path='unused.jsonl')

    def test_typed_success_via_structured_output(self):
        backend,executor,budget,_=setup()
        value=backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(value.critique,'fixture critique')
        self.assertEqual(budget.used['model'],1)
        argv=executor.calls[0][0]
        self.assertIn('--json-schema',argv);self.assertIn('--model',argv);self.assertEqual(argv[-1],'-p')
        stdin_bytes=executor.calls[0][1]
        self.assertIn(b'fixture',stdin_bytes)

    def test_typed_success_via_strict_json_result_string(self):
        backend,executor,_,_=setup(FakeExecutor(outputs=[envelope(structured_output=None,
            result=json.dumps({'critique':'string result critique'}))]))
        value=backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(value.critique,'string result critique')

    def test_native_binding_single_reservation_not_doubled(self):
        backend,executor,budget,_=setup()
        view=type('View',(),dict(as_of=request().as_of.isoformat(),qa_pairs=[],company_id='SYNTHETIC_COMPANY',
            mandate='m',fact_revision=0,argument_revision=0))()
        binding=NativeBinding(backend,budget,view)
        binding.backend.stop_on_validation_error=False
        with binding.activate():
            from closed_loop.native_support import get_llm
            model=get_llm().with_structured_output(ArgumentCritique)
            model.invoke([HumanMessage('fixture')])
        self.assertEqual(budget.used['model'],1)

    def test_process_count_cap_stops_before_executor(self):
        backend,executor,budget,_=setup(max_process_count=1)
        backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        with self.assertRaisesRegex(BudgetStopped,'CLI_PROCESS_CAP'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(executor.calls),1)

    def test_deadline_stops_before_executor(self):
        req=request(max_model_calls=5,deadline=request().as_of)
        budget=CallBudget(req)
        with TemporaryDirectory() as folder:
            backend=ClaudeCliBackend(approved=True,executable_path='claude',model_id='m',call_budget=budget,
                max_process_count=5,journal_path=Path(folder)/'j.jsonl',executor=FakeExecutor())
            with self.assertRaises(BudgetStopped):backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
            self.assertEqual(backend.executor.calls,[])

    def test_failed_call_consumes_attempt_no_retry(self):
        backend,executor,budget,_=setup(FakeExecutor(fail=True))
        with self.assertRaises(BudgetStopped) as caught:
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertNotIn('SECRET',str(caught.exception))
        self.assertEqual(budget.used['model'],1);self.assertEqual(len(executor.calls),1)

    def test_malformed_result_is_terminal(self):
        backend,*_=setup(FakeExecutor(outputs=[b'not json']))
        with self.assertRaisesRegex(BudgetStopped,'CLI_MALFORMED_RESULT'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)

    def test_genuine_quota_error_stops_with_quota_code(self):
        backend,*_=setup(FakeExecutor(outputs=[envelope(is_error=True,subtype='error_quota_exceeded',
            structured_output=None)]))
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)

    def test_successful_answer_mentioning_quota_is_not_a_quota_error(self):
        backend,*_=setup(FakeExecutor(outputs=[envelope(structured_output={'critique':'quota looks fine this quarter'})]))
        value=backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertIn('quota',value.critique)

    def test_prior_journal_cannot_be_reset(self):
        with TemporaryDirectory() as folder:
            journal=Path(folder)/'journal.jsonl'
            setup(journal=journal)
            with self.assertRaisesRegex(BudgetStopped,'CLI_JOURNAL_ALREADY_EXISTS'):
                setup(journal=journal)

    def test_oversized_prompt_never_dispatches(self):
        backend,executor,budget,_=setup(max_input_bytes=16)
        with self.assertRaises(BudgetStopped):
            backend.generate(ArgumentCritique,[HumanMessage('x'*1000)],0)
        self.assertEqual(executor.calls,[]);self.assertEqual(budget.used['model'],0)

    def test_no_raw_exception_or_secret_leaks_into_errors(self):
        backend,executor,_,_=setup(FakeExecutor(fail=True))
        try:backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        except BudgetStopped as exc:
            self.assertNotIn('SECRET',str(exc));self.assertNotIn('Traceback',str(exc))

    def test_argv_tools_field_is_actual_empty_string(self):
        backend,executor,_,_=setup()
        backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        argv=executor.calls[0][0]
        self.assertEqual(argv[argv.index('--tools')+1],'')

    def test_nonzero_returncode_rejected_even_with_success_looking_stdout(self):
        backend,executor,budget,_=setup(FakeExecutor(returncode=1))
        with self.assertRaisesRegex(BudgetStopped,'CLI_NONZERO_RETURNCODE'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(budget.used['model'],1)

    def test_quota_text_without_special_subtype_still_detected(self):
        backend,*_=setup(FakeExecutor(outputs=[envelope(is_error=True,subtype='error_other',
            structured_output=None,result='Usage limit reached for this billing period')]))
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)

    def test_repeated_generate_after_failure_dispatches_zero_new_calls(self):
        backend,executor,budget,_=setup(FakeExecutor(fail=True))
        with self.assertRaises(BudgetStopped):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(executor.calls),1)
        with self.assertRaises(BudgetStopped):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(executor.calls),1)

    def test_journal_write_failure_before_executor_dispatches_nothing(self):
        backend,executor,budget,_=setup()
        backend.journal_path=Path(mkdtemp())
        with self.assertRaisesRegex(BudgetStopped,'CLI_JOURNAL_WRITE_FAILED'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(executor.calls,[])

    def test_expired_cached_budget_stops_before_executor(self):
        start=datetime(2030,1,1,tzinfo=timezone.utc)
        before=start
        after=start+timedelta(seconds=100)
        deadline=start+timedelta(seconds=50)
        req=request(max_model_calls=5,deadline=deadline)
        clock=SteppedClock(switch_at=3,before=before,after=after)
        budget=CallBudget(req,clock=clock)
        with TemporaryDirectory() as folder:
            executor=FakeExecutor()
            backend=ClaudeCliBackend(approved=True,executable_path='claude',model_id='m',call_budget=budget,
                max_process_count=5,journal_path=Path(folder)/'j.jsonl',executor=executor)
            with self.assertRaises(BudgetStopped):
                backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
            self.assertEqual(executor.calls,[])
            self.assertEqual(budget.used['model'],1)

    def test_actual_token_usage_recorded_when_present(self):
        backend,executor,budget,journal=setup(FakeExecutor(outputs=[envelope(
            usage={'input_tokens':5,'output_tokens':7})]))
        backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        last=json.loads(journal.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(last['actual_usage'],{'input_tokens':5,'output_tokens':7})

    def test_actual_token_usage_unknown_when_absent(self):
        backend,executor,budget,journal=setup()
        backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        last=json.loads(journal.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(last['actual_usage'],'UNKNOWN')


class ProcessExecutorChildTimeoutTests(unittest.TestCase):
    """Real sleeping Python CHILD process only; never a model subprocess."""
    def test_nonpositive_timeout_refused_before_popen(self):
        executor=ProcessExecutor()
        with self.assertRaises(ValueError):
            executor.run([sys.executable,'-c','pass'],b'',0)

    def test_real_child_process_timeout_is_killed_and_reaped(self):
        executor=ProcessExecutor()
        argv=[sys.executable,'-c','import time;time.sleep(30)']
        start=time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            executor.run(argv,b'',1)
        self.assertLess(time.monotonic()-start,15)

    def test_cleanup_failure_preserves_original_timeout_and_partial_bytes(self):
        from unittest.mock import patch,MagicMock
        original=subprocess.TimeoutExpired('fixture',1,output=b'partial',stderr=b'err')
        proc=MagicMock();proc.communicate.side_effect=original
        executor=ProcessExecutor()
        with patch('closed_loop.cli_backend.subprocess.Popen',return_value=proc),patch.object(executor,'_kill_own_group',side_effect=OSError('PRIVATE_CLEANUP_DETAIL')):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                executor.run(['fixture'],b'',1)
        self.assertIs(caught.exception,original)
        self.assertEqual(caught.exception.output,b'partial')
        self.assertEqual(caught.exception.cleanup_error_type,'OSError')

    def test_real_child_timeout_preserves_drained_stdout_and_stderr(self):
        executor=ProcessExecutor()
        argv=[sys.executable,'-c',
            "import sys,time;sys.stdout.write('PARTIAL_OUT');sys.stdout.flush();"
            "sys.stderr.write('PARTIAL_ERR');sys.stderr.flush();time.sleep(30)"]
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            executor.run(argv,b'',1)
        self.assertEqual(caught.exception.output,b'PARTIAL_OUT')
        self.assertEqual(caught.exception.stderr,b'PARTIAL_ERR')

class ReviewerChecks(unittest.TestCase):
    def test_timeout_classified_distinctly_sanitized_single_attempt(self):
        class TimeoutExecutor(FakeExecutor):
            def run(self,argv,stdin_bytes,timeout_seconds):
                self.calls.append((argv,stdin_bytes,timeout_seconds))
                raise subprocess.TimeoutExpired(cmd='claude',timeout=timeout_seconds,
                    output=b'SECRET_PARTIAL_OUT',stderr=b'SECRET_PARTIAL_ERR')
        backend,executor,budget,journal=setup(TimeoutExecutor())
        with self.assertRaisesRegex(BudgetStopped,'CLI_PROCESS_TIMEOUT'):
            backend.generate(ArgumentCritique,[HumanMessage('x')],0)
        self.assertEqual(budget.stop_reason,'CLI_PROCESS_TIMEOUT')
        self.assertEqual(len(executor.calls),1)
        text=journal.read_text(encoding='utf-8')
        self.assertNotIn('SECRET_PARTIAL',text)
        record=json.loads(text.splitlines()[-1])
        self.assertEqual(record['error_type'],'TimeoutExpired')
        self.assertEqual(record['status'],'PROCESS_TIMEOUT')

    def test_generic_process_error_keeps_no_invented_output(self):
        backend,executor,budget,journal=setup(FakeExecutor(fail=True))
        with self.assertRaisesRegex(BudgetStopped,'CLI_PROCESS_FAILED'):
            backend.generate(ArgumentCritique,[HumanMessage('x')],0)
        self.assertEqual(budget.stop_reason,'CLI_PROCESS_FAILED')
        record=json.loads(journal.read_text(encoding='utf-8').splitlines()[-1])
        self.assertEqual(record['status'],'PROCESS_FAILED')
        self.assertNotIn('output',record)
        self.assertNotIn('stderr',record)

    def test_error_array_limit_stops_native_backend_once_without_refund(self):
        raw=json.dumps(dict(is_error=True,subtype='error_during_execution',errors=["You've hit your limit"],structured_output=None)).encode()
        backend,executor,budget,_=setup(FakeExecutor(outputs=[raw]))
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(executor.calls),1)
        self.assertEqual(budget.used['model'],1)
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):
            backend.generate(ArgumentCritique,[HumanMessage('fixture')],0)
        self.assertEqual(len(executor.calls),1)

    def test_nonzero_quota_keeps_specific_cause(self):
        class ExitQuota(FakeExecutor):
            def run(self,*args):return 1,envelope(is_error=True,result='usage limit reached',structured_output=None),b''
        backend,executor,budget,_=setup(ExitQuota())
        with self.assertRaisesRegex(BudgetStopped,'CLI_QUOTA_EXHAUSTED'):
            backend.generate(ArgumentCritique,[HumanMessage('x')],0)
        self.assertEqual(budget.stop_reason,'CLI_QUOTA_EXHAUSTED')

    def test_usage_filters_unexpected_fields_without_logging_them(self):
        from closed_loop.cli_backend import ClaudeCliBackend
        actual=ClaudeCliBackend._usage_from_envelope({'usage':{'input_tokens':2,'output_tokens':3,'nested':{'SECRET':4}}})
        self.assertEqual(actual,{'input_tokens':2,'output_tokens':3})

    def test_success_without_completion_journal_is_terminal(self):
        from unittest.mock import patch
        backend,executor,budget,_=setup()
        actual=backend._append_journal
        def fail_completion(**event):
            if event['status']=='SUCCEEDED':raise OSError('SECRET')
            return actual(**event)
        with patch.object(backend,'_append_journal',side_effect=fail_completion):
            with self.assertRaisesRegex(BudgetStopped,'CLI_JOURNAL_WRITE_FAILED'):
                backend.generate(ArgumentCritique,[HumanMessage('x')],0)
        self.assertEqual(len(executor.calls),1)
        self.assertTrue(budget.stopped)


if __name__=='__main__':unittest.main()
