# `src/` — W24 backtest pipeline

Reproducible source code for the W24 Demo Day investment-decision backtest.
Design decisions live in
[`docs/research_log/2026-10-29_w24_backtest_design.md`](../docs/research_log/2026-10-29_w24_backtest_design.md).

No credentials are required by anything here. All sources are public: the
GitHub API, `yc-oss.github.io`, the Wayback Machine CDX API, the Hacker News
Algolia API, and `sec.gov`. Nothing in this directory reads an API key.

## Which script produced which dataset

| Script | Produces | Rows |
| --- | --- | --- |
| `data_collection/build_yc_timeseries.py` | `data/processed/yc2024_monthly.csv` | 13,577 (23 monthly snapshots × 3 batches) |
| `outcome_tracking/extract_status_transitions.py` | `data/processed/status_transitions.csv` | 55 dated transitions |
| `entity_resolution/build_w24_crosswalk.py` | `data/processed/w24_crosswalk.csv`, `w24_uncertain_matches.csv` | 240 sheet rows |
| `data_collection/collect_pre_demoday_evidence.py` | `outputs/w24_27_audit.csv` | 27 audited companies |
| `outcome_tracking/fetch_sec_form_d.py` | `data/raw/form_d/` (gitignored, ~100 MB) | 11 quarters |

Shared helpers, not run directly:

| Module | Purpose |
| --- | --- |
| `data_collection/wayback.py` | CDX + snapshot fetch that reports `QUERY_FAILED` separately from "no captures" |
| `entity_resolution/normalize.py` | name/domain/slug normalisation; legal suffixes only, no fuzzy matching |

`evaluation/` is an empty placeholder — see its README.

## Order to run

```bash
# 1. outcome-side panel (slow: unauthenticated GitHub API, ~70 requests)
python src/data_collection/build_yc_timeseries.py

# 2. dated status events derived from it
python src/outcome_tracking/extract_status_transitions.py

# 3. link the dated 2024-03-25 cohort to current records
python src/entity_resolution/build_w24_crosswalk.py \
    --sheet data/processed/w24_spreadsheet_2024-03-25.csv

# 4. pre-Demo-Day evidence audit (slow: Wayback rate limits, ~5 requests/company)
python src/data_collection/collect_pre_demoday_evidence.py \
    --companies data/processed/w24_late_published_27.csv \
    --out outputs/w24_27_audit.csv

# 5. optional: follow-on financing evidence
python src/outcome_tracking/fetch_sec_form_d.py
```

Steps 1 and 4 are deliberately slow and polite to the upstream services. Step 4
takes roughly an hour for 27 companies because of Wayback backoff.

## Three failure modes this code is built to avoid

These are not hypothetical. Each one already happened during this project and
each one produced plausible-looking wrong data **without raising an error**.

1. **A failed query recorded as an absence of evidence.** Every network helper
   returns an explicit status. `QUERY_FAILED` must never be written as "no
   evidence". Conflating them once turned two companies with known pre-cutoff
   captures into "no historical evidence" rows.

2. **Reading a stale mirror file.** `yc-oss` serves both
   `batches/winter-2024.json` (live) and a frozen `batches/w24.json`. They
   disagree — 25 Inactive / 14 Acquired versus 7 Inactive / 2 Acquired.
   Filename order in `build_yc_timeseries.py` is load-bearing and the script
   warns loudly if it falls back.

3. **Over-eager entity matching.** Normalisation strips legal suffixes only.
   Stripping generic tokens turned "Pax Labs" into "pax" and matched YC's
   unrelated "Pax" to JUUL Labs at about \$1.98B. Ambiguous matches are written
   to an uncertain-matches file and never merged.

## Scripts intentionally not uploaded

| Local script | Why not |
| --- | --- |
| `master.py` | Superseded. Its run was killed at 180/267 and its output was never completed. It also hardcoded `demo_day_eligible=TRUE` and collected founder profile URLs. Its working logic survives in `entity_resolution/build_w24_crosswalk.py` with both problems fixed. |
| `audit27.py` (v1) | Superseded by `collect_pre_demoday_evidence.py`. It had the failed-query-as-absence bug and a loose name match that produced a false positive. |
| `mknb.py` | Notebook generator for a Chinese-language DIALECTIC walkthrough. Authoring tool, not part of the data pipeline. |
| ad-hoc diagnostics | One-off feasibility probes and HTML text extraction run inline; not reproducible pipeline steps. |
