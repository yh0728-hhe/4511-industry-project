# Separate one-company smoke test — November 19, 2026

**Prepared, not run. On November 19, 2026, the user elected to upload the code and
plan without paid execution.** A future live run requires separate new approval.
The earlier Abel
pilot remains sealed. This week's selected company is **Adagy Robotics**, the
first alphabetical valid company after excluding Abel in the historical March
25, 2024 cohort. Selection reads name and website only; no funding/outcome table
or post-cutoff company profile is an input.

The decision cutoff is **April 4, 2024, 23:59:59 UTC**. Historical retrieval is
restricted to archive captures at or before that cutoff. Every content candidate
must pass the existing temporal/identity gateway before reaching the committee.
Current websites, current search snippets, and outcome labels have no retrieval
route in this experiment. The historical cohort supplies the domain anchor; its
past ownership is not independently certified. The model may retain future
knowledge from pretraining, so the run cannot certify absence of all leakage.

The fixed ceilings are **one company, 24 API requests, US$0.20 conservative cost
reservations, six archive HTTP requests, eight minutes, two research passes**.
Every nested lead/committee/research model generation uses the same budget. The
existing backend disables SDK retries and model fallback. Missing or invalid
provider usage stops the new experiment immediately. Provider/schema/validation
failure, a cap, or no new admissible evidence produces a stop with unknowns kept
explicit. No automatic rerun or budget refill is authorized.
The smoke backend stops the shared budget before propagating a backend failure,
so queued committee siblings cannot start another paid request afterward.
It also opts into a native-binding failure boundary covering message preparation,
reservations and response validation. Empty critiques and invalid citations stop
the shared budget before the committee semaphore admits queued siblings. Other
runtime backends keep their existing error policy unless they opt in explicitly.

The new `MeteredResearchProvider` wraps the archive provider and uses the same
backend to select up to two historical-link navigation steps per research task.
These steps consume the 24-call total; they do not receive an extra allowance.
The planner sees only gateway-admitted historical text and eligible links.

Generate the no-network, no-credential preflight from the repository root:

```sh
python experiments/closed_loop_offline/weekly_smoke.py
```

The versioned [plan](../../data/weekly_smoke_20261119/plan.json) records the seed,
seed hash, cohort file hash, exact model, proposed caps and plan fingerprint. The
plan also binds the current prompt bundle hash; prompt changes invalidate an
earlier saved plan before any backend is created. The
preflight does not load an OpenAI or Crunchbase key and reports zero requests.
API access and Codex subscription quota do not constitute API-spend approval.

Only after a user approves the concrete saved plan and the separate dollar cap,
an operator may run the same command with `--approve-api-usd 0.20` and
`--approved-plan-sha256` set to that plan's fingerprint. Existing OpenAI API
configuration is required. The pinned model's rate card must be rechecked against
its official source before authorizing spending; conservative reservations are
estimates, not a verified provider invoice.

Live outputs would be saved locally under
`results/candidates/weekly_smoke_20261119/`: `result.json` contains input/plan
hashes, decision/stop reason, derived trace, archive receipts, API attempts and
cost estimates; `api_budget.jsonl` persists reservations across restarts and seals
the one-off pilot on completion or failure. Raw page bodies and credentials are
not saved. The journal location and pilot identity are fixed independently of
the plan output path. Live outputs are not created by preflight and should be
reviewed before any public upload.
If setup is rejected, for example because the pilot is already sealed or its
lease is held, a separate `setup_failure_<unique-id>.json` is saved and any prior
`result.json` remains intact. Execution also rejects any plan differing from the
current canonical preflight, even if its altered contents have been rehashed.

Acceptance is limited to functioning metering, archival admission, saved outputs,
and an explicit stop. A one-company result cannot establish model accuracy,
investment returns, funding-label validity, or a two-class evaluation set.
