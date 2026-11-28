"""Offline review application; never dispatches a model or edits a saved run.

Saved files are trusted caller-owned run artifacts, not authenticated by this
utility. Hash checks detect inconsistency, not an attacker recomputing hashes.
Only the explicit final-output packet is reviewed; draft traces stay unreviewed.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .analysis_acceptance import gate_analysis

FINAL_KEYS=('decision','rationale','admitted_fact_ids','essential_gaps','thesis')


def _pairs(values):
    out={}
    for key,value in values:
        if key in out:raise ValueError('INVALID_SAVED_REVIEW_INPUT')
        out[key]=value
    return out


def _load(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4_000_000:
        raise ValueError('INVALID_SAVED_REVIEW_INPUT')
    with path.open('rb') as stream:raw=stream.read(4_000_001)
    if len(raw)>4_000_000:raise ValueError('INVALID_SAVED_REVIEW_INPUT')
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=_pairs,
        parse_constant=lambda _value:(_ for _ in ()).throw(ValueError('INVALID_SAVED_REVIEW_INPUT')))
    if not isinstance(value,dict):raise ValueError('INVALID_SAVED_REVIEW_INPUT')
    return value,hashlib.sha256(raw).hexdigest()


def review_saved_run(run_dir,output_dir,*,review_path=None,proposal_name='proposal.json'):
    """Write a new review artifact outside the original run, without inference.

    Legacy result.json must be explicitly requested and must contain the original
    ungated result. Never fall back to another file automatically. Reviewer
    annotations remain conditional judgments, not semantic certification.
    """
    try:
        if proposal_name not in ('proposal.json','result.json'):
            raise ValueError('INVALID_SAVED_REVIEW_INPUT')
        source=Path(run_dir).resolve(strict=True)
        target=Path(output_dir).resolve()
        if target==source or source in target.parents or target.exists():
            raise ValueError('INVALID_SAVED_REVIEW_INPUT')
        plan,plan_sha=_load(source/'plan.json')
        fingerprint=plan.get('fingerprint')
        canonical={k:v for k,v in plan.items() if k!='fingerprint'}
        expected=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
        if fingerprint!=expected or plan.get('status')!='SOURCE_ADMITTED_BEFORE_MODEL_CONSTRUCTION':
            raise ValueError('INVALID_SAVED_REVIEW_INPUT')
        proposal,proposal_sha=_load(source/proposal_name)
        if 'proposed_decision' in proposal or any(k not in proposal for k in FINAL_KEYS):
            raise ValueError('INVALID_SAVED_REVIEW_INPUT')
        review=None;review_sha=None
        if review_path is not None:
            review,review_sha=_load(Path(review_path))
        accepted=gate_analysis({k:proposal[k] for k in FINAL_KEYS},fingerprint,review=review)
        report=dict(status='SAVED_ANALYSIS_REVIEW_WRITTEN',acceptance=accepted,
            input_sha256=dict(plan=plan_sha,proposal=proposal_sha,review=review_sha),
            proposal_source=proposal_name,legacy_source_explicit=proposal_name=='result.json',
            review_supplied=review is not None,review_validated='review_summary' in accepted,
            model_calls=0,network_calls=0,training_run=False,Y_changed=False,
            original_run_modified=False,unreviewed_draft_trace=True,
            semantic_support_certified=False)
        target.mkdir(parents=True,exist_ok=False)
        (target/'review_result.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        return report
    except (ValueError,KeyError,TypeError,OSError,UnicodeError):
        raise ValueError('INVALID_SAVED_REVIEW_INPUT') from None


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True)
    parser.add_argument('--output-dir',required=True)
    parser.add_argument('--review')
    parser.add_argument('--proposal-name',choices=['proposal.json','result.json'],default='proposal.json')
    args=parser.parse_args(argv)
    try:
        report=review_saved_run(args.run_dir,args.output_dir,review_path=args.review,proposal_name=args.proposal_name)
    except ValueError:
        print(json.dumps({'status':'INVALID_SAVED_REVIEW_INPUT'}));return 2
    state=report['acceptance']['acceptance_state']
    print(json.dumps({'status':report['status'],'decision':report['acceptance']['decision'],
        'acceptance_state':state,'model_calls':0,'network_calls':0}))
    return 2 if state in ('INVALID_REVIEW','INVALID_ANALYSIS_PACKET') else 0


if __name__=='__main__':raise SystemExit(main())
