# Pro argument agent / 正方

**WIRED: reused model stage**

## Task / 任务

Build strongest evidence-supported investment case under the mandate; distinguish facts and assumptions, not a final trade decision.

## Inputs and outputs / 接口

Input: Same admitted indexed QA/fact base as contra, mandate and cutoff supplied by NativeBinding.

Output: ArgumentsOutput -> cited Argument objects; qa_indices must be valid admitted evidence indices.

## Tools / 工具

No retrieval, source admission or database access.

## Action loop and handoffs / 行动与交接

Generate pro arguments -> critic -> scored selection -> refinement; evidence gaps handled by evidence reviewer/lead.

## Stop and failure rules / 停止与失败

NativeConfig bounds argument count and iterations; structured output/citation validation and shared model budget.

## Actual prompt and code / 实际 prompt 与代码

Code: `vendor/dialectic_committee_nodes.py:generate_pro_arguments; native_committee.py`.

The full retained prompt or deterministic function is in [the unchanged upstream stage module](../../../src/closed_loop/vendor/dialectic_committee_nodes.py) or [decision module](../../../src/closed_loop/vendor/dialectic_decision.py), at the exact function(s) named above. The project system prompt wraps model stages through `NativeBinding.messages`; deterministic components have no prompt.

See [versioned project prompts](../../../src/closed_loop/agent_prompts.py), including the common historical guard.

## Reuse and project changes

DIALECTIC MIT prompt body retained. Project adds historical system guard, typed citations, metering and handoff context.

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
