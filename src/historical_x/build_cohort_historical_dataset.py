"""Build an outcome-blind 240-company historical-source dataset, with gaps.

Local spreadsheet observations never become dated external claims. Archived
YC data is accepted as a source candidate only if exact original name, slug
and W24 match. HN title evidence uses an exact name immediately before YC W24.
No Y table, current identity crosswalk, model or investment score is read.
"""
import csv
import gzip
from datetime import date
import hashlib
import html
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
COHORT=ROOT/'data/processed/w24_spreadsheet_2024-03-25.csv'
SOURCE=ROOT/'data/metadata/historical_x_240'
CACHE=ROOT/'.cache/historical_x_240'
OUT=ROOT/'data/processed/historical_x_240'
HN=SOURCE/'hn_pre_cutoff.json'
CUTOFF='2024-04-04'


def norm(value):return re.sub(r'[^a-z0-9]','',value.lower())
def words(value,n):return ' '.join(str(value or '').split()[:n])


def archived_claims(row,record):
    if record.get('query_status')!='ARCHIVE_BODY_FETCHED':return None
    timestamp=record['capture_timestamp']
    if not timestamp or timestamp>'20240404235959':raise ValueError('Post-cutoff capture')
    path=CACHE/(record['slug']+'.html')
    derived=SOURCE/'archived_fields'/(record['slug']+'.json')
    if not path.exists():
        if not derived.exists():return None
        fields=json.loads(derived.read_text(encoding='utf-8'))
        if (fields.get('capture_timestamp')!=timestamp or fields.get('body_sha256')!=record.get('body_sha256')
                or fields.get('original_company_name')!=row['Company Name'] or fields.get('original_yc_url')!=row['YC Link']):
            raise ValueError('Curated archive extraction provenance mismatch')
        return fields
    body=path.read_bytes()
    if hashlib.sha256(body).hexdigest()!=record.get('body_sha256'):raise ValueError('Archived body hash mismatch')
    decoded=gzip.decompress(body) if body[:2]==b'\x1f\x8b' else body
    match=re.search(r'data-page="([^"]+)"',decoded.decode('utf-8',errors='replace'))
    if not match:return None
    try:company=json.loads(html.unescape(match.group(1))).get('props',{}).get('company',{})
    except (ValueError,TypeError):return None
    slug=row['YC Link'].rstrip('/').split('/')[-1]
    if (norm(company.get('name',''))!=norm(row['Company Name']) or company.get('slug')!=slug
            or company.get('batch_name') not in ['W24','Winter 2024']):return None
    founders=company.get('founders') or []
    fields=dict(source_url=record['archive_url'],capture_date=record['capture_date'],capture_timestamp=timestamp,
        original_company_name=row['Company Name'],original_yc_url=row['YC Link'],
        body_sha256=record['body_sha256'],identity_check='EXACT_ORIGINAL_NAME_SLUG_W24',
        product_one_liner=words(company.get('one_liner'),18),product_description_excerpt=words(company.get('long_description'),65),
        tags=company.get('tags') or [],team_size=company.get('team_size'),year_founded=company.get('year_founded'),
        location=company.get('location'),founder_total_on_page=len(founders),
        founders=[dict(name=f.get('full_name'),title=f.get('title'),bio_excerpt=words(f.get('founder_bio'),12),linkedin_url=f.get('linkedin_url')) for f in founders[:4]],
        evidence_qualification='ARCHIVED_SELF_REPORTED_FIELDS_NOT_INDEPENDENT_BUSINESS_VERIFICATION',
        market_size=None,revenue=None,customer_count=None)
    derived.parent.mkdir(parents=True,exist_ok=True)
    derived.write_text(json.dumps(fields,indent=2)+'\n',encoding='utf-8')
    return fields


def hn_matches(row,hits):
    bound=re.compile(r'(?<!\w)'+re.escape(row['Company Name'])+r'\s*\(\s*YC\s*W24\s*\)',re.I)
    result=[]
    for hit in hits:
        title=hit.get('title') or '';published=(hit.get('created_at') or '')[:10]
        if bound.search(title) and published and published<=CUTOFF:
            date.fromisoformat(published)
            result.append(dict(source_url='https://news.ycombinator.com/item?id='+str(hit['objectID']),publication_date=published,
                title=words(title,25),claim_scope='DATED_TITLE_ONLY: name, W24 attribution and title product claim',
                limitations='Current vote/comment totals and later comments excluded; body edits not certified'))
    return result


def build():
    with COHORT.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if len(rows)!=240 or len({r['YC Link'] for r in rows})!=240:raise ValueError('Invalid locked cohort')
    hn=json.loads(HN.read_text(encoding='utf-8'))
    if hn.get('nbPages',1)>1:raise ValueError('Truncated HN query')
    packets=[];flat=[];inputs=[COHORT,HN]
    for row in rows:
        slug=row['YC Link'].rstrip('/').split('/')[-1];path=SOURCE/'sources'/(slug+'.json')
        record=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(query_status='NOT_ATTEMPTED')
        if path.exists():inputs.append(path)
        archive=archived_claims(row,record);posts=hn_matches(row,hn['hits'])
        if archive:inputs.append(SOURCE/'archived_fields'/(slug+'.json'))
        status='ARCHIVED_STRUCTURED_SOURCE' if archive else 'DATED_HN_TITLE_ONLY' if posts else 'HISTORICAL_EVIDENCE_GAP'
        packet=dict(company_id=row['YC Link'],company_name_at_decision=row['Company Name'],cutoff_date=CUTOFF,
            local_spreadsheet_observation=row,local_source_label_date='2024-03-25',local_external_availability_date=None,
            source_status=status,archive_query_status=record['query_status'],archived_yc_fields=archive,hn_title_evidence=posts,
            model_ready=False,review_status='CLAIM_REVIEW_REQUIRED',
            unknowns=['Original spreadsheet label date not independent publication proof','Archived fields are company self-report, not verified truth','Market size, revenue, retention and biographies not independently verified','No current funding/status inputs; no investment score generated'])
        packets.append(packet)
        flat.append(dict(company_id=row['YC Link'],company_name_at_decision=row['Company Name'],source_status=status,
            archive_query_status=record['query_status'],archived_capture_date=archive['capture_date'] if archive else '',
            archive_url=archive['source_url'] if archive else '',hn_pre_cutoff_sources=len(posts),
            historical_product=archive['product_one_liner'] if archive else '',
            historical_team_size=archive['team_size'] if archive and archive['team_size'] is not None else '',
            historical_founder_names='|'.join(f['name'] or '' for f in archive['founders']) if archive else '',
            historical_location=archive['location'] or '' if archive else '',market_size_verified=0,model_ready=0))
    counts=dict(cohort=240,base_observation_packets=240,archived_structured_companies=sum(bool(p['archived_yc_fields']) for p in packets),
        hn_title_matched_companies=sum(bool(p['hn_title_evidence']) for p in packets),
        companies_with_dated_source=sum(bool(p['archived_yc_fields'] or p['hn_title_evidence']) for p in packets),
        evidence_gap_companies=sum(p['source_status']=='HISTORICAL_EVIDENCE_GAP' for p in packets),model_ready_companies=0)
    manifest=dict(status='ALL_COHORT_ROWS_BUILT_HISTORICAL_COLLECTION_INCOMPLETE',cutoff=CUTOFF,counts=counts,
        query_status_counts={s:sum(p['archive_query_status']==s for p in packets) for s in sorted({p['archive_query_status'] for p in packets})},
        limitations=['240 rows does not mean 240 complete historical profiles','Source query failure is not absence','Only original YC URLs tried; no claim of archive completeness','Dated HN title does not establish team, traction or market size','Raw archived page cache retained locally; published packets carry source URLs, hashes and short excerpts','No Y read, model call, investment decision or population representativeness claim'],
        input_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in inputs})
    return packets,flat,manifest


if __name__=='__main__':
    packets,flat,m=build();OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'company_packets.json').write_text(json.dumps(packets,indent=2)+'\n',encoding='utf-8')
    with (OUT/'company_historical_data.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(flat[0]));w.writeheader();w.writerows(flat)
    (OUT/'manifest.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(m['counts'],indent=2))
