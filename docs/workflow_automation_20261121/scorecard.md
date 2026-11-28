# Frozen claim/citation scorecard

Purpose: make a later baseline comparison reproducible and reject misleading scoring. `src/workflow_automation/scorecard.py` reads independent gold and submitted extractions, never calls a model, retrieves a website, reads Y or trains anything.

## Contract
Both JSON inputs have version `claim-scorecard-v1` and a cases array. Gold cases contain unique case_id and facts arrays: each fact has unique claim_id within case, source_id, boolean admissible (independently reviewed). Submissions contain identical case IDs, explicit COMPLETED/ABSTAINED/FAILED status and claims arrays with claim_id/source_id. Missing cases or duplicates are errors, not ignored rows. An abstained/failed case cannot also assert facts.

Gold labels and claim IDs must be adjudicated independently, frozen and withheld from model prompts. The scorer does not create a gold dataset, verify the freeze's date or make arbitrary free text factual. A blinded adjudication stage must map model claims to canonical IDs without feeding answer keys back into the model. No empirical comparison has run through this module yet.

Metrics preserve numerator/denominator: exact reviewed claim-source pair precision, admissible claim recall, unsupported/wrong-citation rate, completion/abstention/failure, appropriate abstention on zero-admissible-claim cases, and excess abstentions on cases with evidence. A failed case contributes to the missed-claim denominator. A zero denominator returns null, not perfect accuracy. Different correct paraphrases or additional sources require independent adjudication, not automatic rejection as semantic falsehood.

Run with PYTHONPATH=src:
`python -m workflow_automation.scorecard --gold GOLD.json --submission PREDICTIONS.json --output NEW_REPORT.json`
Output is exclusive-create, cannot overwrite input or an existing report, and records both input SHA256 hashes. Structural scoring is NOT semantic entailment, source truth, verified finance negatives or investment accuracy. Per-arm usage, timestamps, physical calls and cost must come from separate run receipts; this scorer does not invent them.

Next deliverable: freeze an explicitly retrospective small evidence packet and a blinded rubric, then measure two model workflows on identical inputs and ceilings. Keep the historical prediction experiment blocked until historical source admissibility is justified. If a real-model comparison cannot be executed before presentation, present this as evaluation infrastructure plus deterministic regression verification, not measured model uplift.
