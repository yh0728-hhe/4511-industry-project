# Pro/contra critics and refinement / 质疑与修订

**WIRED: two side-specific critics, then two refinement stages**

## Task / 任务

Attack weak causal claims, unsupported assumptions and contradictions in each argument. Revision must not invent facts.

## Inputs and outputs / 接口

Input: Argument, admitted indexed QA and mandate; opposite-side target chosen by existing vendor functions.

Output: ArgumentCritique. Refiner yields IndividualRefinedArgumentOutput(content,qa_indices).

## Tools / 工具

No search tools; criticism is analysis, never a newly admitted fact.

## Action loop and handoffs / 行动与交接

Critique each side -> evaluator/select -> refine -> preserve stage snapshots; snapshots now explicitly sent to evidence review.

## Stop and failure rules / 停止与失败

Bounded by NativeConfig iterations, semantic validity remains unproven; invalid/empty critique or citations stop.

## Actual prompt and code / 实际 prompt 与代码

Code: `vendor/dialectic_committee_nodes.py:_apply_devils_advocate_to_pro_argument / _apply_devils_advocate_to_contra_argument / _refine_individual_pro_argument / _refine_individual_contra_argument`.

The full retained prompt or deterministic function is in [the unchanged upstream stage module](../../../src/closed_loop/vendor/dialectic_committee_nodes.py) or [decision module](../../../src/closed_loop/vendor/dialectic_decision.py), at the exact function(s) named above. The project system prompt wraps model stages through `NativeBinding.messages`; deterministic components have no prompt.

See [versioned project prompts](../../../src/closed_loop/agent_prompts.py), including the common historical guard.

## Reuse and project changes

Retained upstream critique/refine prompts; NEW project debate_trace handoff to evidence review.

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
