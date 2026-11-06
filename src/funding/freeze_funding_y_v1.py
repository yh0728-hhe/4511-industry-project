"""Offline, deterministic Funding Y v1 snapshot; missing is never zero.

Run from repository root: python src/funding/freeze_funding_y_v1.py
Run analyze_funding_benchmark.py first. No network or credentials required.
"""
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / 'data/interim/funding_source_benchmark'
OUT = ROOT / 'results/verified/funding_y_v1'


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def main():
    matches = read(BENCH / 'recentfunding_company_matches.csv')
    raw = read(BENCH / 'recentfunding_events_raw.csv')
    events = read(BENCH / 'funding_events_deduplicated.csv')
    overlap = read(BENCH / 'funding_source_overlap.csv')
    ids = read(BENCH / 'company_identifiers.csv')
    assert len(ids) == len(matches) == len(overlap) == 240
    universe = {r['company_id'] for r in ids}
    assert len(universe) == 240
    assert universe == {r['company_id'] for r in matches} == {r['company_id'] for r in overlap}
    assert all(e['company_id'] in universe for e in events)
    assert all('2024-04-04' < e['event_date'] <= '2026-04-04' for e in events)
    in_window = [e for e in raw if e['in_window'] == 'IN_WINDOW']
    assert all(e['event_date'] and e['evidence_url'] for e in in_window)
    counts = Counter(e['company_id'] for e in in_window)
    for m in matches:
        assert int(m['events_in_window']) == counts[m['company_id']]
        assert (m['match_status'] == 'FUNDING_EVENT_FOUND') == bool(counts[m['company_id']])
    positive = {e['company_id'] for e in events}
    assert positive == {r['company_id'] for r in overlap if r['either_source_found'] == 'YES'}
    by_id = {m['company_id']: m for m in matches}
    rows = []
    for cid in sorted(universe):
        evs = [e for e in events if e['company_id'] == cid]
        rows.append(dict(company_id=cid, funding_y_version='v1',
                         confirmed_positive=1 if cid in positive else '',
                         observation_status='CONFIRMED_POSITIVE' if evs else 'UNKNOWN',
                         observed_event_count=len(evs),
                         recentfunding_status=by_id[cid]['match_status']))
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'company_labels.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    summary = dict(version='Funding Y v1', cohort=240,
                   recentfunding_statuses=dict(sorted(Counter(m['match_status'] for m in matches).items())),
                   recentfunding_in_window_events=len(in_window),
                   confirmed_positive_companies=len(positive), unknown_companies=240-len(positive),
                   deduplicated_events=len(events),
                   window='2024-04-04 exclusive; 2026-04-04 inclusive',
                   api_calls=0, trellis_status='UNRESOLVED_DETAIL_EVIDENCE_UNAVAILABLE',
                   limitations=['missing is not zero', 'confirmed-positive only; no verified negatives',
                                'Form D supplementary, not primary ground truth',
                                'deduplication heuristic; first Form D filing only, not every filing',
                                'not suitable for ordinary binary accuracy or unfunded labels',
                                'Trieve known missing round; source recall incomplete'],
                   hash_method='SHA256 of UTF-8 json.dumps(parsed CSV rows, sort_keys=True)',
                   input_sha256={p.relative_to(ROOT).as_posix(): hashlib.sha256(json.dumps(read(p), sort_keys=True).encode('utf-8')).hexdigest()
                                 for p in sorted(BENCH.glob('*.csv'))})
    (OUT / 'manifest.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
