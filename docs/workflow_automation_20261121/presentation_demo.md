# Presentation demo: one offline command

From repository root, PYTHONPATH=src:
`python -m workflow_automation.presentation_demo --output results/scratch/workflow_20261121/my-demo`
Open the generated index.html. A NEW directory is required; previous results are preserved. No keys, model calls, browser server or network access are needed. All source data remains in the private repository.

The bundle includes summary.json, four generated synthetic traces, an intentionally imperfect hand-authored scorer example and a manifest with source/artifact hashes. A Python socket guard blocks accidental network calls during collection. This is an engineering boundary, not OS isolation. Output staging avoids presenting a partial successful bundle if collection fails. Equal checkout inputs regenerate byte-identical outputs (tested).

Five-minute walkthrough:
1. Describe the 240-company cohort and ascertainment challenge. Show164/240 composite,153/240 financing,76UNKNOWN; these are not model outcomes.
2. Walk through synthetic_sufficient: first research leaves a retention gap, targeted follow-up admits evidence revision2, committee regenerates its input. Contrast missing-evidence and call-cap runs ending MORE_DILIGENCE. All companies and markers are invented.
3. Show the saved real Codex->Claude draft/review receipt and completed-run duplicate prevention. It is replayed evidence, not a newly invoked agent or unattended quota-reset deployment.
4. Open synthetic_scoring_example.json: its deliberate inadmissible citation is penalized and the no-evidence case abstains. Its score demonstrates arithmetic, not model quality.
5. State the still-open historical evidence gate and next planned equal-input comparison. Do not imply a trained classifier or investment accuracy.

Screenshots are local QA only; no paid UI service or public hosting is used. Current browser verification: installed Edge rendered all five sections and local links resolved. Generated assets are reviewed/published separately under results/candidates/presentation_demo_20261121/; raw model logs are never included.

The comparison_protocol.json file is a draft data/evaluation contract, NOT a frozen or executed experiment. The actual comparison must publish packet/prompt/gold hashes and preserve failed cases before making any performance claim. The minimum presentation deliverable does not depend on a positive model uplift.

Independent Claude review: fixed identical abstention permission in both arms; added second blinded adjudication and agreement/disagreement reporting; pinned the saved handoff receipt by canonical hash and original commit; expanded protected output paths. The pinned receipt prevents silent alteration of replayed metadata but is not independent third-party verification of live execution. Data input hashes intentionally cover exact checkout bytes; source hashes normalize LF. Byte-identical builds were tested with identical checkout inputs, not claimed for arbitrary Git newline conversions.
