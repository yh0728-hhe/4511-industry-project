"""Validate the portable reviewed composite-Y snapshot (stdlib only)."""
import csv, hashlib, json
from collections import Counter
from pathlib import Path
p = Path(__file__).resolve().parent
m = json.loads((p / 'manifest.json').read_text(encoding='utf-8'))
# Manifest uses LF bytes; tolerate a CRLF checkout without ignoring content changes.
csv_bytes = (p / 'composite_y.csv').read_bytes().replace(b'\r\n', b'\n')
assert hashlib.sha256(csv_bytes).hexdigest() == m['csv_sha256'], 'CSV content/hash mismatch'
with (p / 'composite_y.csv').open(encoding='utf-8', newline='') as f:
    rows = list(csv.DictReader(f))
assert len(rows) == len({r['company_id'] for r in rows}) == m['cohort'] == 240
for r in rows:
    assert r['composite_y_status'] in {'OBSERVED', 'UNKNOWN'}
    assert r['financing_y'] in {'YES', 'UNKNOWN'}
    observed = (r['financing_y'] == 'YES' or r['shutdown_declaration_by_status_cutoff'] == 'YES'
                or r['provider_status_accepted_for_coverage'] == 'YES'
                or r['jeff_rule_presumed_dead_by_cutoff'] == 'YES')
    assert observed == (r['composite_y_status'] == 'OBSERVED'), r['company_id']
    assert r['status_outcome_cutoff'] == m['status_end']
    assert r['negative_label_approved'] != 'YES'
c = Counter(r['composite_y_status'] for r in rows)
assert c['OBSERVED'] == m['composite_observed'] == 164
assert c['UNKNOWN'] == m['composite_unknown'] == 76
assert sum(r['financing_y'] == 'YES' for r in rows) == m['financing_observed'] == 153
assert sum(r['composite_y_status'] == 'OBSERVED' and r['financing_y'] != 'YES' for r in rows) == m['status_only_observed'] == 11
assert Counter(r['coverage_basis'] for r in rows) == {'FINANCING_OBSERVED':153, 'UNRESOLVED':76, 'REVIEWED_PROVIDER_OUT_OF_BUSINESS':9, 'COMPANY_SHUTDOWN_DECLARATION':2}
print('Validated: 240 unique companies; 164 observed = 153 financing + 11 status-only; 76 UNKNOWN.')
