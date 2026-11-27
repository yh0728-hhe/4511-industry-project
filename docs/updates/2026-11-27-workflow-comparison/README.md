# Workflow comparison update on November 27 2026

The new opt-in comparison API gives each analysis arm its own matching logical
call ceiling, physical CLI launch ceiling and requested duration. A committee
cap no longer consumes the single analyst allocation. Unused reservations do
not transfer, and account-quota rejection stops both arms. Same actual tokens
or dollar cost are not enforced, so this is not a matched-token quality result.
Existing sealed comparisons and the November 26 HTML report remain unchanged.

A separate exporter prepares a previously inspected company source-support
review packet from local sealed artifacts. It leaves all reference/verdict
fields blank and removes arm labels from the reviewer folder. One company and
four correlated passages are not a holdout or four independent observations.
No human review has been completed and no quality score has been calculated.
The local packet, raw publisher context and model prose were not uploaded.

Shared verification passed all five stages: 907 runtime tests, 906 passed and
one skipped. The separate private full profile passed 1,137 tests, 1,134 passed
and three skipped, across six stages. The scopes differ; the shared check does
not claim to run the private funding suites. Twenty-nine new regression tests
cover allowance isolation, failure retention, review-export integrity and saved usage accounting.

A stale training-readiness message was corrected: end-to-end engineering runs
exist; the outstanding blocker is independent company quality evidence and a
matched-budget quality result. No Y labels or training changed. Composite
outcome evidence remains 164/240 (68.33%), with 76 unknown.

See [implementation and limitations](../../workflow_automation_20261121/equal_allowance_comparison.md)
and the shared validation receipt at
`data/metadata/workflow_20261121/shared_equal_allowance_validation_20261127.json`.

## Observed resource accounting

An offline check of the earlier sealed publisher case reconciled all 12 CLI
envelopes, dispatch identifiers, prompt hashes and recorded token counters.
The committee used 11 launches and reported 21,266 output tokens; the single
analyst used one launch and reported 1,274 output tokens. Both returned
MORE_DILIGENCE. Cache counters remain separately recorded. These figures are
not invoices, verified subscription debit, visible-text length or quality scores.
No model was rerun for this audit. See
`data/metadata/workflow_20261121/shared_usage_audit_validation_20261127.json`.

## Independent archive source feasibility

A new identity-only archive probe found two pre-cutoff AgentHub homepage capture
pointers in Common Crawl (February23 and March2 2024). They are index records,
not source bodies. The Agentic Labs index request returned502, and the separate
single AgentHub WARC-range request timed out. No request was retried, no body
was admitted and no financing/status inference was made. A current PyPI package
lead was also held because its displayed releases were all after the cutoff.

The pure offline index planner validates URL, date, digest syntax, safe archive
filename and byte-range metadata, and cannot create source proof. Fourteen new
regressions and cached real-index replay passed. It is not enabled in the
default workflow. The actual Claude coding task returned no files or verdict
before its180.927second timeout; Codex completed implementation and testing.

Latest shared profile:921tests,920passed,1skipped, all five stages. Latest private
full profile:1,151tests,1,148passed,3skipped, all six stages. These supersede the
earlier validation counts above and remain different scopes. No X/Y labels,
training, investment-quality claims or default source policy changed. See
[archive feasibility details](../../workflow_automation_20261121/commoncrawl_feasibility.md)
and `data/metadata/workflow_20261121/shared_commoncrawl_validation_20261127.json`.
