"""Offline12-case follow-up grading, reusing the frozen6-case mapping validator."""
import argparse,hashlib,importlib.util,json
from pathlib import Path
OLD=Path(__file__).with_name('ragtruth_reference_grade_20261126.py')
spec=importlib.util.spec_from_file_location('old_reference_grade',OLD)
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
sha=lambda raw:hashlib.sha256(raw).hexdigest()

def grade(predictions,gold,protocol):
    ids=protocol.get('case_ids')
    if not isinstance(ids,list) or len(ids)!=12 or any(not isinstance(i,str) or not i.strip() for i in ids) or len(set(ids))!=12:raise ValueError('TWELVE_UNIQUE_IDS_REQUIRED')
    if not isinstance(gold,list) or len(gold)!=12 or any(not isinstance(r,dict) for r in gold):raise ValueError('TWELVE_GOLD_ROWS_REQUIRED')
    if len({r.get('case_id') for r in gold})!=12 or {r.get('case_id') for r in gold}!=set(ids):raise ValueError('GOLD_CASE_MISMATCH')
    if not isinstance(predictions,dict):raise ValueError('PREDICTIONS_REQUIRED')
    seen=set()
    for partition in ['completed','failed','not_run']:
        rows=predictions.get(partition)
        if not isinstance(rows,list):raise ValueError('EXPLICIT_PARTITIONS_REQUIRED')
        for row in rows:
            if not isinstance(row,dict) or row.get('case_id') not in ids or row['case_id'] in seen:raise ValueError('DUPLICATE_OR_FOREIGN_CASE')
            seen.add(row['case_id'])
    if seen!=set(ids):raise ValueError('NO_DROPPED_CASES_ALLOWED')
    complete=len(predictions['completed'])==12 and not predictions['failed'] and not predictions['not_run']
    if type(predictions.get('all_rows_completed')) is not bool or predictions['all_rows_completed']!=complete:raise ValueError('INVALID_COMPLETION_FLAG')
    reports=[]
    for start in [0,6]:
        batch=ids[start:start+6];subset={key:[row for row in predictions[key] if row['case_id'] in batch] for key in ['completed','failed','not_run']}
        subset['all_rows_completed']=len(subset['completed'])==6 and not subset['failed'] and not subset['not_run']
        reports.append(legacy.grade(subset,[r for r in gold if r['case_id'] in batch],{'case_ids':batch}))
    matches=sum(r['reference_matches'] for r in reports) if complete else None
    confusion={k:sum(r['confusion_counts'][k] for r in reports) for k in reports[0]['confusion_counts']} if complete else None
    return dict(status='REFERENCE_AGREEMENT_COMPUTED' if complete else 'INCOMPLETE_NO_GROUP_AGREEMENT',
        cases=[r for report in reports for r in report['cases']],planned=12,completed=len(predictions['completed']),failed=len(predictions['failed']),not_run=len(predictions['not_run']),
        reference_matches=matches,confusion_counts=confusion,sample_agreement=None if matches is None else dict(numerator=matches,denominator=12,rate=matches/12),
        constant_not_supported_matches=sum(r['constant_not_supported_matches'] for r in reports) if complete else None,
        aggregate_accuracy=None,company_quality_gold=False,external_reference_labels_human=True,model_calls=0,source_http_requests=0,Y_changed=False,training=False,
        limitations=['New sourceIDs disjoint from previous6, not proven disjoint underlying passages or model pretraining.','Twelve mechanically selected balanced public cases, not representative startup diligence or statistical superiority.','No model tuning or production substitution; any failure retains all12 and null group agreement.'])

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['predictions','gold','protocol','output']:p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args(argv)
    if a.output.exists() or a.output.resolve() in {a.predictions.resolve(),a.gold.resolve(),a.protocol.resolve()}:raise ValueError('NEW_OUTPUT_REQUIRED')
    predictions,pred_raw=legacy._load(a.predictions);gold,gold_raw=legacy._load(a.gold);protocol,proto_raw=legacy._load(a.protocol)
    if protocol.get('protocol_id')!='RAGTRUTH-SOURCE-DISJOINT-12-20261126-001':raise ValueError('UNEXPECTED_PROTOCOL_ID')
    if sha(gold_raw)!=protocol.get('gold_sha256'):raise ValueError('GOLD_HASH_MISMATCH')
    if sha(Path(__file__).read_bytes())!=protocol.get('grader_sha256') or sha(OLD.read_bytes())!=protocol.get('legacy_grader_sha256'):raise ValueError('GRADER_HASH_MISMATCH')
    if predictions.get('protocol_sha256')!=sha(proto_raw) or predictions.get('input_sha256')!=protocol.get('input_sha256'):raise ValueError('PREDICTION_BINDING_MISMATCH')
    r=grade(predictions,gold,protocol);r['input_sha256']={'predictions':sha(pred_raw),'gold':sha(gold_raw),'protocol':sha(proto_raw)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as f:json.dump(r,f,indent=2);f.write('\n')
    print(json.dumps({k:r[k] for k in ['status','completed','reference_matches']}));return 0

if __name__=='__main__':raise SystemExit(main())
