"""Offline agreement with frozen external annotations; never invokes a model."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def grade(predictions, gold, protocol):
    ids=protocol.get('case_ids')
    if (not isinstance(ids,list) or len(ids)!=6 or
            any(not isinstance(x,str) or not x.strip() for x in ids) or len(set(ids))!=6):
        raise ValueError('SIX_FROZEN_CASE_IDS_REQUIRED')
    if not isinstance(gold,list) or len(gold)!=6:
        raise ValueError('COMPLETE_FROZEN_GOLD_REQUIRED')
    refs={}
    for row in gold:
        if not isinstance(row,dict) or row.get('case_id') not in ids or row['case_id'] in refs:
            raise ValueError('INVALID_GOLD_CASE')
        value=row.get('expected_supported');spans=row.get('original_span_count');implicit=row.get('implicit_true_span_count')
        if (type(value) is not int or value not in (0,1) or type(spans) is not int or spans<0 or
                type(implicit) is not int or not 0<=implicit<=spans or value!=int(spans==0)):
            raise ValueError('INVALID_REFERENCE_MAPPING')
        refs[row['case_id']]=value
    if set(refs)!=set(ids) or not isinstance(predictions,dict):
        raise ValueError('CASE_SET_MISMATCH')
    ledger={};completed=predictions.get('completed');failed=predictions.get('failed');not_run=predictions.get('not_run')
    for status,rows in [('COMPLETED',completed),('FAILED',failed),('NOT_RUN',not_run)]:
        if not isinstance(rows,list):raise ValueError('EXPLICIT_CASE_PARTITION_REQUIRED')
        for row in rows:
            if not isinstance(row,dict) or row.get('case_id') not in ids or row['case_id'] in ledger:
                raise ValueError('MISSING_DUPLICATE_OR_FOREIGN_CASE')
            cid=row['case_id'];prediction=None
            if status=='COMPLETED':
                score=row.get('score');prediction=row.get('prediction')
                if (type(prediction) is not int or prediction not in (0,1) or
                        type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1 or
                        prediction!=int(score==1)):
                    raise ValueError('INVALID_PREDICTION')
            ledger[cid]={'case_id':cid,'status':status,'reference_supported':refs[cid],
                'prediction':prediction,'match':prediction==refs[cid] if prediction is not None else None}
    if set(ledger)!=set(ids):raise ValueError('NO_DROPPED_CASES_ALLOWED')
    all_complete=len(completed)==6 and not failed and not not_run
    if type(predictions.get('all_rows_completed')) is not bool or predictions['all_rows_completed']!=all_complete:
        raise ValueError('INCONSISTENT_COMPLETION_FLAG')
    matches=None;confusion=None
    if all_complete:
        matches=sum(x['match'] for x in ledger.values())
        confusion={key:0 for key in ['true_positive','true_negative','false_positive','false_negative']}
        for row in ledger.values():
            truth=row['reference_supported'];guess=row['prediction']
            key=('true_positive' if truth else 'false_positive') if guess else ('false_negative' if truth else 'true_negative')
            confusion[key]+=1
    return {'status':'REFERENCE_AGREEMENT_COMPUTED' if all_complete else 'INCOMPLETE_NO_GROUP_AGREEMENT',
        'cases':[ledger[cid] for cid in ids],'planned':6,'completed':len(completed),'failed':len(failed),
        'not_run':len(not_run),'reference_matches':matches,'confusion_counts':confusion,
        'sample_agreement':None if matches is None else {'numerator':matches,'denominator':6,'rate':matches/6},
        'constant_not_supported_matches':sum(x==0 for x in refs.values()) if all_complete else None,
        'external_reference_labels_human':True,'company_quality_gold':False,'aggregate_accuracy':None,
        'training':False,'Y_changed':False,'model_calls':0,'source_http_requests':0,
        'limitations':['Six purposive public RAGTruth QA cases, not unseen holdout or representative startup evaluation.',
            'Agreement is relative to supplied span annotations, not independently certified truth.',
            'A failed or missing prediction is retained, never mapped to a negative factual label.',
            'No general evaluator accuracy, investment performance or statistical superiority claim.']}


def _load(path):
    with Path(path).open("rb") as stream:raw=stream.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('BOUNDED_JSON_REQUIRED')
    return json.loads(raw),raw


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predictions',type=Path,required=True)
    parser.add_argument('--gold',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.output.resolve() in {args.predictions.resolve(),args.gold.resolve(),args.protocol.resolve()} or args.output.exists():
        parser.error('Output must be new and cannot overwrite inputs')
    predictions,pred_raw=_load(args.predictions);gold,gold_raw=_load(args.gold);protocol,proto_raw=_load(args.protocol)
    if digest(gold_raw)!=protocol.get('gold_sha256'):raise ValueError('GOLD_HASH_MISMATCH')
    if digest(Path(__file__).read_bytes())!=protocol.get('grader_sha256'):raise ValueError('GRADER_HASH_MISMATCH')
    if predictions.get('protocol_sha256')!=digest(proto_raw):raise ValueError('PREDICTION_PROTOCOL_MISMATCH')
    if predictions.get('input_sha256')!=protocol.get('input_sha256'):raise ValueError('PREDICTION_INPUT_MISMATCH')
    result=grade(predictions,gold,protocol)
    result['input_sha256']={'predictions':digest(pred_raw),'gold':digest(gold_raw),'protocol':digest(proto_raw)}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'status':result['status'],'completed':result['completed'],'reference_matches':result['reference_matches']}))
    return 0


if __name__=='__main__':raise SystemExit(main())
