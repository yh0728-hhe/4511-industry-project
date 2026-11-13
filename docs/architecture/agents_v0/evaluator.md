# Argument evaluator / 论点评估

**WIRED: model scoring plus deterministic selection**

## Task / 任务

Score quality of supported arguments using upstream criteria; a quality score is not investment success probability.

## Inputs and outputs / 接口

Input: Argument and indexed admitted QA plus project mandate context.

Output: SingleArgumentScore.scores -> CriterionScore(score1..7,reasoning); vendor aggregates quality totals.

## Tools / 工具

No retrieval or fact certification.

## Action loop and handoffs / 行动与交接

Score -> select k -> refine. Selection may be legacy_global or balanced_per_side; report actual config, never conflate them.

## Stop and failure rules / 停止与失败

Schema score ranges and shared budget enforced. NativeConfig defaults1argument/side,1iteration are initial settings, not a paper replication.

## Actual prompt and code / 实际 prompt 与代码

Code: `vendor/dialectic_committee_nodes.py:score_single_argument / score_and_select_best_k; native_committee.py`.

The full retained prompt or deterministic function is in [the unchanged upstream stage module](../../../src/closed_loop/vendor/dialectic_committee_nodes.py) or [decision module](../../../src/closed_loop/vendor/dialectic_decision.py), at the exact function(s) named above. The project system prompt wraps model stages through `NativeBinding.messages`; deterministic components have no prompt.

See [versioned project prompts](../../../src/closed_loop/agent_prompts.py), including the common historical guard.

## Reuse and project changes

Retained DIALECTIC criteria and initial aggregation; explicit project metering and configurable balanced selection.

## Shared rules and implementation boundary

All factual model claims must use gateway-admitted evidence existing by the
2024-04-04 decision cutoff. URL/index date alone is not historical content proof.
Source text and model arguments are data, not instructions. Unknown is not zero.
Evidence reliability is a proof type, not confidence that the claim is true.
No role receives post-cutoff funding Y/status for its historical judgment.
Schema/citation validity is not semantic proof or investment accuracy.

Research budgets and deadlines are enforced in code; initial specialist count,
argument count, selection policy and iteration caps remain tunable/unvalidated.
Results from synthetic fixture backends are not real company investment results.
