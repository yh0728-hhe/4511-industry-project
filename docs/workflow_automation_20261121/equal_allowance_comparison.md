# Equal allowance comparison and independent source review

The opt-in `execute_equal_allowance_pair` API allocates independent, identical
logical-call and CLI-process ceilings and requested durations to the single
analyst and committee. It reuses the existing evidence gate, analysis functions
and final acceptance gate. The original shared-budget API remains available and
its sealed runs are unchanged.

Each arm receives a new exact budget and backend. Unused calls cannot transfer;
a local call cap or timeout does not refund or reset calls and does not consume
the other arm's reserved allowance. An explicit account-quota rejection stops the
whole pair without starting the other arm. Unknown setup/programming failure also
stops the pair. Factory setup counts against the arm deadline. If the global
remaining time cannot cover a full second allocation, that arm is recorded as
not run rather than receiving a silently shortened allowance. Every arm failure
and partial committee trace is retained.

Call the API with trusted `(SourceCandidate, VerifiedRecord)` pairs, explicit
execution approval, per-arm calls in 1..12, per-arm seconds in 1..180, zero search
calls, concurrency one, a total call cap of exactly twice the per-arm cap and a
global deadline covering both arm durations plus at least five setup seconds
and at most 480 seconds. The supplied backend factory must own the exact arm
budget and explicitly expose the frozen model ID and identical CLI-process cap.
The production Claude CLI transport already enforces its own remaining-time
limit. An arbitrary backend factory is trusted code, not an OS isolation boundary.

This is **equal allowance**, not equal actual computation: the single analyst
normally uses fewer calls. Input/output tokens and dollar costs are not made
equal by this API, and exact model weights are not independently verified.
Therefore the stronger matched-token comparison in the draft protocol remains
unfulfilled. The new API has only been exercised with offline injected backends;
it has not produced a new live model-quality result.

## Independent company review packet

`scripts/experiments/prepare_company_review.py` exports a sealed completed
publisher pair for passage-support review. It checks the five saved result
artifacts against the earlier receipt, verifies saved first/last model inputs
against dispatch hashes and requires identical model-visible contexts. Original
inputs are not modified. The export never reads outcome labels, browses, calls a
model, creates gold labels or calculates a score.

A reviewer first reads `source_context.json` and completes the blank
`reference_first.json`, then opens the four passages in `outputs_second.json`.
The reviewer folder omits arm/role metadata. The coordinator-only operator folder
contains the mapping. Writing style can still reveal the method, and the mask
seed is reproducibility machinery, not a cryptographic blinding guarantee.

The prepared packet is in ignored local scratch at
`results/scratch/workflow_20261127/company_review_packet_001/`. It contains one
previously inspected company and four correlated, differently sized passages.
It is not a holdout or four independent cases. Reviewers should separate source
attribution, independently established facts, inference and normative judgments;
whole-passage verdict counts must not be treated as per-arm accuracy. Two human
reviews and adjudication remain outstanding. No investment recommendation is
certified. Raw publisher/model text remains private and untracked; a fresh
checkout needs the local sealed source artifacts to regenerate this export.

## Validation on November 27 2026

Fourteen new equal-allowance regressions and eight export regressions passed.
The existing 22 paired tests and 18 readiness tests passed. Full offline readiness
passed all six stages: 1,130 tests total, 1,127 passed and three skipped.
One separately bounded read-only Claude design-review call timed out after
120.738 seconds without a returned verdict. It was not retried or treated as
independent approval. No new live comparison, source retrieval, training or Y
change occurred. Current composite evidence coverage remains 164/240.

The readiness training blocker now correctly states that independent company
quality reference evidence and a matched-budget quality result are missing; it
no longer incorrectly says there has been no end-to-end engineering run.

Evidence: `data/metadata/workflow_20261121/equal_allowance_review_validation_20261127.json`.
