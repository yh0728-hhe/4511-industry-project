# Historical X: full-cohort first collection and team publication — 2026-11-05

## User authorization and deliverables

User explicitly authorized uploading prior Y code/data to the team repository yh0728-hhe/4511-industry-project, superseding the earlier private-workspace-only restriction for this publication. Used an isolated worktree based on team main1b19327; did not push private research history or credentials. Y publication is PR1, portable candidate110 primary/1supplementary-only/129UNKNOWN with explicit limits. Stable offline stages and153 tests (2skips) accompany the public release. Raw provider caches/coordination traces excluded.

User also requested historical data for all companies. Built an outcome-blind240-company dataset from the ORIGINAL cohort. All240 rows/packets are present; historical evidence collection remains INCOMPLETE. Do not call240 rows240 fully verified historical profiles.

## Actual Historical X results

| Measure | Result |
|---|---:|
| Fixed cohort/base observation packets |240|
| Pre-cutoff archived YC structured profiles parsed |57|
| Exact-company pre-cutoff HN title matches |24|
| Unique companies with either dated source |75|
| Companies still with historical evidence gaps |165|
| Model-ready packets / model calls / rankings |0/0/0|

Archived company fields include product one-liner/short description, tags, reported team size, founding year, location and founder names/public profile links/short biography excerpts, where actually present. All derived from snapshots no later than2024-04-04. Company self-report remains self-report; no market-size, revenue, customer-count or biography verification invented. HN source qualifies only for original company name immediately before(YC W24), publication date and title product claim. Current scores/comments and later comments excluded.

Data: data/processed/historical_x_240/company_historical_data.csv, company_packets.json and manifest.json. The original spreadsheet's2024-03-25 label is retained as a local label, not proof of external availability. Current identity crosswalk, financing labels and post-cutoff YC snapshots are not read by this builder. Missing historical team size is blank, not0. All model_ready flags remain false pending claim review.

## Collection, failures and stopping

Free HN Algolia pre-cutoff search returned37 story hits,24 exact-name cohort matches. Wayback availability probe succeeded. First bounded pass attempted original YC URL CDX for all240, at most one indexed body each,3workers/9second timeouts; saved31 bodies. Many calls failed with Windows connection refusal. Detected gzip bodies despite identity request; fixed decoder and recovered all31 structured profiles offline.

One single-worker recovery pass retried59 failed-company records and improved totals to57 archived profiles. Additional3 official availability probes returnedHTTP429. Immediately after that probe batch, terminated only the identified recovery process; no more network requests or background job. Added RATE_LIMIT_STOP.json and a resume guard. This is not a completed recovery pass.

Final per-company archive states:57ARCHIVE_BODY_FETCHED,20OK_NO_CAPTURE_RETURNED,156INDEX_QUERY_FAILED,7BODY_QUERY_FAILED. Failed queries never recorded as no capture/evidence. Per-company ledgers contain365 saved request attempts across passes; this excludes the separate3 availability probes, initial connectivity probes and HN query. The failure history is preserved, not overwritten as success.

Raw archived bodies remain in ignored local.cache. Shared curated extractions carry original name/URL, archive timestamp, source URL, raw-body hash and short source excerpts. Offline reconstruction from those inputs reproduces the same dataset; it is reproducibility of curated source observations, not independent verification of every business claim. Re-running source capture requires source availability and respecting rate limits.

## Validation and reproduction

`python src/historical_x/build_cohort_historical_dataset.py`

`python -W ignore::ResourceWarning -m unittest discover -s src/historical_x/tests -q`

Working-stage historical suite:55 tests pass; the portable shared module includes5 tests for for240 unique rows, honest gaps/no Y inputs, pre-cutoff archived fields, post-cutoff rejection, strict HN matching, and identical reconstruction when raw cache is absent. Existing20-company seeds preserved as PENDING. No model call or investment ranking.

## PitchBook handoff requested during collection

Generated outputs/pitchbook_request_20261105/YC_W24_240_companies_for_PitchBook.csv and export_request.txt. Exactly240 unique company IDs;130HIGH primary-unknown rows(129unionUNKNOWN plus1supplementary-only),110CROSS_CHECK positives. Includes original/current matching names, aliases, domains and original YC URLs. Aliases/current names are matching aids for Y export, not Historical X features. No data sent to the third-party exporter by a tool.

## Next exact task

After source access recovers, inspect the saved rate-limit stop before a bounded resumed archive pass, prioritizing165 evidence gaps; do not requery already recovered57 pages. Independently review claims/identity before changing model_ready. Import PitchBook Company/Deal exports through stable cohort IDs and audit query absence vs actual outcomes. Team PR is uploaded but not merged; main is unchanged until review/merge. No active background process remains.
