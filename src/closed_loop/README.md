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
