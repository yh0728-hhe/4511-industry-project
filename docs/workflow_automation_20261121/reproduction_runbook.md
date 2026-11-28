# 複現操作手冊（私有分支）

本文件記錄**已驗證的現狀**，不是承諾或新功能說明。第1節是離線檢查；第4節是真實CLI入口，會消耗模型與搜尋額度。
本文件本身不執行任何指令。

## 1. 離線可重跑：readiness 六步驟

在倉庫根目錄 PowerShell 執行：

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'src'
python -X utf8 -m workflow_automation.readiness --run-id teammate-offline-20261126-01 --max-seconds 180
```

- run-id 必須是**全新、唯一**、最多64字元、僅英數字/底線/連字號的字串（例如含日期與用途），不要重用既有run-id，
  既有結果不會被覆寫。
- 失敗/中斷可用 `--resume` 續跑，它會核對原始碼指紋與已完成產物雜湊。
- 日誌/檢查點輸出在被忽略目錄 `results/scratch/workflow_20261121/`（不入庫）。
- 六個固定步驟：runtime迴歸、融資迴歸、狀態（outcome）迴歸、可攜快照（Y）完整性、
  合成閉環範例、Adagy僅產生計畫的預檢。
- 最近一次有記錄的總計：1,108項測試，1,105通過、3跳過，六步驟皆通過
  （見PROGRESS.md）。**這是工程整合/迴歸驗證結果，不是模型品質或投資判斷的證據**；
  通過代表程式碼路徑可重複執行，不代表模型輸出準確。

## 2. 歷史截止 vs 外部基準測試時間，不要混用

- 公司歷史資料的截止時間固定為 `2024-04-04T23:59:59Z`，用於限制歷史研究/爬取範圍。
- RAGTruth/SNLI等外部來源基準測試是在2026-11-26執行的，其"觀測時間"屬於這個外部
  診斷任務本身，與歷史截止時間是兩件不同的事，不要互相引用佐證。

## 3. 凍結的Y標籤：不是訓練目標

目前240家公司的標籤狀態（見PROGRESS.md）：composite 164/240、financing 153/240、
unknown 76。UNKNOWN不等於沒有融資或公司失敗。這些是**已觀察到的覆蓋情況**，不是：
- 訓練用的目標/標籤定義（尚未定義fitting目標與holdout）；
- 模型準確率或投資表現的證據；
- 76個UNKNOWN不是負例，只表示依目前口徑仍無可採納的結果證據。

## 4. 主要動態 discovery workflow（有既有防護的CLI）

這是**既有**的指令入口，僅在你已準備好自己的config、且確定要消耗真實CLI額度時才執行：

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH='src'
python -m closed_loop.discovery_workflow --help
```

- 入口接受 `--config CONFIG.json --output-dir NEW_DIRECTORY --approve-cli`。
  先針對新研究目的準備自己的配置與明確上限；範例檔是已研究過的Hatchet，
  不要直接執行範例而重跑封存實驗。
- 缺少 `--approve-cli` 或帶 `--help` 時不會發出任何auth/網路/模型呼叫。
- `--output-dir` 必須是新的、未使用過的目錄。
- 真實執行會消耗該次CLI的呼叫上限（模型/搜尋/時間預算），且封存檔案（archive）
  是否可取得不受你控制；即使有更多預算，也不保證能找到更多證據（結果可能停在
  MORE_DILIGENCE / NO_NEW_EVIDENCE / NO_ADMITTED_FACTS）。
- 本流程**不**包含：訓練、新增key、排程器、自動喚醒、或修改Y欄位。

## 5. 獨立「整段回答」支持度診斷（whole-response arm）：已完成，探索性質

- 已完成一次獨立執行：6次實際CLI呼叫，耗時78.354秒，6/6案例完成，對照6個公開
  RAGTruth標籤全部相符（3真陽性、3真陰性，0誤判）。見
  `data/metadata/workflow_20261121/whole_response_result_20261126.json`。
- 這是在先前18次呼叫的分解式（decomposed）跑法已知結果之後，**事後**設計的探索性
  實驗，不是預先註冊的獨立驗證組，**不構成一般準確率聲稱**（僅6個刻意挑選的公開
  案例，非未見過的holdout）。
- 先前18次呼叫的分解式跑法在達到CLI呼叫上限後**仍未完成**（5完成、1失敗），
  其結果維持 `INCOMPLETE_NO_GROUP_AGREEMENT`、不重跑、不恢復(resume)、不重試失敗案例。
  兩個實驗粒度不同（整段回答 vs 原子陳述），不可互相比較優劣。

## 6. 已封存（sealed）的歷史實況執行：只能查收據，不要重放指令

以下執行**已經實際發生並封存**，你的任務是檢查其收據/雜湊，而**不是**重新發出它們
的現場指令（無論目錄是否全新）：
- 來源豐富的動態研究/辯論/支持度檢查/追問循環：23次CLI呼叫、431.369秒，
  MORE_DILIGENCE / NO_NEW_EVIDENCE。
- 單指令稀疏來源跑法：2次CLI呼叫、35.134秒，NO_ADMITTED_FACTS。
- 原始18次呼叫分解式RAGTruth跑法：見第5節，不完整且不重跑。
- 先前主線來源稽核（main source audit/completion audit）逾時120.540秒，**沒有**
  獲得任何獨立核准，維持逾時狀態，不代表拒絕也不代表通過。

複現這些歷史結果的**正確方式**：讀取對應的 `data/metadata/workflow_20261121/*.json`
收據與其中記錄的雜湊，依收據指定的歷史提交核對程式碼/輸入雜湊（不是用目前HEAD取代當時版本）；**不要**重新執行
它們當時呼叫的CLI指令。

## 7. 本機token支持度guard：僅結構檢查，沒有裝模型

見 `data/metadata/workflow_20261121/local_token_support_contract_validation_20261126.json`：
- `local_detector_installed: false`，`local_detector_executed: false`。
- 這是**純stdlib的結構契約檢查**（42個focused測試通過），**沒有**安裝或執行任何
  本地檢測模型，**沒有**token offset bridge。
- 不要以此宣稱本機已具備模型推理能力或可替代線上判斷。

## 8. 不包含的事項（明確排除）

- 不做模型訓練、不新增API key、不建立排程器/常駐服務、不做自我喚醒。
- 不修改Y/outcome欄位。
- 不代表程式碼可透過pip安裝、不代表有OS層級的沙箱隔離、不代表已部署到雲端。
- 本文件不含投影片/demo腳本，僅供復現操作。

## 9. 不變的守門

來源驗證（source gates）與最終審核（final review gates）邏輯未變；主線來源稽核的
逾時狀態沒有獨立核准覆蓋它。任何真實現場執行前，先確認：run-id全新、output-dir
全新、你清楚本次會消耗多少CLI額度。
