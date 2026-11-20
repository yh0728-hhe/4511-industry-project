"""Rebuild a derived audit from frozen rows and explicitly reviewed evidence.

Offline validation is structural, not independent re-verification of web pages.
No API key, network request, lag adjustment, or outcome-to-feature path is used.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import date
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / 'data/weekly_audit_20261119'
BASELINE = ROOT / 'data/team_snapshot_20261111/funding_outcomes.csv'
START, END = date(2024, 4, 5), date(2026, 4, 4)


def month_shift(day: date, months: int) -> date:
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    month += 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def date_interval(value: str, precision: str) -> tuple[date, date] | None:
    """UNREPORTED precision is conservatively a whole year, never day precision."""
    if not value:
        return None
    if not re.fullmatch(r'\d{4}(?:-\d{2})?(?:-\d{2})?', value):
        raise ValueError('invalid date format')
    year = int(value[:4])
    if precision == 'DAY':
        day = date.fromisoformat(value)
        return day, day
    if precision == 'MONTH':
        month = int(value[5:7])
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    if precision in ('YEAR', 'UNREPORTED', 'UNKNOWN'):
        # Validate a supplied month/day before widening its interval.
        if len(value) == 10:
            date.fromisoformat(value)
        elif len(value) == 7:
            date(year, int(value[5:7]), 1)
        return date(year, 1, 1), date(year, 12, 31)
    raise ValueError('unsupported date precision')


def window_attribution(interval: tuple[date, date] | None) -> str:
    if interval is None:
        return 'UNDETERMINED'
    first, last = interval
    if START <= first and last <= END:
        return 'INSIDE'
    if last < START or first > END:
        return 'OUTSIDE'
    return 'UNDETERMINED'


def boundary_flags(interval: tuple[date, date] | None) -> str:
    if interval is None:
        return 'UNKNOWN_DATE_REQUIRES_REVIEW'
    first, last = interval
    return '|'.join(name for name, boundary in [('START', START), ('END', END)]
                    if first <= month_shift(boundary, 3) and last >= month_shift(boundary, -3))


def admitted_disclosure(review: dict) -> bool:
    if not review.get('alternative_disclosure_admitted'):
        return False
    if review.get('alternative_disclosure_semantics') not in ('INVESTOR_PUBLIC_DISCLOSURE', 'COMPANY_PUBLIC_DISCLOSURE'):
        raise ValueError('a transaction or secondary provider date cannot be admitted as primary disclosure')
    if review.get('alternative_disclosure_precision') not in ('DAY', 'MONTH', 'YEAR'):
        raise ValueError('explicit publication precision required for admission')
    if not review.get('alternative_disclosure_url', '').startswith('https://'):
        raise ValueError('source URL required for disclosure admission')
    interval = date_interval(review.get('alternative_disclosure_date', ''), review['alternative_disclosure_precision'])
    if window_attribution(interval) != 'INSIDE':
        raise ValueError('entire publication interval must be inside the strict disclosure window')
    return True


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def build(baseline: list[dict], reviews: list[dict]) -> tuple[list[dict], list[dict], dict]:
    ids = {row['company_id'] for row in baseline}
    expected = {row['company_id'] for row in baseline if row['funding_evidence_status'] == 'FUNDING_KNOWN_WINDOW_UNDETERMINED'}
    actual = [row['company_id'] for row in reviews]
    if len(ids) != 240 or len(baseline) != 240:
        raise ValueError('expected the locked 240-company baseline')
    if len(actual) != len(set(actual)) or set(actual) != expected or len(actual) != 13:
        raise ValueError('reviews must match exactly the original 13 undetermined company IDs')
    candidate = [dict(row) for row in baseline]
    candidate_by_id = {row['company_id']: row for row in candidate}
    audit = []
    for review in reviews:
        admitted = admitted_disclosure(review)
        row = candidate_by_id[review['company_id']]
        if admitted:
            row.update(funding_evidence_status='IN_WINDOW_PUBLIC_DISCLOSURE', disclosure_in_window='YES',
                       disclosure_dates=review['alternative_disclosure_date'], disclosure_sources=review['alternative_disclosure_url'],
                       window_attribution='ESTABLISHED_ONLY_FOR_THE_DIMENSIONS_MARKED_YES')
        # First-sale evidence remains a separate dimension. One out-of-window
        # offering does not establish that all company financing is outside.
        interval = date_interval(review['provider_reported_date'], review['provider_precision'])
        audit.append(dict(company_id=review['company_id'], name_at_decision=review['name_at_decision'],
            provider_reported_date=review['provider_reported_date'], provider_precision=review['provider_precision'],
            provider_page_result=review['provider_page_result'], provider_round_url=review['provider_round_url'],
            provider_date_interval_start=interval[0].isoformat() if interval else '',
            provider_date_interval_end=interval[1].isoformat() if interval else '',
            provider_date_strict_window=window_attribution(interval), boundary_flags=boundary_flags(interval),
            original_announcement_url=review['original_announcement_url'], original_announcement_date=review['original_announcement_date'],
            original_announcement_precision=review['original_announcement_precision'], original_round_resolution=review['original_round_resolution'],
            separate_primary_disclosure_date=review['alternative_disclosure_date'],
            separate_primary_disclosure_url=review['alternative_disclosure_url'],
            company_strict_disclosure_candidate=row['disclosure_in_window'],
            transaction_first_sale_date=review['transaction_first_sale_date'], transaction_source_url=review['transaction_source_url'],
            transaction_event_attribution=window_attribution(date_interval(review['transaction_first_sale_date'], review['transaction_precision'])),
            transaction_company_label=row['transaction_in_window_confirmed'], negative_label_approved=row['negative_label_approved'],
            primary_urls_checked='|'.join(review['primary_urls_checked']), review_note=review['review_note']))
    disclosure = sum(row['disclosure_in_window'] == 'YES' for row in candidate)
    summary = dict(cohort=240, baseline_disclosure_companies=sum(row['disclosure_in_window'] == 'YES' for row in baseline),
        candidate_disclosure_companies=disclosure, candidate_disclosure_percent=round(100 * disclosure / 240, 4),
        disclosure_additions=[row['company_id'] for row in reviews if admitted_disclosure(row)],
        original_13_round_dates_resolved=sum(row['original_round_resolution'] != 'UNDETERMINED' for row in reviews),
        original_13_round_dates_undetermined=sum(row['original_round_resolution'] == 'UNDETERMINED' for row in reviews),
        company_disclosure_unknown_within_original_13=sum(row['company_strict_disclosure_candidate'] != 'YES' for row in audit),
        sec_first_sale_companies=sum(row['transaction_in_window_confirmed'] == 'YES' for row in candidate),
        verified_negative_companies=sum(row['negative_label_approved'] == 'YES' for row in candidate),
        strict_window_start=START.isoformat(), strict_window_end=END.isoformat(),
        status='REVIEWED_CANDIDATE_NOT_AUTOMATIC_REPLACEMENT_FOR_FROZEN_LABELS',
        transaction_and_disclosure_dimensions_combined=False, lag_adjustment_applied=False,
        original_2026_provider_rows_linked_to_separate_primary_events=False,
        limitation='Baseline 102 carried forward, not reverified. Company TrueClaim has separate dated primary disclosure; all 13 original provider round dates remain unresolved. Boundary output is a manual-review queue, not admissions or a measured lag study.')
    return candidate, audit, summary


def boundary_rows(baseline: list[dict], reviews: list[dict]) -> list[dict]:
    """Keep source collections unpaired: snapshot does not prove URL/date alignment."""
    records = []
    for row in baseline:
        for field, source_field, semantics in [('disclosure_dates', 'disclosure_sources', 'INHERITED_PUBLIC_DISCLOSURE_DATE'),
                ('transaction_first_sale_dates', 'transaction_sources', 'INHERITED_SEC_ISSUER_FIRST_SALE')]:
            for value in filter(None, row[field].split('|')):
                records.append(dict(company_id=row['company_id'], name_at_decision=row['name_at_decision'], reported_date=value,
                    precision='UNREPORTED', semantics=semantics, source_urls=row[source_field],
                    note='Source URLs are a company-level collection, not independently paired with this date. Inherited snapshot precision unreported; interval widened conservatively.'))
    for review in reviews:
        records.append(dict(company_id=review['company_id'], name_at_decision=review['name_at_decision'],
            reported_date=review['provider_reported_date'], precision=review['provider_precision'], semantics='PROVIDER_REPORTED_ROUND_DATE_NOT_TRANSACTION_PROOF',
            source_urls=review['provider_round_url'], note=review['provider_page_result']))
        for date_field, precision_field, source_field, semantics in [
                ('alternative_disclosure_date', 'alternative_disclosure_precision', 'alternative_disclosure_url', 'INVESTOR_PUBLIC_DISCLOSURE'),
                ('transaction_first_sale_date', 'transaction_precision', 'transaction_source_url', 'SEC_ISSUER_FIRST_SALE')]:
            if review[date_field]:
                records.append(dict(company_id=review['company_id'], name_at_decision=review['name_at_decision'],
                    reported_date=review[date_field], precision=review[precision_field], semantics=semantics,
                    source_urls=review[source_field], note='Independently read primary source; no inferred event equivalence.'))
    output = []
    for record in records:
        interval = date_interval(record['reported_date'], record['precision'])
        flags = boundary_flags(interval)
        if flags:
            display_span = date_interval(record['reported_date'], 'DAY') if len(record['reported_date']) == 10 else interval
            record.update(interval_start=interval[0].isoformat() if interval else '', interval_end=interval[1].isoformat() if interval else '',
                          boundary_flags=flags, displayed_date_boundary_flags=boundary_flags(display_span),
                          strict_window_attribution=window_attribution(interval), manual_review_required='YES')
            output.append(record)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=AUDIT)
    args = parser.parse_args()
    with BASELINE.open(encoding='utf-8-sig', newline='') as stream:
        baseline = list(csv.DictReader(stream))
    reviewed = json.loads((AUDIT / 'reviewed_evidence.json').read_text())
    candidate, audit, summary = build(baseline, reviewed['reviews'])
    boundaries = boundary_rows(baseline, reviewed['reviews'])
    summary.update(boundary_review_rows=len(boundaries), boundary_review_companies=len({r['company_id'] for r in boundaries}),
                   displayed_date_boundary_review_companies=len({r['company_id'] for r in boundaries if r['displayed_date_boundary_flags']}),
                   displayed_date_boundary_review_rows=sum(bool(r['displayed_date_boundary_flags']) for r in boundaries),
                   boundary_policy='Interval overlap within +/-3 calendar months of either strict window boundary; heuristic only, dates never shifted.')
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / 'original_13_date_audit.csv', audit, list(audit[0]))
    write_csv(out / 'funding_outcomes_candidate.csv', candidate, list(baseline[0]))
    write_csv(out / 'boundary_cases.csv', boundaries, list(boundaries[0]))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    inputs = [BASELINE, ROOT / 'scripts/audit_funding_dates.py', AUDIT / 'reviewed_evidence.json', AUDIT / 'pr3_original_round_leads.csv']
    outputs = [out / name for name in ('original_13_date_audit.csv', 'funding_outcomes_candidate.csv', 'boundary_cases.csv', 'summary.json')]
    files = []
    for path in inputs + outputs:
        try:
            relative = str(path.relative_to(ROOT))
        except ValueError:
            relative = path.name
        files.append(dict(path=relative, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (out / 'manifest.json').write_text(json.dumps(dict(audit_date=reviewed['checked_date'], source_pr3_commit=reviewed['source_pr3_commit'],
        generator='scripts/audit_funding_dates.py', source_verification='Manual primary-source reads; offline rebuild validates structure, not page truth.', files=files), indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
