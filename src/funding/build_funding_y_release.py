"""Rebuild the shareable Funding Y candidate from curated observations, offline.

V2 is the reviewed input baseline. Additional observations promote positives
only; absent records never become negatives. Original provider responses and
credentials are deliberately not required or redistributed.
"""
import csv
from datetime import date
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'results/verified/funding_y_v2/company_labels.csv'
OBS=ROOT/'data/metadata/funding_y_release_20261105/additional_observations.csv'
OUT=ROOT/'results/candidates/funding_y_20261105'


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def build():
    baseline=read(BASE);labels={r['company_id']:dict(r) for r in baseline}
    if len(labels)!=240 or len(baseline)!=240:raise ValueError('Invalid locked cohort')
    observations=read(OBS);seen=set();admitted=[];counts={}
    for e in observations:
        if e['company_id'] not in labels or e['evidence_id'] in seen:raise ValueError('Foreign company or duplicate observation')
        seen.add(e['evidence_id'])
        lower=date.fromisoformat(e['date_lower']);upper=date.fromisoformat(e['date_upper'])
        if not date(2024,4,4)<lower<=upper<=date(2026,4,4):raise ValueError('Outside locked event window')
        if not e['source_url'].startswith('https://'):raise ValueError('Missing source URL')
        if e['admission_status']=='PENDING_ACQUISITION_TIMING':continue
        if e['admission_status']!='ADMIT_OBSERVED_POSITIVE':raise ValueError('Unreviewed admission state')
        admitted.append(e);cid=e['company_id'];counts[cid]=counts.get(cid,0)+1
    new=[]
    for cid in sorted(counts):
        row=labels[cid]
        if row['y_primary_observed']!='1':new.append(cid)
        row.update(y_primary_observed='1',primary_status='CONFIRMED_POSITIVE',source_union_observed='1',union_status='CONFIRMED_POSITIVE',missingness_note='')
    result=[]
    for cid,row in sorted(labels.items()):
        row['baseline_v2_evidence_record_count']=row.pop('evidence_record_count')
        row['additional_source_observation_count']=str(counts.get(cid,0));result.append(row)
    primary=sum(r['y_primary_observed']=='1' for r in result);union=sum(r['source_union_observed']=='1' for r in result)
    manifest=dict(status='CANDIDATE_NOT_FROZEN',window=dict(start_exclusive='2024-04-04',end_inclusive='2026-04-04'),
        counts=dict(cohort=240,primary_positive=primary,supplementary_only=union-primary,source_union_positive=union,union_unknown=240-union,verified_negatives=0,additional_source_observations=len(admitted)),
        goal=dict(required_explicit_outcomes=216,primary_observed=primary,achieved=primary>=216),new_primary_since_v2=new,
        limitations=['Not complete ground truth; no verified negatives; UNKNOWN is not zero','Form D remains supplementary','Evidence observations are not independently deduplicated financing rounds; do not sum amounts','Exact event dates/precision not independently certified','Retell historical date interval disputed; independent review required before freeze','Post-cutoff identity observations support Y only, never Historical X'],
        input_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in [BASE,OBS]})
    return result,manifest


if __name__=='__main__':
    labels,m=build();OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'company_labels.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(labels[0]));w.writeheader();w.writerows(labels)
    (OUT/'manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(m['counts']))
