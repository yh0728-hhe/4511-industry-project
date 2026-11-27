# Guarded closed-loop runtime prototype

This implements the *new control flow*, not a reinstallation of DIALECTIC and
not a re-run of the original Humane smoke test. The prior Humane smoke
test already exists: `data/metadata/runtime_r002_20261108/prior_humane_summary.json`
records the recovered artifact's checksum and verified result separately from
cost/time claims reported in the original Claude conversation.

A newly authorized **Abel** smoke test now executed real model-led routing,
historical retrieval and the adapted DIALECTIC committee. It returned
MORE_DILIGENCE after a targeted follow-up found no new evidence through the
configured tools. This is one limited-source smoke test, not an accuracy result.
The approved $0.20 API pilot is completed/sealed; total provider-usage estimate
is $0.00472890 across 15 API requests, not a verified invoice.

Input is a strict company seed, mandate, cutoff and budget. Research requests
are chosen during execution. No collected/manual evidence-packet input is
required. Specialists supply admitted evidence, not investment votes.

Run from repository root:

```powershell
python -m unittest discover -s tests -p test_closed_loop_runtime.py -v
python experiments/closed_loop_offline/run_fixtures.py
python -m unittest discover -s tests -p test_thesis_synthesis.py -v
```

The fixture trace demonstrates market/traction selection, missing retention,
targeted second research, new facts reaching regenerated committee input, and
INVEST/PASS/MORE_DILIGENCE outcomes. Fixture decisions come from explicit invented
markers, not models or real financial data. Budget counts are **logical dispatch
reservations**, distinct from actual network/model billing (zero in fixtures).
The generic core reports actual external usage as unknown; only the known
deterministic fixture harness asserts zero. Do not plug in a live provider and
retain fixture accounting labels.

`contracts.py`: strict input and typed outputs; semantic cache namespace includes
company/domain, cutoff, mandate, versions, specialist/question and peer subject.
`guards.py`: content/identity/date binding to a trusted fixture proof ledger;
atomic call/concurrency reservation; constrained workspace reader.
`runtime.py`: dynamic lead/research/committee/review/research loop; versioned
facts, source supersession and explicit QA bridge; stale-citation checks;
essential-gap override and structured budget stop.

Peer-company/market research is supported as an explicitly requested subject.
Facts retain their subject identity in QA rows: peer retention cannot satisfy
the fixture's target-retention question. Source namespaces include company,
source and topic; identities are not inferred merely from a matching name.

Important implementation limits:

- `archive_transport.py` now queries CDX, reads raw replay bodies, checks matching
  Memento timestamps, and records hashes. A substituted capture must be independently
  re-indexed and verified under its own timestamp. Domain identity anchors still
  rely on justified caller/cohort metadata, not independent past-ownership proof.
  A date/verified flag supplied by a model remains insufficient.
- File access is an allowlisted tool boundary, not an OS sandbox. Windows denied
  creating test symlinks, so that test is skipped rather than reported passed.
  TOCTOU and hostile concurrent filesystem mutation require OS isolation.
- Runtime research is sequential; concurrent reservation races are tested, but
  parallel specialists and a concurrent cache backend are not implemented.
- The archive transport meters each HTTP request, has no hidden redirects/retries,
  and applies timeouts/body limits. In-flight OS/transport cancellation is not an
  OS sandbox guarantee. Failures are unknown, never no-funding/death labels.
- `native_committee.py` executes 42 selected upstream definitions/prompts through
  an injected backend; original module client initializers/backoff decorators are
  omitted. Inner score-count retries remain metered. This is an adapted committee,
  not an unchanged upstream application or paper replication.
- `specialist_loop.py:SpecialistResearchLoop` (2026-11-15) adds a bounded
  within-specialist action loop (SUBMIT_FACT/FOLLOW_LINK(path)/STOP), reusing
  `RESEARCH_PROTOCOL` in a real request payload for the first time. It is an
  optional `ClosedLoopRuntime(..., specialist=...)` component: no existing
  caller/fixture supplies it, so `research()`'s default single-`provider.search()`
  path is unchanged. Each `FOLLOW_LINK` costs one more `search` reservation under
  the same run budget; `max_iterations` is bounded 1-8. It still only has
  `ArchivedWebsiteProvider.link_hints()` to choose from — a second, broader
  provider is a separate, not-yet-authorized gap.
- `thesis_synthesis.py:ThesisSynthesizer` (2026-11-15) adds the previously
  SPEC_ONLY final thesis synthesis from `thesis.md`'s "PROPOSED ONLY" block
  (reused verbatim, included in `prompt_fingerprint()`). It is an optional
  `ClosedLoopRuntime(..., thesis=...)` component: no existing caller supplies
  it, so `finish()`'s deterministic path and output keys are unchanged when
  omitted. When injected, it runs a single bounded structured-output call
  (no inner loop) strictly after a non-`MORE_DILIGENCE` decision with
  `stop == EVIDENCE_REVIEW_COMPLETE`; the model sees only the committee's own
  cited facts (never the full store or raw model memory), and its own
  `cited_fact_ids` must stay inside `context.store.facts` or the call is
  rejected (`BudgetStopped`). `ThesisSynthesis` has no numeric score/probability
  field by construction, enforced by a unit test. Output is attached as an
  additive `'thesis'` key; `decision`/`essential_gaps` are never touched by it.
  Versioned offline demo: `results/candidates/thesis_synthesis_20261115/`.
- `model_lead.py` uses the same backend to select specialist questions at runtime.
  `openai_backend.py` is disabled without explicit API-spend approval; dollar/request
  reservations persist across restarts, an exclusive lease prevents two budget
  owners, and completion seals the pilot against reuse. SDK retries are disabled.
  Pretrained future-knowledge leakage and claim correctness remain unproven.
- Do not expose Y files or modern profile rows through another Read/shell tool.
  Schema omission and date prompts do not provide that access boundary.

The stage-level `graph_driver.py` and stdlib driver match controlled scenarios;
`compare_native_graph.py` also checks actual adapted committee bodies with fixture
responses. Windows asyncio needs local socketpair IPC: `offline_network.py` permits
only listeners created by that process and blocks external sockets/DNS/UDP during
tests. It is not an OS sandbox against arbitrary native code.

Live execution requires a newly authorized pilot after the completed Abel pilot;
`live_one_company.py` without an approval flag only prints a plan and loads no key.
Search currently covers a narrow set of exact historical website URLs. Broad news,
peer discovery and richer historical source routing are next, not completed here.


## Package-backed CLI route and final-output acceptance

`package_source.py` and `npm_source.py` verify pre-acquired registry artifacts,
then `package_runner.py` runs the existing lead/committee/runtime on admitted
README text. Registry/latest descriptions are not historical features. Publisher
claims are not independently established product performance or business metrics.
This finite-document route is not autonomous unrestricted web research.

The runner now preserves `proposal.json` privately and applies
`analysis_acceptance.py` before releasing a substantive result. An unreviewed
INVEST/PASS proposal stays `MORE_DILIGENCE`, with `proposed_decision` retained and
accepted thesis withheld. A complete final-text inventory is bound to the source
run and checked via `claim_review.py`; annotations cannot be hand-picked or reused
after text/citation changes. Even complete supplied review is conditional reviewer
judgment, never automatic entailment or certified truth. Draft traces are unreviewed.
This integration does not rewrite older sealed API-run records or change Y labels.


Saved results can be reviewed offline with
`python -m closed_loop.saved_analysis_review --run-dir <run> --output-dir <new-review-dir>`.
Add `--review <review.json>` to apply complete annotations without rerunning models.
Original `plan.json`/`proposal.json` remain unchanged; output must be separate and
new. Legacy original `result.json` needs explicit `--proposal-name result.json`,
never automatic fallback. Export does not create approved reviewer verdicts.


`PackageRegistryCollector` in `package_registry.py` automates bounded retrieval for
explicit PyPI/npm mappings with an injected HTTP client and exclusive journal.
Pass its original `CallBudget` into `execute_package_run(call_budget=...)`; consumed
HTTP attempts and the deadline carry forward. One metadata GET and one artifact
GET maximum, no redirects/retries. A rejected or missing artifact remains unknown.
Registry/latest README content is excluded from evidence; only verified artifact
text reaches the gateway. Captured-response fixtures are not live-network results.
