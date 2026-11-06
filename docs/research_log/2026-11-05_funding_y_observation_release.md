# Funding Y observation release — 2026-11-05

Follow-on financing is now available as a versioned observation dataset for the locked240-company cohort. The window remains **(2024-04-04,2026-04-04]**. This update follows the existing dated-log + code + derived-data layout and preserves the original inventory/design documentation.

## What changed

- Corrected the Trellis/trellis-ai RecentFunding entity match using existing verified evidence; retained explicit identity caveats.
- Added frozen Funding Y v1 and reviewed v2. V2 distinguishes primary financing evidence, supplementary Form D filings and quarantined legacy matches.
- Added a reproducible latest candidate from134 additional curated source observations: **110 primary positives,1 supplementary-only company,129 UNKNOWN, zero verified negatives**. The110/240=45.83% rate is evidence coverage, not the cohort's true fundraising rate. The target216 explicit outcomes has not been reached.
- Added offline repair, matching, supplement and validation code, source-linked evidence tables and hashes. No new keys/model calls are required to rebuild the release.

## Files and reproduction

| Output | Meaning |
|---|---|
| `results/verified/funding_y_v1/` | Historical frozen checkpoint; not overwritten by later corrections |
| `results/verified/funding_y_v2/` | Reviewed baseline,51 primary positives/3 supplementary-only/186 UNKNOWN |
| `data/metadata/funding_y_release_20261105/additional_observations.csv` |134 curated source-linked observations, UUID-deduplicated within this supplement |
| `results/candidates/funding_y_20261105/` | Latest110-primary-positive candidate; not independently frozen |

From repository root:

```bash
python src/funding/build_funding_y_release.py
python -W ignore::ResourceWarning -m unittest discover -s src/funding/tests -q
```

The portable builder starts from v2, promotes only admitted in-window positives and reproduces the latest company-level flags. `baseline_v2_evidence_record_count` and `additional_source_observation_count` remain separate: neither is an independently verified round census. The public release intentionally omits raw provider payloads, credentials and private collaboration traces; intermediate cache-dependent R&D stages are consolidated into this portable builder rather than copied without their inputs.

## Interpretation and limitations

Missing is not zero. No negative label is supported here. Do not train a binary success/failure model by treating129 UNKNOWNs as failures. Form D remains supplementary, and existing Lantern/Argon/Tesseral legacy-match quarantine reasons remain visible; separate later evidence does not validate the old disputed match. Multiple providers/UUIDs may describe the same real round; do not sum observation amounts or count them as independent rounds.

Dates are source-attributed. Some January1 dates have unverified precision. Retell's USD4.6m seed has conflicting historical May/Aug2024 references and a different current page-publication header. Its candidate window-positive uses a retained historical date interval wholly inside the Y window; no exact date is certified. Independent source/date review remains required before freezing v3. Company/domain changes observed after cutoff are used for Y identity only, never as Historical X inputs.

## Validation

153 tests completed successfully,2 skipped; skipped tests require omitted external/private cache artifacts. Five new portable-release tests verify counts/missingness, dates, cohort identity, duplicate observations and deterministic reproduction. Existing CLI negative-case tests intentionally print an error while the suite ends OK. Initial release validation exposed a missing pilot selection dependency; the reviewed selection files were included and the suite rerun successfully.

No model investment ranking, return estimate or claim of complete ground truth accompanies this release. Next steps are independent candidate review and separate point-in-time Historical X collection.
