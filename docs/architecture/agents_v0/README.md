# Agent v0.1：逐角色设计与实际接入状态

先看此页。沿用原 workflow，不是再增加一组随意扮演的角色。

角色规格已写出；不代表每项都已成为独立模型 agent，也不代表效果已验证。

|角色/模块|接入状态|
|---|---|
|[Lead investor / 研究调度](lead.md)|WIRED: model call|
|[Research specialist protocol / 专项研究](research.md)|PARTIAL: provider dispatch WIRED; autonomous specialist-model backend NOT WIRED|
|[Pro argument agent / 正方](pro.md)|WIRED: reused model stage|
|[Contra argument agent / 反方](contra.md)|WIRED: reused model stage|
|[Pro/contra critics and refinement / 质疑与修订](critic.md)|WIRED: two side-specific critics, then two refinement stages|
|[Argument evaluator / 论点评估](evaluator.md)|WIRED: model scoring plus deterministic selection|
|[Evidence reviewer / 证据缺口审查](evidence_review.md)|WIRED: project model call|
|[Final aggregation, synthesis and partner / 最终输出](thesis.md)|PARTIAL: aggregation/finish WIRED; rich thesis synthesis SPEC_ONLY; partner HUMAN|
|[Temporal and identity gateway / 日期与实体验证](gateway.md)|DETERMINISTIC: not an agent|

## 实际工作流

Partner mandate -> lead chooses questions/roles -> provider research -> historical
gateway -> shared admitted facts -> pro/con -> critics -> evaluator/refinement ->
evidence reviewer sees debate trace -> either lead follow-up or final aggregation
-> human partner. Research provider is not yet a universal autonomous researcher.

## 本次新增

- Versioned project prompt module, shared guard and seven role briefs wired to lead.
- Evidence-review prompt receives actual debate/critic stage trace, not only facts.
- Research cache keys include prompt-body fingerprint and retained vendor bodies,
  even if a caller forgets to change the manual prompt_version string.
- Separate rich specialist research and thesis-synthesis specifications from code
  that is actually implemented. No vendor prompt bodies or licenses overwritten.

## 可复现检查（无 API）

```powershell
$env:PYTHONPATH="src"
python -m closed_loop.agent_prompts
python -m unittest discover -s tests -p test_agent_role_prompts.py -v
```

Windows async tests require local loopback IPC. They use OfflineSocketGuard to
block external networking; a restrictive shell can stall the Windows event loop.
The test backend is synthetic, not a new real-company or live-model run.

[Existing v0 mapping](../agent_v0_adaptation.md) ·
[Reuse manifest](../agent_v0_reuse_manifest.json) ·
[Team handoff and validation](../../updates/2026-11-11-agent-v0-team-sync.md)

Pending: structured mandate, autonomous specialist model/tool loop and richer
thesis output; separately versioned real-company smoke test with current budgets.
OpenAI total new spend belowUSD1 is already authorized; none used here.
