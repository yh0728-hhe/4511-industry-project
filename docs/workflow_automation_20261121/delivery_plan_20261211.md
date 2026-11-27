# Delivery plan for 2026-12-11 presentation

Planning date: 2026-11-21. User away 2026-11-25 through 2026-11-30; dates use America/Port-au-Prince. This is a project delivery plan, not an installed recurring automation.

## Minimum presentation deliverable
A reproducible AI-assisted research workflow: admissible evidence -> structured packet -> factual claims with citations or explicit unknown -> reviewer adjudication -> saved reproducible receipt. Keep historical investment evaluation separate from retrospective extraction. Current Y snapshot remains 164/240 composite,153/240 financing,76 UNKNOWN; no UNKNOWN-to-zero conversion. Coverage is not model accuracy. No supervised training unless a later justified evaluation establishes a need.

## Milestones
- Nov21-24: stabilize workflow; finish historical evidence disposition; freeze a small evaluation rubric and deterministic fixture cases; prepare a bounded controller and demonstrate restart/stop/duplicate prevention before travel. A mock controller test is not evidence of quota-reset recovery.
- Nov25-30: only preapproved finite tasks may run; phone access for material approvals or blockers. No historical gate -> offline retrieval/citation/abstention verification, packaging and documentation only. No invented real-company result.
- Dec1-4: if admissible data and separate cost approval exist, execute equal-input baseline/workflow comparison; otherwise deliver the tested retrospective/extraction workflow with historical evaluation explicitly blocked. Freeze experiment receipts and limitations.
- Dec5-7: finish presentation narrative, workflow diagram, measured process results, honest Y coverage and limitations; record a deterministic demo and backup.
- Dec8-10: rehearse, verify clean-checkout reproduction, freeze release and slide numbers. Avoid new features after freeze.
- Dec11: presentation.

## Automation architecture and honest limits
One lightweight deterministic controller dispatches Codex CLI implementation and Claude Code review serially, rather than two models recursively waking each other. Use explicit task IDs, pinned inputs, separate workspaces, exclusive leases, persisted attempt counts, checkpoints, output validation and a STOP sentinel. No idle model calls. A CLI call starts a CLI worker, not necessarily this desktop chat.

Quota is not context: context compaction and daily/weekly usage reset are different. No verified quota dashboard/reset-time API is assumed. On a genuine quota error persist WAITING_QUOTA. Only a documented provider retry/reset time can permit a later bounded attempt; an absent/ambiguous reset time requires user intervention. Never switch accounts, bypass limits, auto-purchase, or enable extra paid usage. Auth/permission errors block immediately; unknown network errors do not become quota-retry loops. Workers cannot self-increase budget or approve themselves.

Proposed first live controller rehearsal (not enabled): one task, one Codex implementation invocation and one Claude read-only review invocation, combined ceiling2, deadline20minutes from actual start, no paid data/model API, no outcome edits, no installation or power changes, private branch only. If either fails/quota-stops, preserve progress and stop; this rehearsal does not auto-resume at quota reset. A travel deployment requires a separate explicit absolute deadline and shared attempt/task ceilings, verified scheduled trigger, stop path, recovery test, and phone approval check. Do not restart the old night_controller or reuse its expired deadline.

Local execution requires the home computer to be powered, networked and able to run the worker. Phone connectivity alone does not establish that. Cloud execution is a separate environment needing private-repo access and equivalent constraints; not configured by this document. No new scheduled task, background service, remote port or account setting has been enabled.

## Next concrete engineering task
Implement and unit-test a bounded controller state machine with injected fake workers: READY/RUNNING/REVIEW/WAITING_QUOTA/BLOCKED/DONE/STOPPED; monotonic persistent global ceilings; stop/deadline before every dispatch; refuse stale leases/ambiguous execution; reject malformed reviewer results; no recursive model delegation. Demonstrate crash/restart without redoing completed work and failed writeback without claiming success. Only then wire a single finite live rehearsal. Muse is not needed for this engineering task.

## Independent Claude review and dispositions
Actual local Claude Code read-only review completed 2026-11-21, exit0/is_error=false; raw transcript remains ignored local scratch. Accepted findings: travel execution channel is unverified; controller may miss Nov24; historical gates must be named. Adagy, Aedilic and Aether have no verified pre-cutoff readable body admitted (see historical_gate_codex_review.json); remain OPEN, not silently completed. If the home-machine/phone/trigger/recovery checks fail or controller is unfinished Nov24, Nov25-30 defaults to NO_AUTONOMOUS_EXECUTION. Documentation can be prepared before travel or resumed in an explicitly started session, never assumed running by itself. The presentation still has an offline reproducible demo as fallback.

The reviewer cited old T001/Trellis sequencing. That file contains expired sprint/task language: this plan does not revive T001, assert remaining allowance, repeat its historical RecentFunding request or depend on its obsolete task order. General shared budgets/STOP/private-first rules still apply. Present scope is the current user-authorized workflow project; no additional paid request is authorized. Any later paid experiment needs explicit current approval in the active chat, phone or desktop, bound to the frozen plan and ceiling; it is not inferred from travel access.

## 2026-11-21 autonomy update
User authorized autonomous routine implementation, local verification and private-branch publication; do not ask for repetitive review approvals. This does not supply new billing credentials, authorize account changes or automatically satisfy external approval gates. Continue scoped engineering and honest evidence evaluation; only material unresolved cost/access decisions need user involvement. Resume claims must state what was actually executed. No background operation is inferred from this standing instruction.

Resume-ready scope: AI-assisted investment research engineering, a 240-company evidence audit, provenance/date/identity controls, bounded CLI handoffs, and reproducible evaluation infrastructure. Do not claim trained predictive model, investment returns, 90% coverage, production deployment or model accuracy improvements without actual evidence. Separate personal contributions from team work and reused upstream components. Next priorities are a completed demo, measured extraction comparison if feasible, documentation and presentation, rather than adding orchestration indefinitely.
