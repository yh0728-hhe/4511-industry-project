"""Offline temporal/content admission, call reservation and constrained file access."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from .contracts import Fact, aware, digest


class BudgetStopped(RuntimeError):
    pass


class CallBudget:
    """Atomic admission; dispatched attempts are never refunded.

    Rejection before dispatch (including concurrency rejection) does not consume
    a call. This does not preempt a running transport; transports need timeouts.
    """
    def __init__(self, request, clock=lambda:datetime.now(timezone.utc)):
        self.bound_request=request
        self.deadline=request.deadline
        self.caps={'model':request.max_model_calls,'search':request.max_search_calls}
        self.used={'model':0,'search':0}
        self.concurrency=request.concurrency
        self.active=0
        self.clock=clock
        self.lock=Lock()
        self.stopped=False

    def remaining_seconds(self):
        with self.lock:return max(0,(self.deadline-aware(self.clock())).total_seconds())

    def check(self):
        with self.lock:
            if self.stopped or aware(self.clock())>=self.deadline:
                raise BudgetStopped('STOP_OR_DEADLINE')

    def stop(self):
        with self.lock:self.stopped=True

    @contextmanager
    def reserve(self, kind):
        with self.lock:
            if kind not in self.caps:raise ValueError('unknown call kind')
            if self.stopped or aware(self.clock())>=self.deadline:raise BudgetStopped('STOP_OR_DEADLINE')
            if self.used[kind]>=self.caps[kind]:raise BudgetStopped('CALL_CAP')
            if self.active>=self.concurrency:raise BudgetStopped('CONCURRENCY_CAP')
            self.used[kind]+=1
            self.active+=1
        try:
            yield
        finally:
            with self.lock:self.active-=1

    def snapshot(self):
        with self.lock:return dict(used=dict(self.used),caps=dict(self.caps),active=self.active)


@dataclass(frozen=True)
class SourceCandidate:
    """Untrusted retrieval text: never pass directly to committee/specialists."""
    source_id: str
    url: str
    company_id: str
    topic: str
    text: str


@dataclass(frozen=True)
class VerifiedRecord:
    """Trusted fixture-ledger entry; a future live verifier must produce these.

    A model cannot submit its own 'verified=True'. This offline ledger is not a
    live publication verifier and must not be populated from model assertions.
    """
    source_id: str
    url: str
    company_id: str
    topic: str
    content_sha256: str
    availability_upper_bound: datetime
    proof_kind: str
    body_read: bool = True
    expected_capture: datetime | None = None
    served_capture: datetime | None = None


class TemporalGateway:
    def __init__(self, request, ledger):
        self.request=request
        self._ledger={}
        records=ledger.values() if hasattr(ledger,'values') else ledger
        for record in records:
            if not isinstance(record,VerifiedRecord):raise ValueError('trusted ledger records required')
            key=(record.company_id,record.source_id,record.topic)
            if key in self._ledger and self._ledger[key]!=record:
                raise ValueError('conflicting proof records; version explicitly instead of overwriting')
            self._ledger[key]=record

    def register_verified_record(self, record):
        """Internal trusted-verifier API; never exposed as an LLM/tool action."""
        if not isinstance(record,VerifiedRecord):raise ValueError('verifier record required')
        key=(record.company_id,record.source_id,record.topic)
        if key in self._ledger and self._ledger[key]!=record:raise ValueError('conflicting verified record')
        self._ledger[key]=record

    def admit(self, candidate, subject_id=None):
        """Return admitted Fact or an opaque reason; rejected text/URL never leaks."""
        token=digest(candidate.source_id)[:20]
        record=self._ledger.get((candidate.company_id,candidate.source_id,candidate.topic))
        reason=None
        if record is None:reason='UNVERIFIED_SOURCE'
        elif not record.body_read:reason='BODY_NOT_VERIFIED'
        elif (candidate.source_id,candidate.company_id,candidate.topic,candidate.url)!=(
                record.source_id,record.company_id,record.topic,record.url):reason='IDENTITY_OR_METADATA_MISMATCH'
        elif candidate.company_id!=(subject_id or self.request.company.company_id):reason='IDENTITY_MISMATCH'
        elif digest(candidate.text)!=record.content_sha256:reason='CONTENT_MISMATCH'
        elif record.proof_kind not in ('READABLE_ARCHIVE','VERIFIED_ORIGINAL_PUBLICATION'):reason='UNSUPPORTED_PROOF'
        else:
            try:
                if aware(record.availability_upper_bound)>self.request.as_of:reason='AFTER_CUTOFF'
                elif record.proof_kind=='READABLE_ARCHIVE':
                    if record.expected_capture is None or record.served_capture is None:reason='MISSING_CAPTURE_PROOF'
                    elif aware(record.expected_capture)!=aware(record.served_capture):reason='SUBSTITUTED_CAPTURE'
                    elif record.served_capture!=record.availability_upper_bound:reason='INCONSISTENT_AVAILABILITY'
            except ValueError:reason='UNVERIFIED_DATE'
        if reason:return None,dict(source_token=token,reason=reason)
        fact_id=digest('|'.join((record.company_id,record.topic,record.source_id,record.content_sha256)))
        return Fact(fact_id,record.source_id,record.company_id,record.topic,candidate.text,
            record.url,record.availability_upper_bound,record.content_sha256,record.proof_kind),None


class WorkspaceReader:
    """Only whitelisted files inside a run workspace; no shell/general repo tool.

    This is a file tool boundary, not an OS sandbox or protection against a
    hostile process racing filesystem changes. Live workers need OS isolation.
    """
    def __init__(self, root, allowed=(), max_bytes=65536):
        self.root=Path(root).resolve(strict=True)
        self.allowed=frozenset(Path(name).as_posix() for name in allowed)
        self.max_bytes=max_bytes

    def read(self, name):
        path=Path(name)
        if path.is_absolute() or '..' in path.parts or path.as_posix() not in self.allowed:
            raise PermissionError('FILE_NOT_ALLOWED')
        resolved=(self.root/path).resolve(strict=True)
        if not resolved.is_relative_to(self.root):raise PermissionError('FILE_OUTSIDE_WORKSPACE')
        if not resolved.is_file() or resolved.stat().st_size>self.max_bytes:raise PermissionError('FILE_TOO_LARGE_OR_INVALID')
        return resolved.read_text(encoding='utf-8')
