# Discovery-backed workflow entry

`closed_loop.discovery_runner.execute_discovery_run` composes model lead, existing managed-discovery agent, independently verified archived pages, native debate, optional Ragas support review, gap feedback and thesis synthesis. This library entry is separate from the finite package command.

Pass an explicit historical RunRequest, new output directory, approved existing-agent usage, backend_factory(budget, root), discovery_factory(task, budget, root), and HTTP client. The factory returns a fresh ManagedWebDiscoveryAgent with exclusive output path and the SAME budget/request. Authentication is the caller's responsibility; the library creates no implicit service, key, or client.

The project cutoff is2024-04-04T23:59:59Z. Bounds: at most480seconds,24model reservations,12search reservations,2research passes,concurrency1 and3sources per discovery. Search reservations mix managed invocations and direct archive requests; internal managed HTTP/inferences are unknown. These bounds are not dollar limits.

The caller must justify historical domain anchors. Discovered official-domain paths can be queried independently of homepage navigation, but must pass exact indexed target, timestamp, Memento replay and content gateway checks. Third-party domains stay held by default. Explicit `verify_publishers=True` enables a bounded archive verifier requiring a target-name headline and a labelled exact-company-domain link in the eligible replay. It labels the result ARCHIVED_EXTERNAL_PUBLISHER_CONTEXT; editorial independence and claim truth remain unverified. Peer/alias binding is not supported. This is static HTML extraction, not computed browser visibility. No readable evidence is UNKNOWN, never a negative.

Saved files include source-bound plan fingerprint, proposal, gated result, provider trace, archive attempts/receipts and raw archive responses for reproduction. Stopped/failed runs are distinguished from ordinary bounded completion. Files remain private scratch artifacts. No automatic retry/resume/scheduling. Final source-bound analysis review remains distinct from automatic entailment diagnostics.

Validation:10injected composition tests, full798tests795pass3skip. Tests include actual main runtime+archive provider, no-lead unknown,429terminal status, exclusive output, sanitized failure, shared budgets and pending final review. No live quality result is claimed from these fixtures.

Optional publisher validation2026-11-25:22verifier tests,6provider tests and2runner integrations. Full863tests860pass3skip. No live publisher result at this checkpoint.


2026-11-25 transport/content correction: the observed GitHub replay is363,271bytes, exceeding the original256KiB decoded bound. One precommitted1MiB-bound request verified its2024-04-02 snapshot with0models. Current publisher extraction selects matching article/main context, excluding navigation/footer; captured-body replay produced5,033context characters with0newHTTP/model. Unsupported page structure staysUNKNOWN. Source claims/editorial independence remain unverified.

The library now accepts max_specialists=1..2 (default2) and publisher_max_body_bytes=128..1,048,576 (default262,144), both frozen in plan. These do not change24model/12search/480second maxima or6,000character extracted-context cap. Explicit one-specialist mode selects a role dynamically each pass; it does not prescribe a fixed feature list. Latest full offline:869tests866pass3skip. A fresh regression is frozen withone specialist,512KiB publisher bound andsame global caps; no result claimed yet.


## Single-command entry

From the existing checkout on E:, with an explicitly prepared config and a new private output directory:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='src'
python -m closed_loop.discovery_workflow --config docs/workflow_automation_20261121/discovery_workflow_example.json --output-dir results/scratch/my_new_authorized_run --approve-cli
```

The example is a configuration reference, not an instruction to replay the sealed Hatchet experiments. A new directory does not authorize repeating an already completed experiment. Use a historically justified company identity seed; the command does not certify corporate identity or reconstruct aliases from modern profiles. No Y/outcome columns are accepted.

`--help` and missing `--approve-cli` dispatch no auth/network/model calls. Config has13requiredfields and two optional booleans preliminary_screen and verify_packages (both defaultfalse); unknown fields remain rejected; duplicate keys, NaN, oversized JSON, naive/wrong cutoff, invalid bounds and extra fields are rejected before auth/output. Current project cutoff stays2024-04-04T23:59:59Z, including UTC-equivalent offsets. Source/body/specialist options are explicit, with existing global caps unchanged.

The command reuses existing local claude.ai authentication checks and rejects direct API routing; it creates no credentials or services. Auth has its own20second check before the research deadline begins. Authentication does not certify a billing amount; managed internal requests/inferences/invoice remain unknown.

Outputs add `config_snapshot.json`, `backend_wire/call_*.json/.stdin/.stdout/.stderr` and per-discovery wire folders to the library's plan/proposal/result/committee/provider/source receipts. Dispatch intent is saved before launching a process; failures retain sanitized exception type. Raw prompts/pages/outputs remain private under the chosen directory; commit curated hashes/receipts rather than raw captures.

Exit0 means a valid bounded execution, including MORE_DILIGENCE/NO_NEW_EVIDENCE or NO_ADMITTED_FACTS. It does not mean an investment recommendation is accepted or evidence is exhaustive. Stopped runs return2; config/auth/unexpected failures return1. No automatic retry, fallback, quota reset or resume is included.

When no source fact reaches analysis, the controller retains the selected research questions and skips model debate. It allows the remaining authorized research passes, then returns NO_ADMITTED_FACTS. The native committee already guarded empty evidence; this centralizes that behavior for other committee adapters. A transport restriction still retains its original stop reason. Existing source-rich flows remain unchanged.

Validation (2026-11-25): 12 command tests and 5 no-fact controller regressions; full readiness totals 905 tests, 902 passed, 3 skipped. The earlier source-rich library run used 23 CLI attempts over 431.369 seconds. A separate actual single-command Adagy run used 2 CLI attempts over 35.134 seconds and returned NO_ADMITTED_FACTS. Its later-brand canonical ID exposure is documented in guarded_command_live_result_20261125.json and corrected in the current prompt presentation; the old run was not replayed. Neither result establishes company accuracy or investment performance.

Timeout diagnostics (2026-11-26): the native backend distinguishes CLI_PROCESS_TIMEOUT from other process errors. When byte streams are available, the recording wrapper retains partial stdout/stderr privately and marks partial capture; neither absent streams nor a successful research result are invented. Capture failures preserve the original error. Cleanup failure does not guarantee every child terminated. There is no automatic retry or budget refund, and old sealed failures are not retrospectively relabelled.

Support policy (2026-11-26): an empty list of new factual research questions does not resolve an automatic unsupported-argument flag. Such a proposal stays MORE_DILIGENCE, preserves existing gaps and provenance, and emits EVIDENCE_SUPPORT_UNRESOLVED without manufacturing a new public-source query. The diagnostic may be wrong; this conservative hold is not a factual falsity judgment or a measured accuracy improvement.

Optional preliminary screen: add "preliminary_screen": true to explicitly reuse SingleAnalystBaseline before configured committee deliberation. Default remains full_committee. Source gates, model/search/deadline ceilings, support checking on escalation, and final acceptance are unchanged. An incomplete screen routes existing questions back to research and cannot itself release INVEST/PASS. The opt-in mode has offline integration and captured-response replay evidence, not a live performance/quality result. See progressive_committee.md.

Usage rejection handling (2026-11-26): both CLI transports share explicit error-envelope classification. Managed discovery stops on primary rate_limit_info.status=rejected, including before a malformed trailing frame. allowed/allowed_warning and secondary overage rejection alone do not stop the run. Missing utilization stays unknown. The legacy CLI_QUOTA_EXHAUSTED code denotes a provider usage/rate stop, not measured remaining tokens. No automatic retry, reset, model fallback, credit purchase or wakeup is added.


## Optional registry artifact discovery (2026-11-26)

Add `"verify_packages": true` explicitly to enable an existing PackageRegistryCollector-backed verifier. The library requires an explicit registry_http_client when enabled and rejects a registry client without the flag. No package name, feature list or evidence packet is supplied up front: the managed search must first observe a supported canonical unversioned PyPI/npm URL. Registry artifacts then pass their existing upload-time, digest, README domain-link and historical gateway checks. Current registry summaries are never evidence; package code is never installed or executed.

Only primary-subject lowercase PyPI names and lowercase unscoped or canonical unencoded @scope/name npm leads are supported. Invalid, encoded or versioned URLs and peer package claims remain held. Scoped registry paths, tarball basename, full manifest name and digests must agree; scope alone is not corporate identity proof. Domain links do not prove corporate authorship or historical domain ownership. The full attributed README must fit6,000characters; otherwise it is held without truncation or an older-version fallback. A package miss and URL aliases are cached for the run; no failed request is retried.403/429stops the shared run before other source routes.

Model/search/deadline caps remain unchanged. Registry metadata/artifact GETs consume the SAME search reservations as managed discovery and archive HTTP. New direct_registry_http_attempts and direct_source_http_attempts distinguish them from direct_archive_http_attempts. Registry journals, raw responses and scope receipts are saved privately. Plan freezes the explicit flag and28component hashes, including the shared npm name validator.

Validation:16new offline regressions,128focused tests passed; full readiness1,030tests(1,027passed,3skipped), all six stages passed. A zero-network/model replay of old captured bytes admitted Hatchet's historical wheel and held Million's oversized README. This is an adapter-path check, not fresh live acquisition or semantic quality evidence. Claude supplied a draft before timeout; Codex completed integration and validation. A later Claude read-only review also timed out without a verdict; neither timeout was retried.


Capability advertisement: when verify_packages is explicitly true, the managed search prompt describes historical package-document verification as an optional source type. It supplies no package name, URL or fact and still requires exactly one observed WebSearch; the default prompt remains unchanged. Three additional regressions; final full readiness1,033tests(1,030passed,3skipped), all six stages passed. The initial failed readiness run is retained: its injected test factory had not accepted the new optional keyword; updating that fixture restored the actual CLI integration test.


Managed timeout classification: subprocess.TimeoutExpired before the shared deadline now stops as WEB_DISCOVERY_PROCESS_TIMEOUT; an expired shared deadline stops as STOP_OR_DEADLINE. A previously recorded cause wins. Complete top-level frames captured before a timeout can preserve an explicit provider quota rejection, including before malformed/invalidUTF8tail; nested tool prose, allowed-primary/rejected-overage, stderr and incomplete search URLs do not establish quota or evidence. Generic executor errors keep WEB_DISCOVERY_PROCESS_FAILED. The sealed live registry test keeps its original reason. Eight new fake regressions and a zero-model/HTTP captured-stream replay validate control flow, not token-balance knowledge. Full readiness1,041tests(1,038passed,3skipped).


Scoped npm extension:13new offline regressions,123focused passed; full readiness1,084tests(1,081pass,3skip), six stages passed. Actual Claude drafted the shared parser/integration and7tests before180.418second timeout, without completion verdict. Codex completed strict scoped transport rules, source fingerprints and6additional regressions. Sourcec20ac6d passed both GitHub checks. A separately frozen zero-model live scoped probe dispatched1HTTPattempt but received no completed response before60.481second outer timeout; live availability and compatibility remainUNKNOWN. It was not retried or substituted. See scoped_npm_validation_20261126.json and scoped_registry_probe_result_20261126.json.


Registry CLI transport now uses a separate bounded Python worker per GET, reusing the unchanged raw registry validator and ProcessExecutor cleanup. This controls a blocked open/DNS/read without treating partial stdout as HTTP evidence. No retry, fallback, extra model call or source-gate relaxation is added. Shared deadline stops win; otherwise child timeout becomes REGISTRY_REQUEST_TIMEOUT. Cleanup has bounded overhead, so this is not a precise real-time guarantee or OS sandbox. The raw in-process client remains a low-level API for the child and tests.12new regressions and a harmless sleeping-child control passed; the earlier source probe was not retried. Full readiness1,096tests(1,093pass,3skip).
