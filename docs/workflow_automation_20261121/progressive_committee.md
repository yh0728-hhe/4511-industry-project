# Optional preliminary screen using existing agents

ProgressiveCommittee reuses SingleAnalystBaseline.assess(view) before an existing committee, which may itself be EvidenceCheckedCommittee. It uses the identical budget/deadline and owns no outer model reservation. This module is optional. The runner/CLI now expose an explicit opt-in; the legacy default remains off.

When the screen reports MORE_DILIGENCE or essential gaps, the wrapper returns MORE_DILIGENCE with the existing questions, no claimed citations, and a generic administrative rationale. It does not deliberate, synthesize a thesis, create source facts or turn screen claims into evidence. The original assessment is retained privately as untrusted, automatic and non-certified trace data. When the screen proposes INVEST/PASS without gaps, the original view goes unchanged to the existing committee; the preliminary recommendation is not passed into its prompts and cannot bypass final acceptance. A preliminary error stops the shared run, without fallback, retry, refund or source mutation. First recorded stop reason is preserved.

This may over-abstain and no empirical improvement is established. It is motivated by one development comparison(11committee CLI versus1baseline CLI, both incomplete), not a representative benchmark. Keep default behavior unchanged until explicitly evaluated and selected.

Validation:11newtests, full977tests(974pass,3skip). A captured real baseline response was replayed only when its input prompt matched byte-for-byte. The optional wrapper preserved all9questions, returned MORE_DILIGENCE, invoked no committee and left source/old wire bytes unchanged. Physical new model/source HTTP calls were0. The fake dispatch's copied usage metadata must not be counted as new billing. Runtime fixtures also covered evidence gap -> new source -> committee escalation. These are structural tests, not quality/cost/latency measurements.

Actual Claude implementation:140.169seconds,exit0,provider_is_error=false. Codex completed boundary corrections and validation. See progressive_committee_validation_20261126.json.

## Explicit opt-in (2026-11-26)

Add `"preliminary_screen": true` to an otherwise valid discovery-workflow JSON config, or pass preliminary_screen=True to execute_discovery_run. The original13required keys remain valid; this is the only additional optional key, must be a boolean, defaults false, and changes no caps or source criteria. Plan records preliminary_screen_enabled, analysis_strategy(full_committee/baseline_first) and hashes20components. Legacy examples/protocols were not rewritten or replayed.

The screen wraps the already configured committee after optional argument-support checking is composed. Thus an escalation still executes that support checker. Future/unverified sources are held before any screen. The normal final acceptance gate remains outside both strategies. No new prompts or model framework were introduced.

Integration checks:9additionaltests; full986tests(983pass,3skip). Tests include actual CLI forwarding of true without cap expansion, rejection before auth, legacy default, future-source exclusion before screen, and a sentinel proving configured Ragas checking remains on the escalation path. This is not a live performance/quality experiment.


## Incomplete screen output (2026-11-26)

MORE_DILIGENCE with an empty essential_gaps list stops explicitly as PROGRESSIVE_SCREEN_MISSING_GAPS. Previously the runtime treated this empty list as EVIDENCE_REVIEW_COMPLETE even though the committee had not run. The fix retains the untrusted assessment, admitted sources and call records; it does not invent a missing factual premise, trigger another model call or dispatch the committee as fallback. Nonempty questions still route through the bounded research loop; no default strategy change.

Actual Claude identified and implemented this guard; Codex reproduced the old behavior independently and verified saved runner artifacts. Three new regressions; 53 focused tests passed. Full offline readiness: 1,014 tests, 1,011 passed and 3 skipped, all six stages passed. These are control-flow checks, not semantic accuracy measurements.
