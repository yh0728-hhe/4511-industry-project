> Shared team review package (2026-11-26): run python scripts/verify_shared_workflow.py --output-dir results/scratch/shared-my-new-run --max-seconds 300. This profile verifies the workflow, portable Y snapshot, synthetic loop, plan-only preflight and injected integration without private provider data. The original full readiness command also runs legacy funding suites whose private inputs are not bundled here. Private1,108check results remain historical evidence, not the shared-profile count. Team legacy source modules are preserved from PR#4.

# Workflow automation checkpoint / 工作流程自動化進度

This branch integrates Yi-Nung's bounded historical research backend from team commit93259e48 with RoseYu's newer specialist/thesis runtime. Only selected source/tests/docs were imported; the older branch was not merged wholesale. Original authorship and vendor licenses are preserved. Codex implemented integration/orchestration; Claude Code independently reviewed via read-only local CLI, without executing tests itself.
本分支把Yi-Nung的歷史研究後端接入RoseYu較新的specialist/thesis流程，僅選取程式、測試與文件，未整枝覆蓋。保留原作者及授權。Codex負責整合與執行；Claude Code以本機CLI獨立唯讀審閱，未自行執行測試。

Latest verified progress: [PROGRESS.md](PROGRESS.md). Chinese teammate instructions: [reproduction_runbook.md](reproduction_runbook.md). Offline artifact audit: [saved_run_audit.md](saved_run_audit.md). A clean tracked export of ee5c762 reproduced all six offline stages without the original scratch directory; same host/Python, not OS isolation. See [the receipt](../../data/metadata/workflow_20261121/clean_export_reproduction_20261126.json).

## Current checkpoint / 目前進度（2026-11-26）

The source-rich discovery workflow completed an actual bounded cycle: dynamic specialist selection, managed search, historical source verification, committee argument/critique/refinement, Ragas-derived support diagnostics, factual-gap triage, and a new follow-up search. It finished MORE_DILIGENCE / NO_NEW_EVIDENCE after 23 observed CLI attempts in 431.369 seconds; only one repository context was admitted, with 14 questions unresolved. This is an engineering integration result, not accuracy evidence.

A separate actual single-command sparse-source run finished in 35.134 seconds with 2 CLI attempts, 2 direct archive requests, zero facts, and MORE_DILIGENCE / NO_ADMITTED_FACTS. A later-rebrand bookkeeping ID exposure was identified and fixed with neutral model-facing identifiers; the original run remains sealed and its limitation retained. Empty evidence now retains any remaining authorized research passes. Latest full readiness: 1,108 tests, 1,105 passed, 3 skipped; all six stages passed. The optional screen explicitly stops when it says MORE_DILIGENCE without specifying gaps. Optional registry discovery is default off; a bounded live test exercised dynamically found wheel verification, preliminary screen and follow-up, then stopped at its deadline. See PROGRESS.md for exact versions, counts and limits. No training or Y changes. No unattended background execution is implied.

Use [the guarded discovery command](discovery_workflow.md) for current execution instructions and [the latest correction log](../research_log/2026-11-25_identity_presentation_and_sparse_command.md) for limitations and contributions. Earlier sections below are the original integration checkpoint, not an instruction to repeat completed probes or revisit old gates.

## Run / 執行

From the repository root in PowerShell:
從倉庫根目錄執行：

```powershell
$env:PYTHONPATH = 'src'
python -X utf8 -m workflow_automation.readiness --run-id first-offline-run
python -X utf8 -m workflow_automation.readiness --run-id first-offline-run --resume
```

Six fixed stages run automatically: runtime regressions, funding regressions, outcome regressions, portable snapshot integrity, synthetic closed-loop examples, and an Adagy plan-only preflight. The entry point exposes no paid/live flag. Interrupted/failed stages stop the workflow; resume checks source fingerprint and completed artifact hashes. An existing run is never silently overwritten. Locks prevent concurrent writes; a stale lock after a hard process kill requires operator inspection, never automatic deletion. Source changes require a new run ID. Logs/checkpoints remain in ignored results/scratch/workflow_20261121, with selected reviewed receipts promoted separately.
自動執行六個固定步驟：runtime、融資、狀態測試、共享表完整性、合成閉環案例、Adagy僅產生計畫的預檢。此入口沒有付費或正式執行開關。失敗即停止；續跑檢查程式及輸入雜湊和已完成產物。既有結果不覆寫，鎖阻止同時寫入；強制終止遺留鎖需人工確認，不自動刪除。原始日誌留於忽略目錄，僅選定回執入庫。

This is an on-demand local automated workflow, not a newly installed scheduler, unattended service, external Muse wake-up API, or model training job. Tests use fakes and a Python-level network guard; this is not an OS sandbox guarantee. Engineering verification may inspect Y to validate exports; Y is not fed into model prompts, historical company selection or source retrieval.
這是本機按需自動流程，不是新建排程、常駐服務、Muse喚醒API或模型訓練。測試採假回應及Python網路防護，不聲稱OS隔離。工程驗證會核對Y，但Y不進入模型提示、公司選擇或歷史檢索。

## Historical checkpoint and current limits / 歷史檢查與目前限制

The original Adagy archive probe and the later Muse/Codex review are retained in [historical_gate_codex_review.json](../../data/metadata/workflow_20261121/historical_gate_codex_review.json). A dated March 5, 2024 article supports the Adagy name/domain association; it does not independently establish every identity field or an unchanged pre-cutoff website body. The later guarded command admitted no historical facts. Neither observation proves that no archive or funding exists. These are recorded limitations, not instructions to repeat sealed probes or wait for Muse before engineering can proceed.

Current engineering has executed a source-rich research/debate/support/follow-up cycle and two sparse-source commands. A separate fixed-evidence publisher comparison completed both arms (committee 11 CLI attempts; single analyst 1; both MORE_DILIGENCE). This is unequal-resource development evidence, not comparative accuracy. The posthoc support diagnostic stopped on call 6; no aggregate score is reported. See [PROGRESS.md](PROGRESS.md) and [the diagnostic receipt](../../data/metadata/workflow_20261121/posthoc_argument_support_result_20261126.json).

目前已實際執行有來源的閉環及資料稀少的命令流程；比較實驗與未完成的支持診斷均保留限制。沒有合格來源仍是未知，不是負例；工程開發不以等待人工複核為前提。

The imported one-company paid pilot remains plan-only and sealed-pilot protections are retained. It proposes at most24API attempts, USD0.20 reservations,6archive requests and8minutes. The integrated prompts change its fingerprint, so old approvals cannot be reused. A later execution needs approval of the actual current plan and a checked model rate card; no paid run was performed here. If archival identity/availability remains unresolved, hold rather than spend on an unsupported run.
匯入的付費試驗仍僅準備計畫，保留封存與預算防護。建議上限24次API、0.20美元、6次檔案請求及8分鐘。整合改變提示雜湊，舊核准不得沿用；此輪未執行付費試驗。歷史身份或檔案問題未解時先暫緩。

See evaluation_gate.json for why a supervised investment/funding classifier is not yet ready. Financing negatives0 is distinct from reviewed shutdown records: shutdown does not imply no financing; observation coverage is not success. Future targets and holdouts must be defined before fitting, and a smoke test cannot establish model quality.
訓練條件見evaluation_gate.json。融資負例0與已知關閉樣本不同；關閉不等於沒融資，覆蓋不等於成功。需先定義目標及保留集，單家公司試跑不證明模型品質。

Implementation notes: a subject-scoped visited-path fix prevents peer research from suppressing another company's same path; the live factory now binds physical request count to its run budget. Overlapping specialist/provider navigation loops are rejected explicitly. Full240-row identity projection is regression tested. The optional specialist/thesis modules remain available with their original compatible providers.
實作補充：已訪問路徑按公司隔離，避免同路徑跨公司誤判；實際API請求數跟隨運行預算。禁止兩層導覽控制器疊用，核對240家公司seed只含身份欄位；既有specialist/thesis模組保留。

Original integration validation (historical, not the current test count): Windows419tests,416pass/3skip; GitHubUbuntu push andPR jobs at0fa3dc9 both pass allsixstages and completed-run resume. CI history checkout is full for pinned source verification; legacy CSV determinism checks distinguish Git checkout newline conversion from changed content.
驗證：Windows共419項，416通過、3跳過；GitHubUbuntu的push及PR檢查均通過六步流程與續跑。CI保留完整歷史以核對固定提交；CSV檢查同時維持內容一致與連續重建位元組一致，不把換行差異當資料變更。
