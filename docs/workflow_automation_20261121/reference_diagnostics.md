# External reference diagnostics

The project reuses Ragas faithfulness instructions through its existing bounded model binding. It does not reproduce the whole Ragas package or certify investment recommendations. Engineering regressions and agreement with external annotations answer different questions.

The initial three SNLI cases shared a premise. A separately frozen six-premise expansion matched5of6external annotations; the disagreement concerned a commonsense inference absent from literal source wording. The result and all original cases are retained, without prompt tuning or retry. Known public caption data is not an unseen holdout or startup benchmark.

## RAGTruth reference slice

[RAGTruth](https://github.com/ParticleMedia/RAGTruth), described by [Niu et al.,2024](https://aclanthology.org/2024.acl-long.585/), supplies RAG responses with manual unsupported-span annotations and their source contexts. The pinned source revision is c103204b9ce28d6bbad859304bf30de72b8ed8fe. Both original JSONL files were checked against Git blob IDs and SHA256. Repository code is MIT; embedded webpage rights are not independently certified and raw passages are not redistributed in this repository.

Preparation scans original file order, only good-quality test QA responses within fixed UTF8 limits, taking the first three zero-span and three nonempty-span cases with six distinct source IDs. Any original annotation, including implicit_true (factually true outside the supplied context), maps to not fully supported for this declared source-grounding diagnostic. This response-level mapping is not the paper's full word-span evaluation or an official benchmark replication. The six IDs and selection rules are frozen before predictions.

Three standard-library scripts separate the stages. Preparation writes canonical UTF8/LF model inputs and a separate reference file. Prediction accepts only case ID,source ID,question,context,response and never opens the gold file. Its existing backend has no tools, a shared18-call/360-second ceiling and no source HTTP. First failure preserves completed,failed and not-run cases without retry. Only after the prediction process exits does the offline grader load frozen reference labels; it refuses missing cases, hash/protocol mismatches, inconsistent predictions or a changed grader. Incomplete runs receive no group agreement metric.

From the repository root, set PYTHONPATH=src for prediction. These are reproduction templates, not instructions to repeat sealed experiments with a fresh directory. A distinct later experiment must declare its purpose and ceilings before execution.

```powershell
python scripts/experiments/ragtruth_reference_prepare_20261126.py --responses RESPONSE_JSONL --sources SOURCE_INFO_JSONL --output-dir NEW_CASE_DIRECTORY
python scripts/experiments/ragtruth_reference_predict_20261126.py --inputs SELECTED_INPUTS_JSON --protocol FROZEN_PROTOCOL_JSON --output-dir NEW_RUN_DIRECTORY --approve-cli
python scripts/experiments/ragtruth_reference_grade_20261126.py --predictions RUN_RESULT_JSON --gold SELECTED_GOLD_JSON --protocol FROZEN_PROTOCOL_JSON --output NEW_REPORT_JSON
```

These scripts fetch no dataset, install no package and perform no training. Raw reference files remain private local artifacts. Source observation time belongs to this external reference task; the company-history cutoff remains2024-04-04T23:59:59Z. Public reference cases may already be in the model's training data; no causal information exclusion or general evaluator accuracy follows from six cases.

Before live execution:14new fake regressions; full readiness1,055tests(1,052passed,3skipped), six stages passed. Preparation reproduced the earlier selected six cases exactly. Real prediction and reference agreement are recorded separately when actually run.


## Frozen RAGTruth run result

Protocol RAGTRUTH-QA-SUPPORT-20261126-001 was frozen at e5f24b2 before predictions. The run used18actualCLI attempts in240.094seconds and reached its physical process ceiling:5cases completed,1failed,0dropped. The measured statement/NLI batch counts would require19calls for the whole group. The ceiling was not increased and the failed case was not rerun. Offline grading retained all6cases and produced INCOMPLETE_NO_GROUP_AGREEMENT; no whole-group accuracy or agreement score is reported. This was a planned local cap, not a provider token-quota rejection.

All18recorded model inputs were checked for annotation field exclusion; source/case/script hashes were reverified. This does not establish absolute information isolation from a public dataset that may be in model pretraining. A separate existing SNLI sample remains5of6matched; the two datasets are not pooled into an accuracy claim. Receipt: data/metadata/workflow_20261121/ragtruth_reference_result_20261126.json.

## Planned distinct exploratory whole-response arm

A new arm reuses the existing Ragas NLI instruction with each entire supplied response as one statement. It omits statement decomposition and therefore answers a different, coarser question: whether the whole response is supported. It is not the official Ragas faithfulness metric, does not produce atomic-claim recall and is not a production replacement. Same six source/response inputs, same model alias and external span-label mapping; maximum6physicalCLI attempts,0sourceHTTP,240seconds, no retries or cap reset. Each case has one intended NLI call; malformed exact-copy/verdict output stops and preserves remaining cases.

This arm was proposed after the decomposed run and its case-level results were available. It is exploratory and not an independent holdout or pre-registered confirmatory comparison. Any later agreement must report all six cases, failures and null group score on incompletion. No superiority or general accuracy claim follows. The original incomplete run remains unchanged. A separate protocol with code/input/reference/grader hashes must be committed before any real prediction; separate offline grading follows child exit. As of this entry, the new arm has not run.

### Whole-response arm result

Protocol frozen at372882e, source732403a. All6cases completed using6actualCLI attempts in78.354seconds (parent wall time),0sourceHTTP. Offline grader ran after prediction exited and found6of6matches with the declared span-to-response mapping:3true-positive and3true-negative,0false-positive/negative on these six cases. Constant not-supported matches3of6. All frozen source/input/gold hashes reverified; all6saved stdin records checked for reference-label field names. Raw prompts, contexts and outputs remain private; curated receipt records their hashes.

This is an exploratory public-data diagnostic designed after the earlier arm. Whole-response judgment is coarser than atomic decomposition, with no unsupported-claim localization. Prior arm used18attempts and stopped incomplete; its group score remains null. Different task granularity and completion prevent a controlled latency/cost/quality superiority claim. No general accuracy, unseen-holdout, investment quality or final-gate validation follows; no model training, production replacement or Y change occurred. Receipt: data/metadata/workflow_20261121/whole_response_result_20261126.json.


## Source-ID-disjoint12case follow-up (prepared before new predictions)

Reuse the pinned raw RAGTruth files and prior mechanical selector twice: exclude all six old sourceIDs; first take3reference-supported+3unsupported cases in original order, exclude those sources too, then take the next3+3. The12cases have no old sourceID or exact context hash overlap. This does not prove independent underlying topics, unseen pretraining or representative startup evidence. The new selector, prediction process and offline grader are separate. The predictor reuses the existing unchanged whole-response NLI helper and never opens reference labels. Source code and12caseorder are frozen before predictions, with12physicalCLI attempts,240seconds,0sourceHTTP and no retries; all12remain in the ledger on failure. Gold grading only after child exit. Any incomplete group has null agreement. This is not official Ragas atomic-statement faithfulness and does not replace main workflow or company-quality reference facts. As of preparation, no new predictions have run.


### Twelve-case follow-up result

Source0c17c06, protocol frozen atff31ae1. All12newcases completed with12actualmodelCLI attempts in137.093seconds parent wall time,0sourceHTTP. Separate offline grading after prediction exit found11of12reference agreements:5TP,6TN,0FP,1FN under the declared source-support mapping. Constant not-supported matches6of12. All code/input/reference hashes reverified and12saved stdin records checked for reference fields. Labels, prompt and cases were not changed or retried.

Case ragtruth-response-12330 is the sole disagreement: the supplied annotation accepts a generalization across gendered wording, while the model requires more literal support for the reframed subject. This shows possible excessive abstention; neither side is newly certified as universal truth. Retain it as a diagnostic, not an excuse to relabel the reference or tune this example. The new group is reported separately from the initial6case exploration, never pooled into an accuracy claim. Known publicQA cases and sourceID/context-hash exclusion do not establish pretraining exclusion or representative company diligence. Main workflow, Y and training unchanged. Receipt: data/metadata/workflow_20261121/followup_reference_result_20261126.json.
