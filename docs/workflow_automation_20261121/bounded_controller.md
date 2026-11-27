# Bounded Codex / Claude controller

Implemented 2026-11-21. Entry: `python -m workflow_automation.controller --run-id plan-001` (PYTHONPATH=src). Default is DRY_RUN, zero CLI/model invocations. A different run ID with `--live-rehearsal` opts into the fixed draft/review task. Existing runs require `--resume`, same mode, pinned inputs and intact artifacts. Dry plans cannot silently become live runs.

This is not a general autonomous coding agent or installed scheduler. The fixed task is Codex drafting an evidence-extraction rubric, followed by Claude reviewing it. Both receive approved context as text, work in a private scratch directory, and cannot choose another task. Codex uses read-only sandbox/approval never/ignore-user-config; Claude uses safe-mode/dontAsk/no built-in tools. Actual Codex JSON events showed one agent_message and no command/tool events. Prompt constraints are not a general OS security guarantee; configured environment/server permissions remain relevant.

## Limits and persistence

Combined maximum TWO CLI process invocations and TWENTY minutes from receipt creation, each child timeout at most eight minutes or remaining shared deadline. Counters and dispatch intents persist before the process starts. These are process invocation ceilings, not exact token, inner-request or monetary ceilings. CLI subscription usage is real; no new experiment API key or paid research call is made. No inherited budget is increased.

Exclusive lease prevents concurrent controller writers. Abrupt controller termination may leave a stale lease: inspect the owner/child before manually releasing it, never auto-clear and re-dispatch. A worker failure or ambiguous prior RUNNING state blocks the run. Do not edit receipts to reset attempts/deadline. Completed artifacts are hashed and source changes refuse resume; a clean checkpoint after the Codex artifact can resume only the review, with the original deadline/count.

`coordination/STOP` is checked before each dispatch. It prevents the next worker; it is NOT a mid-call cancellation monitor. To end an active call immediately, use the host process/session controls. The per-call timeout terminates the owned child process tree (Windows taskkill; POSIX process group). No promise is made for a controller itself forcibly killed by the OS; verify its child before restart.

States: READY -> RUNNING -> REVIEW -> REVIEW_RUNNING -> DONE; errors -> BLOCKED; explicit provider error envelope reporting quota -> WAITING_QUOTA; STOP/deadline/attempt ceiling -> STOPPED. Successful prose mentioning quota is not a quota error. Missing executable/auth/permission/unclassified errors block; no automatic inference of a reset time. WAITING_QUOTA is terminal for this version: no sleep/retry/account switch or automatic post-reset recovery. A requested revision blocks, no model-to-model recursion.

No controller Git writeback. Local DONE means validated draft plus reviewer ACCEPT, not pushed/merged/deployed. `writeback_verified` stays false; the human-facing Codex root commits only reviewed files and verifies the remote separately.

## Observed rehearsal

Run `live-rehearsal-001`: one Codex CLI invocation then one actual Claude Code CLI invocation; Claude ACCEPT. Explicit completed-run resume returned DONE with attempts still2. Selected machine-readable evidence is `data/metadata/workflow_20261121/controller_rehearsal.json`; raw CLI payloads remain ignored scratch. Independent process usage within each invocation is not inferred from attempts.

Full offline readiness run `bounded-controller-validation-001`:443 tests,440pass/3skip, all six stages passed. The 24 new controller tests include actual sleeping-child timeout, crash after durable intent, clean checkpoint continuation, tamper/source-change refusal, stop between stages, malformed/revise result handling and cumulative ceilings. This demonstrates handoff mechanics, not research quality or actual quota-reset recovery.

## Travel readiness still open

No scheduled task/service/power setting/remote access or paid cloud worker was created. Before unattended travel use, separately verify machine uptime/no sleep, phone control/approval, a bounded scheduled trigger, a graceful stop channel and provider-supported recovery semantics. If not verified by Nov24, use explicit manual starts and the reproducible offline demo. Do not restart an expired night_controller. No Muse forwarding needed for this engineering handoff.
