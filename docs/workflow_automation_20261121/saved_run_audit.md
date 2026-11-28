# Offline saved-run consistency audit

Run from the repository root with PYTHONPATH=src:

```powershell
python -m closed_loop.saved_run_audit --run-dir YOUR_SEALED_RUN --output NEW_REPORT_OUTSIDE_RUN.json
```

The command reads only plan.json, result.json, optional proposal.json and committee_trace.json, bounded to 4 MiB per file. It never invokes a model, opens network connections, reads labels or writes into the run. Outputs are exclusive-create outside the input directory. Exit 0 means consistent records; 1 means findings; 2 means refused output. Missing/malformed data produce fixed finding codes without copying private evidence text.

Checks cover plan self-hash, declared caps and logical usage, reported process/HTTP counts, final/proposed/accepted decision consistency, empty evidence, terminal failures, prohibited success claims, and citations against each stage's available fact IDs. Older stage citations are not compared with only the final fact revision. Null external counters stay unknown. The audit is not authentication: a coordinated edit of all records could remain internally consistent. It does not certify source truth, historic ownership, claim support, independence, model accuracy or the absence of pretrained future knowledge. model_calls.json is deliberately not treated as a complete process ledger.

Validation 2026-11-26: 29 corruption regressions; full readiness 934 tests, 931 passed, 3 skipped. Four existing runs passed the consistency checks: source-rich completion, sparse-source completion, call-cap stop, and CLI failure. Input SHA256 values were identical before and after. The actual command exited 0 on the source-rich run. Original raw runs and their limitations remain unchanged. No company model/network reruns, training or Y changes occurred.

Claude drafted the module before a 180.600-second timeout; Codex completed validation and tests. The receipt is data/metadata/workflow_20261121/saved_run_audit_validation_20261126.json.
