"""Offline Funding Y v2: primary observations, supplemental filings, UNKNOWN.

No negative labels and no source completeness claim. Preserve frozen v1.
Retain v1 event clusters/variants; bulk rows corroborate or add dated events,
not multiple counts of the same round. Never sum incompatible amounts.
"""
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'results/verified/funding_y_v2'
INPUTS = [
    'results/verified/funding_y_v1/company_labels.csv',
    'results/verified/funding_y_v1/manifest.json',
    'data/interim/funding_source_benchmark/funding_events_deduplicated.csv',
    'data/interim/bulk_match/bulk_match_companies.csv',
    'data/interim/bulk_match/bulk_match_events.csv',
    'data/interim/bulk_match/bulk_match_manifest.json',
    'data/interim/identifier_repair/company_identifiers_repaired.csv',
    'data/processed/w24_raw_outcomes_24m.csv',
    'data/processed/yc2024_monthly.csv',
    'data/metadata/rename_evidence/agenthub_gumloop.json',
    'data/metadata/funding_y_v2/delve_identity_evidence.json',
    'data/metadata/funding_y_v2/additional_public_evidence.json',
]
QUARANTINE = {
    'lantern-2': 'Form-D-only identity conflict (inactive entity versus later filing, state mismatch)',
    'argon-ai-inc': 'Form-D-only issuer-state mismatch; unresolved, not proof of a false match',
    'tesseral': 'RecentFunding name-only identity match; source publishes no domain',
}
START, END = date(2024, 4, 4), date(2026, 4, 4)


def read(rel):
    with (ROOT / rel).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def in_window(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('Missing or non-ISO event date')
    return START < date.fromisoformat(value) <= END


def url_ok(value):
    parsed = urlsplit(value)
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname)


def norm_domain(value):
    parsed = urlsplit(value if '://' in value else 'https://' + value)
    return (parsed.hostname or '').lower().removeprefix('www.')


def interval_in_window(start, end):
    lo, hi = date.fromisoformat(start), date.fromisoformat(end)
    return lo <= hi and START < lo and hi <= END


def build():
    labels = read(INPUTS[0])
    cohort = {r['company_id'] for r in labels}
    if len(labels) != 240 or len(cohort) != 240:
        raise ValueError('Expected 240 unique original cohort IDs')
    companies = read(INPUTS[3])
    by_id = {r['company_id']: r for r in companies}
    if len(companies) != 240 or set(by_id) != cohort:
        raise ValueError('Bulk companies must exactly match the cohort')
    identifiers = {r['company_id']: r for r in read(INPUTS[6])}
    raw = {r['entity_id']: r for r in read(INPUTS[7])}
    canonical = read(INPUTS[2])
    bulk = read(INPUTS[4])
    used_slugs = {}
    verified = set()
    for cid, row in by_id.items():
        if row['match_basis'] not in ('DOMAIN', 'DOMAIN+NAME_TIEBREAK'):
            continue
        domain = norm_domain(row['matched_website'])
        allowed = {norm_domain(v) for v in identifiers[cid]['query_domains'].split('|') if v}
        if not domain or domain not in allowed:
            raise ValueError('Domain proof fails: ' + cid)
        slug = row['matched_slug']
        if not slug or (slug in used_slugs and used_slugs[slug] != cid):
            raise ValueError('Shared or missing source identity')
        used_slugs[slug] = cid
        verified.add(cid)

    evidence, excluded = [], []
    for index, row in enumerate(canonical, 1):
        cid = row['company_id']
        if cid not in cohort:
            raise ValueError('Evidence outside cohort')
        if not in_window(row['event_date']):
            raise ValueError('Canonical evidence outside window')
        if cid in QUARANTINE:
            excluded.append(dict(company_id=cid, origin='v1_cluster', origin_row=index,
                                 reason=QUARANTINE[cid]))
            continue
        rf = 'recent_funding' in row['sources'].split('|')
        if rf and cid not in verified:
            excluded.append(dict(company_id=cid, origin='v1_cluster', origin_row=index,
                                 reason='No domain-verified source identity'))
            continue
        layer = 'PRIMARY' if rf else 'SUPPLEMENTARY_FORM_D'
        if rf and not url_ok(row['evidence_url']):
            raise ValueError('Primary source URL missing: ' + cid)
        evidence.append(dict(
            company_id=cid, evidence_id='V1-%03d' % index, layer=layer,
            event_date=row['event_date'], date_kind='SOURCE_REPORTED_DATE_OR_CLUSTER' if rf else 'FORM_D_RECORDED_DATE',
            date_variants=row['date_variants'], round_type=row['round_type'],
            amount_usd='' if row['amount_disagreement'] == 'YES' else row['amount_usd'],
            amount_variants=row['amount_variants'], amount_conflict=row['amount_disagreement'],
            evidence_url=row['evidence_url'], sources=row['sources'],
            basis='Existing v1 event cluster with ' + ('new domain corroboration' if rf else 'supplemental filing only'),
        ))

    for index, row in enumerate(bulk, 1):
        cid = row['company_id']
        if cid not in cohort or not in_window(row['event_date']):
            raise ValueError('Invalid bulk event company/date')
        if cid not in verified or cid in QUARANTINE:
            continue
        if row['matched_slug'] != by_id[cid]['matched_slug']:
            raise ValueError('Bulk event/source identity mismatch')
        if any(e['company_id'] == cid and row['event_date'] in e['date_variants'].split('|')
               and 'recent_funding' in e['sources'].split('|') for e in evidence):
            continue  # existing cluster corroboration, not a second round
        if not url_ok(row['evidence_url']):
            raise ValueError('New bulk event has no source URL')
        evidence.append(dict(
            company_id=cid, evidence_id='BULK-%03d' % index, layer='PRIMARY',
            event_date=row['event_date'], date_kind='SOURCE_REPORTED_ANNOUNCEMENT_DATE',
            date_variants=row['event_date'], round_type=row['round_type'],
            amount_usd=row['amount_usd'], amount_variants=row['amount_usd'], amount_conflict='',
            evidence_url=row['evidence_url'], sources='recent_funding',
            basis='Domain-verified bulk match and dated round detail',
        ))

    delve = json.loads((ROOT / INPUTS[10]).read_text(encoding='utf-8'))
    panel_domains = {norm_domain(r['website'])
                     for r in read(INPUTS[8]) if r.get('slug') == 'delve' and r.get('website')}
    if (delve['company_id'] != 'RM-delve' or delve['identity_status'] != 'CONFIRMED'
            or delve['current_domain'] not in panel_domains
            or urlsplit(delve['primary_url']).hostname != delve['current_domain']
            or not in_window(delve['event_date'])):
        raise ValueError('Delve evidence does not bind to panel identity/window')
    evidence.append(dict(
        company_id='RM-delve', evidence_id='OFFICIAL-DELVE-20250722', layer='PRIMARY',
        event_date=delve['event_date'], date_kind='ANNOUNCEMENT_DATE',
        date_variants=delve['event_date'], round_type='SERIES_A',
        amount_usd='', amount_variants=delve['amount_as_stated'], amount_conflict='',
        evidence_url=delve['primary_url'], sources='company_announcement|lead_investor',
        basis='Official domain + panel domain continuity; wire release and investor corroboration',
    ))
    for e in evidence:
        e.update(date_start=e['event_date'], date_end=e['event_date'], date_precision='DAY')
    additional = json.loads((ROOT / INPUTS[11]).read_text(encoding='utf-8'))
    for record in additional['events']:
        cid = record['company_id']
        if cid not in cohort or not interval_in_window(record['date_start'], record['date_end']):
            raise ValueError('Additional evidence outside cohort/window')
        if norm_domain(record['domain']) not in {norm_domain(d) for d in identifiers[cid]['query_domains'].split('|') if d}:
            raise ValueError('Additional evidence domain not linked to cohort')
        if not url_ok(record['primary_url']) or not record['identity_evidence']:
            raise ValueError('Missing additional provenance')
        if record['date_precision'] == 'MONTH':
            if record['event_date']:
                raise ValueError('Month-only evidence must not fabricate a point date')
        elif record['date_precision'] == 'DAY':
            if not (record['event_date'] == record['date_start'] == record['date_end']):
                raise ValueError('Day precision conflicts with interval')
        else:
            raise ValueError('Unsupported date precision')
        evidence.append(dict(
            company_id=cid, evidence_id=record['event_id'], layer='PRIMARY',
            event_date=record['event_date'], date_kind='ANNOUNCEMENT_DATE' if record['date_precision'] == 'DAY' else 'SOURCE_REPORTED_MONTH_INTERVAL',
            date_variants=record['event_date'], round_type=record['round_type'],
            amount_usd='', amount_variants=record['amount_as_stated'], amount_conflict='',
            evidence_url=record['primary_url'], sources=record['source_kind'],
            basis=record['identity_evidence'], date_start=record['date_start'],
            date_end=record['date_end'], date_precision=record['date_precision'],
        ))
    evidence.sort(key=lambda r: (r['company_id'], r['date_start'], r['evidence_id']))
    output = []
    for cid in sorted(cohort):
        own = [e for e in evidence if e['company_id'] == cid]
        primary = any(e['layer'] == 'PRIMARY' for e in own)
        supplementary = any(e['layer'] == 'SUPPLEMENTARY_FORM_D' for e in own)
        output.append(dict(
            company_id=cid, name_at_decision=raw[cid]['name_at_decision'],
            y_primary_observed=1 if primary else '',
            primary_status='CONFIRMED_POSITIVE' if primary else 'UNKNOWN',
            supplementary_form_d_observed=1 if supplementary else '',
            source_union_observed=1 if own else '',
            union_status='CONFIRMED_POSITIVE' if primary else 'SUPPLEMENTARY_POSITIVE' if own else 'UNKNOWN',
            evidence_record_count=len(own),
            quarantined_legacy_match=QUARANTINE.get(cid, ''),
            missingness_note='' if primary else 'Not a verified negative; missing/insufficient admissible funding evidence',
        ))
    counts = dict(cohort=240, primary_positive=sum(r['y_primary_observed'] == 1 for r in output),
                  supplementary_only=sum(r['union_status'] == 'SUPPLEMENTARY_POSITIVE' for r in output),
                  source_union_positive=sum(r['source_union_observed'] == 1 for r in output),
                  union_unknown=sum(r['union_status'] == 'UNKNOWN' for r in output),
                  primary_unknown=sum(r['primary_status'] == 'UNKNOWN' for r in output),
                  evidence_records=len(evidence), quarantined_legacy_events=len(excluded),
                  verified_negatives=0)
    manifest = dict(version='Funding Y v2', counts=counts,
                    window=dict(start_exclusive='2024-04-04', end_inclusive='2026-04-04'),
                    limitations=['Observation dataset, not complete ground truth',
                                 'No verified negatives; UNKNOWN is not zero',
                                 'Form D remains supplementary, not primary target',
                                 'Evidence record count is not independently verified round count',
                                 'Existing heuristic clusters retained; no aggregate dollar total',
                                 'Current identities used only for Y resolution, never Historical X'],
                    api_calls_this_build=0,
                    input_sha256={p: digest(ROOT / p) for p in INPUTS},
                    v1_unchanged=True)
    return output, evidence, excluded, manifest


def main():
    labels, evidence, excluded, manifest = build()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, records in [('company_labels.csv', labels), ('event_evidence.csv', evidence), ('quarantined_events.csv', excluded)]:
        with (OUT / name).open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0]))
            writer.writeheader(); writer.writerows(records)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(manifest['counts'], ensure_ascii=False))


if __name__ == '__main__':
    main()
