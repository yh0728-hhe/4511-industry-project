# Composite Y snapshot / 綜合 Y 快照

As of 2026-11-18: **164/240 observed (68.33%)**, comprising 153 financing observations and 11 additional status observations; **76 UNKNOWN**.
截至 2026-11-18：**164/240 有結果證據（68.33%）**，其中融資153家，另有11家狀態證據；**76家 UNKNOWN**。

This measures outcome evidence availability, NOT investment success. Shutdown observations are adverse outcomes but count as observed. UNKNOWN must not become a financing-negative or failure label. This reviewed candidate snapshot does not replace a frozen training dataset automatically.
本表衡量結果證據覆蓋率，不代表投資成功率。關閉屬負面結果，但計為有觀測；UNKNOWN 不得轉為未融資或失敗。本候選快照不會自動取代已凍結的訓練資料。

## Definition and windows / 定義與時間窗

Composite Y is the company-level union of qualifying financing, reviewed shutdown, reviewed secondary business cessation, or established silence-rule presumed death. Current status-only observations: 2 first-party shutdowns and 9 secondary cessation records; no silence-rule cases qualify. Acquisitions or current active/closed badges alone do not establish a qualifying historical result.
綜合 Y 按公司去重，合併合格融資、已核准關閉、二手停止營運證據及已成立的沉默規則；目前額外11家包括2家第一方關閉與9家二手停止營運，沒有沉默規則個案。僅收購、目前活躍或關閉標籤不足以證明歷史結果。

Decision cutoff: 2024-04-04. Inclusive SEC issuer first-sale window: 2024-04-05 through 2026-04-04; filing/signature dates and indirect fund/SPV first sales do not substitute for issuer sales. Non-SEC financing report window: 2024-04-05 through 2026-07-04, including the approved reporting grace. Status cutoff: 2026-04-04.
決策截止2024-04-04；SEC 發行人首次出售日窗口為2024-04-05至2026-04-04，申報日、簽署日及間接基金/SPV 日期不得替代。非 SEC 融資報道窗口為2024-04-05至2026-07-04，包含已核准寬限期。狀態截止2026-04-04。

Dates retain source semantics; publication dates do not prove closing dates. Provider dates are used as reported, with unresolved conflicts retained in the source review. Explicit month precision qualifies only if the whole month is inside. Specific secondary financing reports may qualify; cumulative funding totals, grants, prizes, credits, investor lists and recycled older reports alone do not establish a new qualifying round. Identity-conflicted and SPV-only evidence is held.
日期保留來源語義，發布日不證明成交日；供應商日期按原記錄使用，衝突保留於來源審核。明確到月的記錄需整月落窗。具體二手融資報道可採納；累計金額、補助、獎金、點數、投資人名單及舊報道轉載本身不成立新輪次；身份衝突及僅有 SPV 的證據暫緩。

## Files and limitations / 檔案與限制

`composite_y.csv` contains 240 company rows; `manifest.json` records totals, source revision and CSV SHA-256. `preferred_*` fields may be empty where upstream has no selected preferred record. Source URL collections include reviewed historical leads, not only admitted events: do not re-label a company from a URL or aggregate date alone. Provider/secondary records and user-transferred browser reviews are not uniformly independently verified primary announcements. This is a derived snapshot, not complete funding histories or raw provider data. Wuri is a secondary news cessation report available by 2025-07-29, not an exact shutdown date or a first-party declaration. Sonia retains conflicting provider dates for the same reported seed financing; no distinct additional round is asserted.
CSV 包含240家公司；manifest 記錄統計、來源版本及雜湊。上游未選定首選記錄時 preferred 欄位可空白。來源連結集合含歷史線索，不等於每條都採納；不得只按連結或彙總日期改標籤。供應商、二手及使用者轉交瀏覽審核並非全部已獨立核對第一方公告。本檔是衍生快照，不是完整融資史或原始供應商資料。Wuri 為2025-07-29前可見的二手關閉報道，不是精確關閉日或第一方聲明；Sonia 同一筆種子輪保留供應商日期衝突，未主張額外新輪次。

Run `python data/team_snapshot_20261118/validate_snapshot.py` offline from the repository root. The validator verifies IDs, union counts, labels and file integrity; it does not independently re-verify source pages. Earlier snapshots remain historical records.
從倉庫根目錄執行上述指令，可離線核對 ID、聯集統計、標籤及完整性；驗證器不重新核驗網頁。舊快照保留為歷史記錄。

Prepared within RoseYu's research/data contribution with AI assistance; no claim of sole project authorship.
由 RoseYu 的研究及資料工作範圍整理，使用 AI 協助；不主張整個專案由個人獨立完成。

PromptArmor: explicit Prospeo Funding Date2024-05-03 is admitted as a provider-reported financing date; raw Round3 is not interpreted as a stage. USD3.2M selected, USD500K same-date row and prewindow dates remain conflicting records. No independent closing or additional-cash confirmation.
PromptArmor：採納 Prospeo 明列的2024-05-03融資日期，原始 Round3 不解讀為階段；選定320萬美元記錄，保留同日50萬美元及窗口前日期衝突，不主張已獨立核實成交或額外新增資金。

Prospeo shared-date quality flag: Topo, PromptArmor, MathDash/Breez Labs and Kabilah all display Funding Date2024-05-03. Accepted consistently as provider-reported records; no article links or independent closing confirmation. A shared date may indicate correlated data risk but does not prove ingestion/default dating. Excluding all four as a sensitivity view yields160/240 (66.67%); this is NOT the official count. Celest remains UNKNOWN because the previously recorded OOB date has unresolved business-continuity/pivot conflict; repeating the dated row does not resolve that hold.
Prospeo共同日期品質標記：上述4家公司均顯示2024-05-03，按相同供應商日期口徑採納，缺少文章連結及獨立成交驗證。共同日期提示相關資料風險，但未證明是入庫或預設日期。若敏感度分析排除4家，覆蓋為160/240（66.67%），並非正式統計。Celest既有OOB記錄仍有業務延續／轉型衝突，維持UNKNOWN。

Portability fix (2026-11-19): CSV is stored as UTF-8/LF; the manifest hashes LF bytes and the validator normalizes CRLF checkouts before hashing. Content modifications still fail integrity checks. TrueClaim gains a separate June12,2024 KAYA investor disclosure; all240 Y labels and coverage totals remain unchanged.
可攜性修正（2026-11-19）：CSV統一UTF-8/LF，manifest採LF雜湊；校驗器先正規化CRLF，內容變更仍會校驗失敗。TrueClaim新增獨立投資人披露，240家公司Y標籤與覆蓋率不變。
