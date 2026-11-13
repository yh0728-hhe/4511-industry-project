# Agent v0.1 and financing snapshot — team handoff

Prepared by **Rose Yu (YueYu-Rose)** with AI-assisted development and research.
Contribution scope for this handoff: project-specific agent specifications and
prompt adaptation; temporal/identity guards; critic-to-evidence-review handoff;
prompt-aware cache versioning; offline regressions; derived financing data audit.
This records the work delivered here, not a claim of sole authorship of the team
project. Other contributions remain represented by the existing team history.

- [Per-agent design and implementation status](../architecture/agents_v0/README.md)
- [Project prompt definitions](../../src/closed_loop/agent_prompts.py)
- [Core runtime](../../src/closed_loop/runtime.py)
- [Shared financing snapshot](../../data/team_snapshot_20261111/README.md)

Source checkpoint:private project commitcc48262 (November11,2026). Selected
reviewed files are synchronized onto the shared repository's existingmain base;
private repository history, credentials, rawAPIcaches, coordination files and full
model transcripts are not copied. DIALECTIC MIT license is retained alongside
reused nodes. Roles/cards distinguish WIRED,PARTIAL,SPEC_ONLY and deterministic
components. These designs and offline tests are not a live investment backtest.

Offline validation at the source checkpoint:104tests,103pass,1Windows symlink
skip. Fixture model responses validate flow and guardrails, not investment quality.
No newlyrun realLLM investment experiment is claimed. The prior company outcomes
and current funding table are not agentinputfeatures after the decisioncutoff.

```powershell
$env:PYTHONPATH="src"
python -m closed_loop.agent_prompts
python -m unittest discover -s tests -p "test_*.py" -q
python experiments/closed_loop_offline/run_fixtures.py
```

Windows asyncio tests need local loopbackIPC. OfflineSocketGuard blocks external
networking. Optionalgraphcomparison may require existingLangGraph installation;
no liveAPIkey is needed for unit tests or syntheticfixtures.
