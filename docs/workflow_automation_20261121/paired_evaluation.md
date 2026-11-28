# Fixed-evidence comparison execution and limits

execute_fixed_evidence_pair in closed_loop.paired_evaluation accepts explicit arm_order=('single_analyst','committee') or ('committee','single_analyst'). The default preserves legacy execution. Invalid orders fail before source/output/backend setup. Freeze order before a future experiment; alternate deliberately across cases if the protocol requires it. No caller may change an already executed experiment's order retroactively.

Both arms share one admitted source view, backend, global deadline and total model reservation ceiling. Each arm now records remaining_model_reservations_before, remaining_model_reservations_after and budget_snapshot, including failures. Plan and result explicitly state shared_budget=true, equal_per_arm_allowance=false, equal_cost=false and randomized_order=false. Changing order does not make the experiment cost-matched, randomised or independently graded. Hidden model requests and invoice amounts remain UNKNOWN. An upstream terminal stop persists; the other arm does not get a fresh budget or retry.

The 2026-11-24 real pair completed both arms with 1 versus 11 CLI attempts. No starvation was observed in that run. It establishes neither equal resource use nor comparative quality. Existing raw artifacts are unchanged. No new live pair was executed for this patch.

Actual Claude Code implemented the patch and four tests, exit0 in62.971seconds. Codex strengthened observed call-order and first-stop checks, then ran all readiness stages:938tests,935passed,3skipped. This is engineering validation. Any empirical quality comparison must separately freeze cases, evidence and prompts and report all failures, explicit resource asymmetry and independent evaluation limitations.

## Historical website evidence route (2026-11-26)

execute_verified_evidence_pair accepts an explicit tuple of 1..8 (SourceCandidate, VerifiedRecord) pairs produced by trusted internal source verifiers. Every item is rechecked by TemporalGateway for the primary company: date, identity, exact content and body-read proof. Any rejected or duplicated input fails the whole preflight before output/backend creation; records are not coerced from model dictionaries. Conflicting ledgers fail. A body-read proof must be the boolean True, not a truthy string/integer. This is not authentication of a malicious trusted caller; retain the independently produced verifier receipts and sealed source hashes.

The package wrapper and this route share one analysis core. Both arms receive identical admitted QA, one backend, one global ceiling and the frozen arm order. No browsing or source discovery occurs in this comparison. source_proofs in plan records provenance hashes/timing, trusted_verifier_input=true and assessment_scope=fixed_evidence_analysis_only_not_research. The main dynamic workflow still selects specialists and sources itself; this evaluation API is not its prerequisite.

Validation: 11 new tests; full readiness965tests(962pass,3skip). Two existing byte-verified archive responses were replayed through the existing publisher verifier, yielding the original source/fact IDs. Both deterministic model arms received identical evidence; original files stayed unchanged. Actual new model/HTTP calls were0; local cached verifier gets were2. Fake model outputs are not an empirical comparison. No live pair or old company run was replayed.

Actual Claude implementation exited0 in146.645seconds; Codex completed edge cases and validation. Successful comparisons report null stop_reason; failures preserve their first terminal cause. The original 2026-11-24 real pair is unchanged.

Network accounting correction: new paired receipts use actual_network_calls=null, actual_source_http_requests=0 and managed_network_requests=UNKNOWN. A zero source-fetch budget does not certify zero underlying model-provider network requests. Old sealed fields are not retroactively rewritten. Full offline readiness after this correction:966tests(963pass,3skip).

First actual verified-publisher comparison completed under the frozen2026-11-26protocol: committee11CLI/263.889s, single analyst1CLI/18.027s, both MORE_DILIGENCE with9gaps. Actual model-visible source rows matched and old source files were unchanged. This case gives descriptive resource/latency evidence, not accuracy or superiority. Ragas and dynamic research were not run in this fixed-analysis comparison; see verified_publisher_pair_result_20261126.json.
