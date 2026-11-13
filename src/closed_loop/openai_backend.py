"""Explicitly enabled OpenAI backend; no live client created at import time.

Disabled until the operator has actual user approval for separate API spending.
Tests inject a fake client. Subscription Codex quota is NOT this API budget.
"""
from dataclasses import fields,is_dataclass
from decimal import Decimal,ROUND_CEILING
import json
import os
from pathlib import Path
import uuid
from threading import Lock
from typing import get_args,get_origin,get_type_hints
import types

from .guards import BudgetStopped


MODEL='gpt-4o-mini-2024-07-18'
RATE_SOURCE='https://developers.openai.com/api/docs/models/gpt-4o-mini'
INPUT_PER_MILLION=Decimal('0.15')
OUTPUT_PER_MILLION=Decimal('0.60')


def schema_for(kind):
    if kind is str:return {'type':'string'}
    if kind is int:return {'type':'integer'}
    if kind is float:return {'type':'number'}
    if kind is bool:return {'type':'boolean'}
    if kind is type(None):return {'type':'null'}
    origin=get_origin(kind)
    if origin is list:return {'type':'array','items':schema_for(get_args(kind)[0])}
    if origin is types.UnionType:return {'anyOf':[schema_for(x) for x in get_args(kind)]}
    if is_dataclass(kind):
        hints=get_type_hints(kind)
        properties={field.name:schema_for(hints[field.name]) for field in fields(kind)}
        return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    raise ValueError('unsupported structured schema')


def decode_as(kind,value):
    origin=get_origin(kind)
    if origin is list:
        if not isinstance(value,list):raise ValueError('expected list')
        return [decode_as(get_args(kind)[0],x) for x in value]
    if origin is types.UnionType:
        for option in get_args(kind):
            try:return decode_as(option,value)
            except (ValueError,TypeError):continue
        raise ValueError('union type mismatch')
    if is_dataclass(kind):
        hints=get_type_hints(kind)
        if not isinstance(value,dict) or set(value)!=set(hints):raise ValueError('response fields mismatch')
        return kind(**{name:decode_as(typ,value[name]) for name,typ in hints.items()})
    if kind is float and type(value) is int:return float(value)
    if type(value) is not kind:raise ValueError('response primitive mismatch')
    return value


class APISpendEnvelope:
    """Conservative reservation under a pinned model/rate card, not a bill API.

    Reservations are never refunded, even for failed calls. Model/API prices
    and actual invoices remain provider-controlled; this records an estimate.
    """
    def __init__(self,limit_usd,journal_path=None,pilot_id='single-approved-pilot',request_cap=24):
        self.limit=Decimal(str(limit_usd))
        if not self.limit.is_finite() or self.limit<=0:raise ValueError('positive explicit API dollar limit required')
        self.reserved=Decimal('0');self.reported_estimate=Decimal('0');self.lock=Lock()
        self.request_count=0;self.request_cap=request_cap;self.pilot_id=pilot_id
        self.journal_path=Path(journal_path) if journal_path is not None else None
        self._lease_path=None;self._lease_id=uuid.uuid4().hex
        self._closed=False;self._sealed=False
        if type(request_cap) is not int or request_cap<1:raise ValueError('explicit request cap required')
        if self.journal_path is not None:
            self.journal_path.parent.mkdir(parents=True,exist_ok=True)
            lease=self.journal_path.with_suffix(self.journal_path.suffix+'.lock')
            try:
                fd=os.open(lease,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError:raise BudgetStopped('API_PILOT_LEASE_ALREADY_HELD') from None
            self._lease_path=lease
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as stream:
                    fd=None
                    json.dump({'lease_id':self._lease_id,'pid':os.getpid()},stream);stream.flush();os.fsync(stream.fileno())
            except BaseException:
                if fd is not None:os.close(fd)
                lease.unlink(missing_ok=True);self._lease_path=None
                raise
            try:
                if self.journal_path.exists():
                    for line in self.journal_path.read_text(encoding='utf-8').splitlines():
                        event=json.loads(line)
                        if event['pilot_id']!=self.pilot_id or Decimal(event['approved_limit_usd'])!=self.limit:
                            raise ValueError('pilot journal approval mismatch')
                        if event.get('kind')=='PILOT_COMPLETED':raise BudgetStopped('API_PILOT_ALREADY_COMPLETED')
                        amount=Decimal(event.get('reserved_usd','0'));estimated=Decimal(event.get('usage_estimate_usd','0'))
                        count=event.get('request_reservations',0)
                        if not amount.is_finite() or amount<0 or not estimated.is_finite() or estimated<0 or type(count) is not int or count<0:
                            raise ValueError('invalid pilot journal')
                        self.reserved+=amount;self.reported_estimate+=estimated;self.request_count+=count
                    if self.reserved>self.limit or self.request_count>self.request_cap:raise ValueError('pilot journal exceeds approval')
            except Exception:
                self.close();raise

    def _append(self,**event):
        if self.journal_path is None:return
        event.update(pilot_id=self.pilot_id,approved_limit_usd=str(self.limit))
        with self.journal_path.open('a',encoding='utf-8',newline='\n') as stream:
            stream.write(json.dumps(event,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())

    def close(self):
        self._closed=True
        if self._lease_path is not None:
            if self._lease_path.exists() and json.loads(self._lease_path.read_text())['lease_id']==self._lease_id:
                self._lease_path.unlink()
            self._lease_path=None

    def reserve(self,input_upper_bound,output_upper_bound):
        amount=((Decimal(input_upper_bound)*INPUT_PER_MILLION+Decimal(output_upper_bound)*OUTPUT_PER_MILLION)/Decimal(1000000)).quantize(Decimal('0.00000001'),rounding=ROUND_CEILING)
        with self.lock:
            if self._sealed:raise BudgetStopped('API_PILOT_ALREADY_COMPLETED')
            if self._closed:raise BudgetStopped('API_PILOT_OWNER_CLOSED')
            if self.request_count>=self.request_cap:raise BudgetStopped('API_APPROVED_PILOT_REQUEST_CAP')
            if self.reserved+amount>self.limit:raise BudgetStopped('API_DOLLAR_RESERVATION_CAP')
            self._append(kind='RESERVED_BEFORE_DISPATCH',reserved_usd=str(amount),request_reservations=1)
            self.reserved+=amount
            self.request_count+=1
        return amount

    def record_usage(self,estimate):
        with self.lock:
            self._append(kind='PROVIDER_USAGE_ESTIMATE',usage_estimate_usd=str(estimate))
            self.reported_estimate+=estimate

    def seal_completed(self):
        with self.lock:
            if self._closed:raise BudgetStopped('API_PILOT_OWNER_CLOSED')
            if not self._sealed:
                self._append(kind='PILOT_COMPLETED');self._sealed=True

    def snapshot(self):
        with self.lock:return dict(limit_usd=str(self.limit),conservative_reserved_usd=str(self.reserved),
            provider_usage_estimated_usd=str(self.reported_estimate),actual_invoice_known=False,
            total_pilot_request_reservations=self.request_count,request_cap=self.request_cap,
            persistent_across_restarts=self.journal_path is not None)


class OpenAIModelBackend:
    def __init__(self,client,spend_envelope,call_budget,model=MODEL,max_output_tokens=1000,max_request_bytes=32768):
        if model!=MODEL:raise ValueError('unapproved model/rate-card change; no fallback')
        if type(max_output_tokens) is not int or not 1<=max_output_tokens<=1000:raise ValueError('output cap required')
        if type(max_request_bytes) is not int or not 1024<=max_request_bytes<=32768:raise ValueError('request byte cap required')
        if getattr(client,'max_retries',0)!=0:raise ValueError('hidden SDK retries must be disabled')
        self.client=client;self.envelope=spend_envelope;self.call_budget=call_budget
        self.model=model;self.max_output_tokens=max_output_tokens;self.max_request_bytes=max_request_bytes
        self.attempts=[]

    def generate(self,schema,messages,temperature):
        self.call_budget.check()
        payload=dict(model=self.model,messages=[{'role':getattr(m,'role','user'),'content':m.content} for m in messages],
            temperature=temperature,max_completion_tokens=self.max_output_tokens,store=False,
            response_format={'type':'json_schema','json_schema':{'name':schema.__name__,'strict':True,'schema':schema_for(schema)}})
        size=len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))
        if size>self.max_request_bytes:raise BudgetStopped('API_REQUEST_BYTE_CAP')
        with self.call_budget.reserve('model'):
            return self._send(schema,payload,size)

    def _send(self,schema,payload,size):
        # Conservative byte/token bound plus framing margin; no cached discount assumed.
        reserved=self.envelope.reserve(size+8192,self.max_output_tokens)
        attempt=dict(schema=schema.__name__,model=self.model,request_bytes=size,reserved_usd=str(reserved),
            status='DISPATCHED',input_tokens=None,output_tokens=None)
        self.attempts.append(attempt)
        try:
            response=self.client.chat.completions.create(**payload,timeout=min(30,self.call_budget.remaining_seconds()))
        except Exception as exc:
            attempt.update(status='PROVIDER_ERROR',http_status=getattr(exc,'status_code',None),
                error_type=type(exc).__name__)
            raise BudgetStopped('API_PROVIDER_ERROR') from None
        usage=getattr(response,'usage',None)
        if usage is not None:
            incoming=getattr(usage,'prompt_tokens',None);outgoing=getattr(usage,'completion_tokens',None)
            attempt.update(input_tokens=incoming,output_tokens=outgoing)
            if type(incoming) is int and type(outgoing) is int:
                estimate=(Decimal(incoming)*INPUT_PER_MILLION+Decimal(outgoing)*OUTPUT_PER_MILLION)/Decimal(1000000)
                self.envelope.record_usage(estimate)
                if estimate>reserved:
                    attempt['status']='ACCOUNTING_BOUND_BREACH';raise BudgetStopped('API_ACCOUNTING_BOUND_BREACH')
        choices=getattr(response,'choices',[])
        if not choices or getattr(choices[0],'finish_reason',None)!='stop':
            attempt['status']='INCOMPLETE';raise BudgetStopped('API_INCOMPLETE_RESPONSE')
        message=choices[0].message
        if getattr(message,'refusal',None):
            attempt['status']='REFUSAL';raise BudgetStopped('API_REFUSAL')
        try:value=decode_as(schema,json.loads(message.content))
        except (ValueError,TypeError,AttributeError):
            attempt['status']='INVALID_JSON';raise BudgetStopped('API_INVALID_STRUCTURED_OUTPUT') from None
        attempt['status']='SUCCEEDED'
        return value


def create_live_backend(*,approved,limit_usd,call_budget,env_file=None,journal_path=None,pilot_id='single-approved-pilot'):
    if approved is not True:raise PermissionError('Separate API-spend approval required; subscription quota is not API credit')
    envelope=APISpendEnvelope(limit_usd,journal_path=journal_path,pilot_id=pilot_id)
    # Credential loading is delegated to normal application configuration only
    # after approval. Never print, copy, persist or pass keys to other agents.
    try:
        if env_file is not None:
            from dotenv import dotenv_values
            api_key=dotenv_values(env_file).get('OPENAI_API_KEY')
        else:api_key=os.environ.get('OPENAI_API_KEY')
        if not api_key:raise RuntimeError('Existing API configuration missing; no new key requested')
        from openai import OpenAI
        client=OpenAI(api_key=api_key,base_url='https://api.openai.com/v1',max_retries=0,timeout=30)
    except Exception:
        envelope.close();raise RuntimeError('Existing API client configuration failed; credentials not printed') from None
    return OpenAIModelBackend(client,envelope,call_budget)
