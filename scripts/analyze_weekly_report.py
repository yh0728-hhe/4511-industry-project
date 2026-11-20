"""Build chart-ready weekly metrics from committed derived evidence, offline.

This never reads a provider cache or treats absent evidence as a negative. The
output compares two versions of the strict disclosure definition separately
from the upstream composite definition. No charts or labels are inferred from
URLs alone.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'data/weekly_audit_20261119'
BASELINE = ROOT / 'data/team_snapshot_20261111/funding_outcomes.csv'

CATEGORY_LABELS = {
    'IN_WINDOW_PUBLIC_DISCLOSURE': ('Strict-window public disclosure', '嚴格窗口公開披露'),
    'UNKNOWN_NO_PUBLIC_EVENT_RETURNED': ('No public event returned', '未返回公開事件'),
    'FUNDING_KNOWN_WINDOW_UNDETERMINED': ('Known financing; window undetermined', '已知融資、窗口未定'),
    'CONFLICT_REVIEW_REQUIRED': ('Conflicting evidence', '證據衝突待審'),
    'INDIRECT_LEAD_SPV_ONLY': ('Indirect SPV lead only', '僅有間接 SPV 線索'),
    'UNKNOWN_IDENTITY_UNRESOLVED': ('Identity unresolved', '實體身分未解'),
    'UNKNOWN_EMPTY_FUNDING_PROFILE': ('Empty funding profile', '融資頁面空白'),
    'IN_WINDOW_ISSUER_SEC_TRANSACTION_ONLY': ('Issuer SEC first sale only', '僅 SEC 發行人首次出售'),
}


def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def percentage(count, cohort):
    return float((Decimal(count) * 100 / Decimal(cohort)).quantize(Decimal('0.0001')))


def test_count(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    return sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and
               node.name.startswith('test_') for node in ast.walk(tree))


def boundary_screen(rows, field):
    selected = [row for row in rows if row[field]]
    start = {row['company_id'] for row in selected if 'START' in row[field].split('|')}
    end = {row['company_id'] for row in selected if 'END' in row[field].split('|')}
    companies = {row['company_id'] for row in selected}
    assert start | end == companies
    return dict(evidence_rows=len(selected), companies=len(companies),
                start_companies=len(start), end_companies=len(end),
                both_boundary_companies=len(start & end),
                start_only_companies=len(start - end), end_only_companies=len(end - start)), companies


def build():
    candidate_path = AUDIT / 'funding_outcomes_candidate.csv'
    baseline, candidate = read_csv(BASELINE), read_csv(candidate_path)
    by_old = {row['company_id']: row for row in baseline}
    by_new = {row['company_id']: row for row in candidate}
    assert len(by_old) == len(by_new) == len(baseline) == len(candidate) == 240
    assert set(by_old) == set(by_new)
    cohort = len(candidate)
    summary = json.loads((AUDIT / 'summary.json').read_text(encoding='utf-8'))
    validation = json.loads((AUDIT / 'validation.json').read_text(encoding='utf-8'))
    upstream = json.loads((AUDIT / 'upstream_pr3_review.json').read_text(encoding='utf-8'))
    reviews = json.loads((AUDIT / 'reviewed_evidence.json').read_text(encoding='utf-8'))['reviews']
    original = read_csv(AUDIT / 'original_13_date_audit.csv')
    boundary_rows = read_csv(AUDIT / 'boundary_cases.csv')
    old_n = sum(row['disclosure_in_window'] == 'YES' for row in baseline)
    new_n = sum(row['disclosure_in_window'] == 'YES' for row in candidate)
    target_n = 216  # 90% of the fixed 240-company cohort, not a new success label.
    assert (old_n, new_n) == (102, 103)

    changes = []
    for company_id in sorted(by_old):
        before, after = by_old[company_id], by_new[company_id]
        fields = [field for field in before if before[field] != after[field]]
        if fields:
            changes.append(dict(company_id=company_id, name=after['name_at_decision'],
                                changed_fields=fields,
                                values={field: dict(before=before[field], after=after[field]) for field in fields}))
    assert [row['company_id'] for row in changes] == ['trueclaim']
    assert all(not any('transaction' in field or 'negative' in field for field in row['changed_fields'])
               for row in changes)

    counts = Counter(row['funding_evidence_status'] for row in candidate)
    assert set(counts) == set(CATEGORY_LABELS)
    disposition = [dict(key=key, label_en=label_en, label_zh=label_zh, count=counts[key],
                        percent=percentage(counts[key], cohort),
                        strict_disclosure_established=key == 'IN_WINDOW_PUBLIC_DISCLOSURE')
                   for key, (label_en, label_zh) in CATEGORY_LABELS.items()]
    assert sum(item['count'] for item in disposition) == cohort
    assert sum(row['negative_label_approved'] == 'YES' for row in candidate) == 0

    matrix_counts = Counter((row['disclosure_in_window'] == 'YES',
                             row['transaction_in_window_confirmed'] == 'YES') for row in candidate)
    dimensions = [dict(disclosure_established=disclosure, sec_first_sale_established=sec,
                       count=matrix_counts[(disclosure, sec)])
                  for disclosure, sec in ((True, True), (True, False), (False, True), (False, False))]
    assert [item['count'] for item in dimensions] == [11, 92, 1, 136]

    displayed, displayed_ids = boundary_screen(boundary_rows, 'displayed_date_boundary_flags')
    expanded, expanded_ids = boundary_screen(boundary_rows, 'boundary_flags')
    assert displayed_ids <= expanded_ids
    uncertainty_only = sorted(expanded_ids - displayed_ids)
    assert len(uncertainty_only) == 29

    precision = Counter(row['provider_precision'] for row in original)
    displayed_dates = Counter(row['provider_reported_date'] for row in original)
    assert precision == {'UNREPORTED': 12, 'DAY': 1}
    assert displayed_dates == {'2026-01-01': 11, '2026-04-01': 1, '2026-05-11': 1}
    assert all(row['original_round_resolution'] == 'UNDETERMINED' for row in original)
    original_chart_rows = [dict(company_id=row['company_id'], name=row['name_at_decision'],
                                displayed_date=row['provider_reported_date'],
                                precision=row['provider_precision'],
                                interval_start=row['provider_date_interval_start'],
                                interval_end=row['provider_date_interval_end'],
                                strict_window=row['provider_date_strict_window'],
                                original_resolution=row['original_round_resolution'],
                                disclosure_candidate=row['company_strict_disclosure_candidate']) for row in original]

    added_test_groups = [
        dict(label_en='Metered historical navigation', label_zh='歷史導覽後端',
             path='tests/test_research_backend.py', count=test_count(ROOT / 'tests/test_research_backend.py')),
        dict(label_en='Separate smoke-plan safeguards', label_zh='獨立 smoke test 防護',
             path='tests/test_weekly_smoke.py', count=test_count(ROOT / 'tests/test_weekly_smoke.py')),
        dict(label_en='Date precision and evidence dimensions', label_zh='日期精度與證據維度',
             path='tests/test_funding_date_audit.py', count=test_count(ROOT / 'tests/test_funding_date_audit.py')),
        dict(label_en='Navigation prompt cache invalidation', label_zh='導覽 prompt 快取失效',
             path='tests/test_agent_role_prompts.py', count=1),
    ]
    assert [group['count'] for group in added_test_groups] == [15, 14, 8, 1]
    assert sum(group['count'] for group in added_test_groups) == 38
    assert validation['offline_tests']['run'] == 104 + 38 == 142

    examples = []
    for company_id in ('trueclaim', 'haplotype-labs'):
        review = next(row for row in reviews if row['company_id'] == company_id)
        examples.append(dict(company_id=company_id, name=review['name_at_decision'],
                             primary_disclosure_date=review['alternative_disclosure_date'],
                             primary_disclosure_url=review['alternative_disclosure_url'],
                             transaction_first_sale_date=review['transaction_first_sale_date'],
                             transaction_source_url=review['transaction_source_url'],
                             original_provider_date_still_unresolved=True,
                             note=review['review_note']))

    inputs = [BASELINE, candidate_path, AUDIT / 'summary.json', AUDIT / 'validation.json',
              AUDIT / 'upstream_pr3_review.json', AUDIT / 'reviewed_evidence.json',
              AUDIT / 'original_13_date_audit.csv', AUDIT / 'boundary_cases.csv',
              ROOT / 'tests/test_research_backend.py', ROOT / 'tests/test_weekly_smoke.py',
              ROOT / 'tests/test_funding_date_audit.py', ROOT / 'tests/test_agent_role_prompts.py']
    return dict(
        report_date='2026-11-19', cohort=cohort,
        strict_disclosure=dict(window_start=summary['strict_window_start'], window_end=summary['strict_window_end'],
                               baseline_count=old_n, baseline_percent=percentage(old_n, cohort),
                               candidate_count=new_n, candidate_percent=percentage(new_n, cohort),
                               company_delta=new_n-old_n, percentage_point_delta=percentage(new_n-old_n, cohort),
                               target_percent=90, target_count=target_n,
                               companies_needed_to_target=target_n-new_n,
                               percentage_points_below_target=percentage(target_n-new_n, cohort),
                               strict_disclosure_unknown_count=cohort-new_n,
                               verified_funding_negatives=0,
                               limitation='Baseline carried forward; candidate not a replacement for frozen labels. Disclosure evidence does not prove transaction date.'),
        company_changes=changes, disposition=disposition,
        evidence_dimensions=dict(cells=dimensions, disclosure_total=new_n, sec_first_sale_total=12,
                                 limitation='YES is established evidence; false means not established, not no funding. Do not add a union as strict funding positives.'),
        original_13=dict(companies=len(original), original_rounds_resolved=0, original_rounds_undetermined=13,
                         companies_without_strict_disclosure=12,
                         provider_precision_counts=dict(precision), provider_displayed_date_counts=dict(displayed_dates),
                         stored_provider_link_domains=dict(Counter(urlparse(row['provider_round_url']).hostname for row in original)),
                         provider_page_read_dispositions=dict(Counter(row['provider_page_result'] for row in original)),
                         link_distribution_scope='Only the 13 original held-round leads, not all cohort funding sources.',
                         company_rows=original_chart_rows,
                         limitation='Provider display precision and original announcement precision are different. Twelve whole-year spans are conservative uncertainty envelopes, not dated funding events.'),
        boundary_review=dict(displayed_date_screen=displayed, uncertainty_expanded_screen=expanded,
                             uncertainty_only_additional_companies=len(uncertainty_only),
                             uncertainty_only_company_ids=uncertainty_only,
                             review_band_calendar_months=3, dates_shifted=False,
                             start_band=['2024-01-05', '2024-07-05'], end_band=['2026-01-04', '2026-07-04'],
                             limitation='Nested manual-review queues. Whole-year widening is conservative, not a measured source lag; rows may exceed companies.'),
        upstream_composite_reference=dict(source_commit=upstream['source_commit'], observed=164,
                                           observed_percent=percentage(164, cohort),
                                           financing_under_upstream_definition=153, status_only=11, unknown=76,
                                           non_sec_report_window_end='2026-07-04',
                                           limitation='Different definition and wider non-SEC window; not an increase from strict103 to164, not investment success.'),
        validation=dict(baseline_tests=104, current_tests=142, added_tests=38,
                         added_groups=added_test_groups, current_passed=142, current_skips=0,
                         live_paid_model_requests=0,
                         limitation='Test counts describe coverage of wiring and guards, not research quality. Baseline Windows reported103pass+1skip; current macOS142pass has different platform conditions.'),
        source_examples=examples,
        chart_rules=['Use company counts unless explicitly labeled evidence rows.',
                     'Never plot unknown as a negative financing outcome.',
                     'Never present PR3 composite and strict disclosure as one chronological growth series.',
                     'Separate provider display intervals from verified original announcement dates.',
                     'Show sample size, strict window, cutoff and carried-forward baseline limitations.'],
        sources=[dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in inputs])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=AUDIT / 'report_metrics.json')
    args = parser.parse_args()
    data = build()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(cohort=data['cohort'], strict_candidate=data['strict_disclosure']['candidate_count'],
                          target_gap=data['strict_disclosure']['companies_needed_to_target'],
                          boundary_companies=data['boundary_review']['uncertainty_expanded_screen']['companies'],
                          original_dates_resolved=data['original_13']['original_rounds_resolved']), ensure_ascii=False))


if __name__ == '__main__':
    main()
