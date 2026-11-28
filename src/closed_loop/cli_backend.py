"""Explicit local Claude Code CLI backend; no SDK/key/network at import or construction.

Host CLI auth/billing belongs to the caller's environment; this class never
implies subscription billing from its name. Physical CLI process count is a
launch cap only, not the exact inner-inference/API request count or a USD cap.
"""
from pathlib import Path
from threading import Lock, TIMEOUT_MAX
import hashlib
import json
import os
import signal
import subprocess
import sys
import uuid

from .agent_prompts import CLI_RESEARCH_SYSTEM
from .cli_limits import is_quota_result_envelope
from .guards import BudgetStopped
from .openai_backend import schema_for, decode_as


class ProcessExecutor:
    """Launches one subprocess per call; owns its own timeout and process cleanup."""
    def run(self,argv,stdin_bytes,timeout_seconds):
        if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=TIMEOUT_MAX:
            raise ValueError('finite positive platform-bounded timeout required before dispatch')
        popen_kwargs=dict(stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if sys.platform=='win32':popen_kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
        else:popen_kwargs['start_new_session']=True
        proc=subprocess.Popen(argv,**popen_kwargs)
        try:
            stdout,stderr=proc.communicate(input=stdin_bytes,timeout=timeout_seconds)
        except subprocess.TimeoutExpired as timeout_exc:
            try:
                self._kill_own_group(proc)
                drained_stdout,drained_stderr=proc.communicate(timeout=5)
            except Exception as cleanup_exc:
                timeout_exc.cleanup_error_type=type(cleanup_exc).__name__
                raise timeout_exc from None
            timeout_exc.output=drained_stdout
            timeout_exc.stderr=drained_stderr
            raise timeout_exc from None
        return proc.returncode,stdout,stderr

    def _kill_own_group(self,proc):
        if sys.platform=='win32':
            subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False,timeout=15)
        else:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass


class ClaudeCliBackend:
    """Metered, explicit local Claude Code CLI backend for NativeBinding.

    Not a USD/billing meter: max_process_count only bounds physical subprocess
    launches; it is never an exact inner-inference count or dollar cap.
    """
    stop_on_validation_error=True

    def __init__(self,*,approved,executable_path,model_id,call_budget,max_process_count,journal_path,
            executor=None,per_call_timeout_seconds=60,max_input_bytes=32768):
        if approved is not True:raise PermissionError('Separate CLI usage approval required; subscription quota is not implied by this class')
        if not isinstance(executable_path,str) or not executable_path.strip():raise ValueError('explicit CLI executable path required')
        if not isinstance(model_id,str) or not model_id.strip():raise ValueError('explicit model id required')
        if type(max_process_count) is not int or max_process_count<1:raise ValueError('explicit positive process cap required')
        if type(per_call_timeout_seconds) is not int or per_call_timeout_seconds<1:raise ValueError('explicit per-call timeout required')
        if type(max_input_bytes) is not int or not 1<=max_input_bytes<=1_000_000:raise ValueError('explicit input byte cap required')
        self.call_budget=call_budget
        self.executable_path=executable_path
        self.model_id=model_id
        self.max_process_count=max_process_count
        self.process_count=0
        self.per_call_timeout_seconds=per_call_timeout_seconds
        self.max_input_bytes=max_input_bytes
        self.executor=executor if executor is not None else ProcessExecutor()
        self.journal_path=Path(journal_path)
        self._lock=Lock()
        self.journal_path.parent.mkdir(parents=True,exist_ok=True)
        try:
            with self.journal_path.open('x',encoding='utf-8'):pass
        except FileExistsError:raise BudgetStopped('CLI_JOURNAL_ALREADY_EXISTS') from None

    def _append_journal(self,**event):
        event.setdefault('actual_usage','UNKNOWN')
        with self.journal_path.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(event,sort_keys=True)+'\n')
            stream.flush()
            os.fsync(stream.fileno())

    def _safe_journal(self,**event):
        try:self._append_journal(**event)
        except Exception:pass

    @staticmethod
    def _usage_from_envelope(envelope):
        usage=envelope.get('usage')
        if not isinstance(usage,dict):return 'UNKNOWN'
        selected={k:usage[k] for k in ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens') if k in usage}
        if not {'input_tokens','output_tokens'}<=set(selected):return 'UNKNOWN'
        if any(type(v) is not int or v<0 for v in selected.values()):return 'UNKNOWN'
        return selected

    def _decode(self,schema,stdout):
        try:envelope=json.loads(stdout.decode('utf-8'))
        except (ValueError,UnicodeDecodeError):return None,'MALFORMED','UNKNOWN'
        if not isinstance(envelope,dict):return None,'MALFORMED','UNKNOWN'
        usage=self._usage_from_envelope(envelope)
        if envelope.get('is_error') is True:
            if is_quota_result_envelope(envelope):
                return None,'QUOTA_EXHAUSTED',usage
            return None,'MALFORMED',usage
        if envelope.get('is_error') is not False:return None,'MALFORMED',usage
        structured=envelope.get('structured_output')
        if structured is None:
            result=envelope.get('result')
            if isinstance(result,str):
                try:structured=json.loads(result)
                except ValueError:return None,'MALFORMED',usage
            else:structured=result
        try:value=decode_as(schema,structured)
        except (ValueError,TypeError):return None,'MALFORMED',usage
        return value,'SUCCEEDED',usage

    def generate(self,schema,messages,temperature):
        with self._lock:
            self.call_budget.check()
            if self.process_count>=self.max_process_count:raise BudgetStopped('CLI_PROCESS_CAP')
            prompt_text='\n\n'.join(f'{getattr(m,"role","user")}: {m.content}' for m in messages)
            prompt_bytes=prompt_text.encode('utf-8')
            if len(prompt_bytes)>self.max_input_bytes:raise BudgetStopped('CLI_PROMPT_BYTE_CAP')
            attempt_id=uuid.uuid4().hex
            prompt_hash=hashlib.sha256(prompt_bytes).hexdigest()
            argv=[self.executable_path,'--safe-mode','--permission-mode','dontAsk','--tools','',
                '--disable-slash-commands','--no-session-persistence','--output-format','json',
                '--system-prompt',CLI_RESEARCH_SYSTEM,
                '--json-schema',json.dumps(schema_for(schema)),'--model',self.model_id,'-p']
            with self.call_budget.reserve('model'):
                self.process_count+=1
                try:
                    self._append_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status='DISPATCHING')
                except Exception:
                    self.call_budget.stop('CLI_JOURNAL_WRITE_FAILED')
                    raise BudgetStopped('CLI_JOURNAL_WRITE_FAILED') from None
                self.call_budget.check()
                timeout=min(self.per_call_timeout_seconds,self.call_budget.remaining_seconds())
                try:
                    returncode,stdout,stderr=self.executor.run(argv,prompt_bytes,timeout)
                except subprocess.TimeoutExpired as exc:
                    self.call_budget.stop('CLI_PROCESS_TIMEOUT')
                    self._safe_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status='PROCESS_TIMEOUT',
                        error_type=type(exc).__name__)
                    raise BudgetStopped(self.call_budget.stop_reason) from None
                except Exception as exc:
                    self.call_budget.stop('CLI_PROCESS_FAILED')
                    self._safe_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status='PROCESS_FAILED',
                        error_type=type(exc).__name__)
                    raise BudgetStopped(self.call_budget.stop_reason) from None
                value,status,usage=self._decode(schema,stdout)
                if returncode!=0:
                    reason='CLI_QUOTA_EXHAUSTED' if status=='QUOTA_EXHAUSTED' else 'CLI_NONZERO_RETURNCODE'
                    self.call_budget.stop(reason)
                    self._safe_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status=reason)
                    raise BudgetStopped(reason)
                if status!='SUCCEEDED':
                    reason='CLI_QUOTA_EXHAUSTED' if status=='QUOTA_EXHAUSTED' else 'CLI_MALFORMED_RESULT'
                    self.call_budget.stop(reason)
                    self._safe_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status=status,actual_usage=usage)
                    raise BudgetStopped(reason)
                try:
                    self._append_journal(attempt_id=attempt_id,schema=schema.__name__,prompt_hash=prompt_hash,
                        model_id=self.model_id,process_count=self.process_count,status=status,actual_usage=usage)
                except Exception:
                    self.call_budget.stop('CLI_JOURNAL_WRITE_FAILED')
                    raise BudgetStopped('CLI_JOURNAL_WRITE_FAILED') from None
                return value
