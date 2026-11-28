"""Offline CLI counter audit, not billing verification or a quality comparison."""
import argparse
import hashlib
import json
from pathlib import Path
from closed_loop.cli_backend import ClaudeCliBackend

FIELDS=('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')


def read(path):
    with Path(path).open('rb') as stream:raw=stream.read(524289)
    if len(raw)>524288:raise ValueError('AUDIT_INPUT_TOO_LARGE')
    return raw


def sha(raw):return hashlib.sha256(raw).hexdigest()


def audit(pair_root,receipt_path):
    root=Path(pair_root);receipt=json.loads(read(receipt_path));values={};input_hashes={}
    for name in ('plan.json','result.json','arms.json'):
        raw=read(root/name);input_hashes[name]=sha(raw)
        if receipt.get('raw_sha256',{}).get(name)!=sha(raw):
            raise ValueError('SEALED_PAIR_HASH_MISMATCH')
        values[name]=json.loads(raw)
    result=values['result.json'];plan=values['plan.json'];arms=values['arms.json']
    count=result.get('cli_process_attempts')
    if type(count) is not int or not 1<=count<=24:raise ValueError('BOUNDED_OBSERVED_PROCESS_COUNT_REQUIRED')
    if (len(arms)!=2 or {a.get('arm') for a in arms}!={'committee','single_analyst'} or
        any(a.get('status')!='EXECUTED_REVIEW_PENDING' or
            type(a.get('model_reservations')) is not int or a['model_reservations']<0 for a in arms) or
        sum(a['model_reservations'] for a in arms)!=count):
        raise ValueError('COMPLETE_RECONCILED_ARMS_REQUIRED')
    if any(a.get('evidence_sha256')!=plan.get('evidence_sha256') for a in arms):
        raise ValueError('ARM_CONTEXT_HASH_MISMATCH')
    journal=read(root/'dispatch.jsonl');input_hashes['dispatch.jsonl']=sha(journal)
    events=[json.loads(line) for line in journal.decode('utf-8').splitlines() if line.strip()]
    dispatch=[e for e in events if e.get('status')=='DISPATCHING']
    success=[e for e in events if e.get('status')=='SUCCEEDED']
    if (len(dispatch)!=count or len(success)!=count or
        any(type(e.get('process_count')) is not int for e in dispatch+success) or
        len({e.get('attempt_id') for e in dispatch})!=count or
        any(not isinstance(e.get('attempt_id'),str) or not e['attempt_id'] for e in dispatch) or
        sorted(e.get('process_count',-1) for e in dispatch)!=list(range(1,count+1))):
        raise ValueError('UNIQUE_COMPLETE_DISPATCHES_REQUIRED')
    totals=[];offset=0
    for arm in arms:
        rows=[]
        for n in range(offset+1,offset+arm['model_reservations']+1):
            d=[e for e in dispatch if e.get('process_count')==n]
            s=[e for e in success if e.get('process_count')==n]
            if len(d)!=1 or len(s)!=1 or d[0].get('attempt_id')!=s[0].get('attempt_id'):
                raise ValueError('UNIQUE_MATCHING_SUCCESS_REQUIRED')
            d,s=d[0],s[0]
            if d.get('model_id')!=plan.get('model') or s.get('model_id')!=plan.get('model'):
                raise ValueError('MODEL_ID_MISMATCH')
            stdin=read(root/f'backend_wire/call_{n:03d}.stdin')
            stdout=read(root/f'backend_wire/call_{n:03d}.stdout')
            if sha(stdin)!=d.get('prompt_hash') or sha(stdin)!=s.get('prompt_hash'):
                raise ValueError('PROMPT_HASH_MISMATCH')
            envelope=json.loads(stdout)
            if not isinstance(envelope,dict) or envelope.get('is_error') is not False:
                raise ValueError('EXPLICIT_SUCCESS_ENVELOPE_REQUIRED')
            usage=ClaudeCliBackend._usage_from_envelope(envelope)
            if not isinstance(usage,dict) or usage!=s.get('actual_usage'):
                raise ValueError('REPORTED_USAGE_MISSING_OR_CONFLICTING')
            rows.append(dict(process_count=n,stdout_sha256=sha(stdout),usage=usage))
        counters={f:sum(row['usage'][f] for row in rows)
            if rows and all(f in row['usage'] for row in rows) else None for f in FIELDS}
        totals.append(dict(arm=arm['arm'],observed_cli_attempts=len(rows),
            reported_counter_sums=counters,
            counter_coverage={f:sum(f in row['usage'] for row in rows) for f in FIELDS},attempts=rows))
        offset+=arm['model_reservations']
    return dict(status='OBSERVED_CLI_COUNTERS_RECONCILED_NOT_BILLING_OR_QUALITY',
        arms=totals,input_sha256=input_hashes,model_id_string=plan['model'],
        new_model_cli_attempts=0,new_source_http_requests=0,
        amount_charged='UNKNOWN',quota_debit='UNKNOWN',
        inner_inference_count='UNKNOWN',independently_authenticated_billing=False,
        counter_scope='Provider-reported CLI envelope counters; caches retained separately, no pricing conversion.',
        comparison_scope='One previously inspected unequal-resource development case; no quality superiority or general efficiency claim.',
        Y_changed=False,training_run=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair-root',required=True);parser.add_argument('--receipt',required=True)
    parser.add_argument('--output',required=True);args=parser.parse_args()
    value=audit(args.pair_root,args.receipt)
    with Path(args.output).open('x',encoding='utf-8') as stream:
        stream.write(json.dumps(value,indent=2)+'\n')
    print(json.dumps({k:v for k,v in value.items() if k!='input_sha256'},indent=2))


if __name__=='__main__':main()
