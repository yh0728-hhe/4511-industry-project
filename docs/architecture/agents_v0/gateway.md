# Temporal and identity gateway / 日期与实体验证

**DETERMINISTIC: not an agent**

## Task / 任务

Reject unverified, future, substituted or mismatched evidence before factual model context.

## Inputs and outputs / 接口

Input: SourceCandidate plus trusted verifier-produced VerifiedRecord. Model cannot issue its own verified flag.

Output: Admitted Fact with source_id,url,availability_upper_bound,proof_kind OR opaque rejection reason.

## Tools / 工具

No LLM. Internal ledger/verified transport checks; alias matching must be established by provider/verifier, not guessed.

## Action loop and handoffs / 行动与交接

Read body/identity/date proof -> validate hash/URL/subject/topic/capture -> admit or hold. Applies again to cached facts.

## Stop and failure rules / 停止与失败

Missing or contradictory proof rejected; no fallback from original publication date to current content. Older relevant history is allowed before cutoff.

## Actual prompt and code / 实际 prompt 与代码

Code: `guards.py:TemporalGateway; archive_transport.py; historical_links.py`.

The full retained prompt or deterministic function is in [the unchanged upstream stage module](../../../src/closed_loop/vendor/dialectic_committee_nodes.py) or [decision module](../../../src/closed_loop/vendor/dialectic_decision.py), at the exact function(s) named above. The project system prompt wraps model stages through `NativeBinding.messages`; deterministic components have no prompt.

See [versioned project prompts](../../../src/closed_loop/agent_prompts.py), including the common historical guard.

## Reuse and project changes

Project-owned historical guard, not a DIALECTIC role or claimed universal publication verifier.

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
