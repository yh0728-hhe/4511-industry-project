"""Review PR #3's pinned Git objects without changing its outcome definitions.

No provider calls, raw caches, credentials, or outcome relabeling are involved.
Fetch the source branch before running if its objects are not present locally.
"""
import argparse
from collections import Counter
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = '82bb8e9f6e1224192d402283088b7ef0d809f35f'
PREFIX = 'data/team_snapshot_20261118/'


def git_bytes(ref, name):
    return subprocess.check_output(['git', 'show', f'{ref}:{PREFIX}{name}'], cwd=ROOT)


def review(ref=SOURCE):
    revision = subprocess.check_output(
        ['git', 'rev-parse', '--verify', f'{ref}^{{commit}}'], cwd=ROOT, text=True).strip()
    data = git_bytes(revision, 'composite_y.csv')
    manifest = json.loads(git_bytes(revision, 'manifest.json'))
    rows = list(csv.DictReader(io.StringIO(data.decode('utf-8'))))
    counts = Counter(row['composite_y_status'] for row in rows)
    financing = sum(row['financing_y'] == 'YES' for row in rows)
    status_only = sum(row['composite_y_status'] == 'OBSERVED' and
                      row['financing_y'] != 'YES' for row in rows)
    actual = hashlib.sha256(data).hexdigest()
    crlf = hashlib.sha256(data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest()
    union_valid = all((row['composite_y_status'] == 'OBSERVED') == (
        row['financing_y'] == 'YES' or row['shutdown_declaration_by_status_cutoff'] == 'YES'
        or row['provider_status_accepted_for_coverage'] == 'YES'
        or row['jeff_rule_presumed_dead_by_cutoff'] == 'YES') for row in rows)
    count_checks = (
        len(rows) == len({row['company_id'] for row in rows}) == manifest['cohort'] == 240
        and counts['OBSERVED'] == manifest['composite_observed'] == 164
        and counts['UNKNOWN'] == manifest['composite_unknown'] == 76
        and financing == manifest['financing_observed'] == 153
        and status_only == manifest['status_only_observed'] == 11
        and union_valid
        and all(row['negative_label_approved'] != 'YES' for row in rows))
    if not count_checks:
        raise ValueError('Pinned upstream snapshot count/union checks failed')
    return dict(
        reviewed_on='2026-11-19', source_pr='https://github.com/yh0728-hhe/4511-industry-project/pull/3',
        source_commit=revision, source_path=PREFIX, cohort=len(rows),
        composite_observed=counts['OBSERVED'], composite_unknown=counts['UNKNOWN'],
        financing_observed_under_upstream_definition=financing, status_only_observed=status_only,
        count_and_union_checks_passed=count_checks,
        repository_csv_sha256=actual, manifest_csv_sha256=manifest['csv_sha256'],
        original_validator_hash_check_passed=actual == manifest['csv_sha256'],
        manifest_matches_crlf_normalization=crlf == manifest['csv_sha256'],
        integrity_finding='The manifest hashes CRLF bytes; the committed CSV has LF bytes. '
                          'The original validator fails before its count checks.',
        documentation_finding='The Chinese opening paragraph says financing150 and UNKNOWN79; '
                              'the CSV, manifest and English paragraph say financing153 and UNKNOWN76.',
        recommended_upstream_fix='Regenerate the manifest hash from committed LF bytes and correct '
                                 'the Chinese opening totals; do not change outcome rows for this fix.',
        definitions=dict(strict_disclosure_end='2026-04-04',
                         upstream_non_sec_report_end=manifest['non_sec_report_end'],
                         automatic_three_month_date_shift_applied=False,
                         upstream_composite_is_strict_funding_coverage=False),
        disposition='REFERENCE_REVIEW_ONLY_NO_AUTOMATIC_RELABELING',
        limitation='Count/integrity review does not independently verify all sources or approve '
                   'the wider reporting window. No transaction/disclosure union is added to positives.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-ref', default=SOURCE)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'data/weekly_audit_20261119/upstream_pr3_review.json')
    args = parser.parse_args()
    result = review(args.source_ref)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(count_checks='PASSED',
                          upstream_hash_check=result['original_validator_hash_check_passed'],
                          crlf_explains_hash=result['manifest_matches_crlf_normalization'])))


if __name__ == '__main__':
    main()
