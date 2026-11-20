# Original 13 funding dates and source timing review

Prepared November 19, 2026, for Yi-Nung's weekly project contribution, with AI-assisted implementation and source review. The input is Rose Yu's November 11 derived snapshot; upstream research and attribution remain preserved. Full [audit files](../../data/weekly_audit_20261119/README.md) and the [offline generator](../../scripts/audit_funding_dates.py) are committed separately from the historical agent input.

The source review completed a first inspection of all 13 company records. **It did not recover the original announcement date and precision of any of the 13 provider rounds.** Most stored links are provider round pages rather than original company/investor announcements. Eleven leads display `2026-01-01`; that string alone does not distinguish a day from normalized month/year precision. Original-announcement URL/date/precision therefore remain blank/UNKNOWN, with each failed or insufficient read documented rather than silently treated as evidence.

## Company-by-company disposition

| Company at decision | PR #3 lead date | First-party/source result this week | Strict-window disposition |
| --- | --- | --- | --- |
| Agentic Labs | 2026-01-01 | Company homepage read; backing section has no financing date; provider page unavailable. | Original round undetermined. |
| Arcane | 2026-01-01 | Company domain unavailable; YC current profile is not a dated financing announcement. Marketing-software company with the same name must not be merged. | Original round undetermined. |
| Arini | 2026-05-11 | Caplight directly displays this day and a separate April 30, 2024 seed row; underlying sources locked. Company page gives no dated financing announcement. | May lead is outside strict endpoint, inside end-boundary review band. No grace-window admission here. |
| Artos | 2026-04-01 | Current company material names investors; November 18, 2026 product release gives no qualifying financing date. Original provider page unavailable. | Date precision unreported, end-boundary review required. |
| CommodityAI | 2026-01-01 | Company homepage read; no dated financing announcement in inspected content. | Original round undetermined. |
| Haplotype Labs | 2026-01-01 | Company names YC without a date. Issuer Form D independently read: first sale March 29, 2024. | SEC offering is outside window, near start. Original provider round remains undetermined; no company-level negative. |
| Marblism | 2026-01-01 | Company homepage and news text inspected. Crunchbase page's Announced Date is obfuscated; Recent News has Jan 1, 2026 but no readable article. | News display date is insufficient to establish round date or precision. |
| OpenFoundry / Overheard | 2026-01-01 | Company domains unavailable; YC explicitly establishes the former name and a September 2026 product pivot, without a financing date. | Original round undetermined. |
| GoldenBasis / Polar | 2026-01-01 | Original domain unavailable; current site exposed only iframe. YC confirms founder/product identity context. Secondary month dates conflict. | Original round undetermined. |
| Terrakotta | 2026-01-01 | Company homepage has YC backing without a financing date. | Original round undetermined. |
| TrueClaim | 2026-01-01 | Independently read investor KAYA newsletter dated June 12, 2024, under new investments; matching founders and $2.1M pre-seed linked. | Separate company-level disclosure added; original 2026 provider round date remains undetermined. |
| Upsolve AI | 2026-01-01 | Company about page gives no round date; HubSpot page describes a pitch-competition win. | Prize/competition amount is not assumed equity financing. |
| Yarn | 2026-01-01 | Company domain unavailable; YC founder post describes product launch. Conflicting provider April 1, 2024 row has no article. | Original round undetermined. |

The resulting strict public-disclosure **candidate is 103/240 (42.9167%)**, one company above the carried-forward baseline of 102/240. Twelve of the original 13 companies still lack strict-window disclosure evidence. Issuer SEC first-sale coverage remains 12; verified company financing negatives remain zero. PR #3's composite coverage is a separate definition and is not substituted into these counts.

## What each source date means

| Source/field | Meaning to retain | Treatment in this audit |
| --- | --- | --- |
| SEC issuer Form D, Date of First Sale | First investor's irrevocable contractual commitment to invest, according to SEC guidance. It is neither the filing date nor proof of final round closing. | Keep a separate transaction dimension. Read issuer identity and first-sale field. Filing/signature dates and indirect funds/SPVs cannot replace issuer first sale. |
| SEC filing date | Date the notice was filed, a separate disclosure/administrative timestamp. | Never substitute for the offering's first-sale date. A 15-day filing deadline does not prove every filing is timely. |
| Company or investor dated release | Date that first party publicly discloses the reported financing/investment. | Preserve publication date and precision; require the whole interval inside the strict disclosure window. This does not independently establish transaction date. |
| News/media article | Publication or updated timestamp of an article, unless its text explicitly establishes a different event date. | Record publication and event dates separately, retain update/republication ambiguity. No global lag subtraction. |
| Crunchbase `announced_on` | Public-announcement date in Crunchbase's funding-round schema; not a guaranteed transaction date. | Preserve provider date and available precision. Public pages may obfuscate it, and the shared snapshot omits precision. No precision inference from `YYYY-01-01`. |
| Crunchbase `closed_on` | Separate provider close-date field with precision; requires usable entitled API access and an actual returned field. | Do not infer it from `announced_on` or claim it was returned when API access fails. |
| Caplight/other provider round date | Date as labeled by that provider; underlying article/transaction semantics may be unverified. | Store as provider-reported round evidence. A visible day establishes the provider display, not the actual transaction or original publication date. |
| Current profile/backing badge/cumulative total | Current profile or cumulative context; no necessarily dated new round. | Identity/research lead only; not a new qualifying round by itself. |

The [SEC Form D FAQ](https://www.sec.gov/about/divisions-offices/division-corporation-finance/frequently-asked-questions-answers-form-d) supplies the first-sale definition and filing requirement, and expressly discusses late filings. The [Crunchbase funding-round reference](https://data.crunchbase.com/reference/getfundinground) and [data dictionary](https://data.crunchbase.com/docs/data-dictionary) distinguish announcement and close dates. These are schema semantics, not independent verification of any company row.

Direct primary observations: [KAYA June 12 newsletter](https://newsletter.kaya.vc/ceefarers-jun-2024/) and [Haplotype issuer Form D](https://www.sec.gov/Archives/edgar/data/2017857/000201785724000001/xslFormDX01/primary_doc.xml). The latter directly reports first sale March 29; the FormDS mirror separately reports filing April 16. That filing metadata is not used for a positive transaction label. The TrueClaim newsletter's financing context supports disclosure admission; correspondence with the ambiguous 2026 provider record is **not established**. No duplicate-round or incremental-cash claim follows.

## Boundary review and remaining questions

The reproducible review bands are January 5–July 5, 2024 around the start, and January 4–July 4, 2026 around the end. Month/year intervals are checked for overlap, with unreported precision conservatively widened to the whole reported year. The stored displayed date gives **60 evidence rows for 55 companies** near a boundary; including uncertainty-expanded intervals yields **102 rows for 84 companies**. `boundary_cases.csv` distinguishes the two. Baseline URLs are company-level source collections; the audit does not invent one-to-one URL/date pairing.

Three months is a **manual-review heuristic**, not an estimated source-specific lag, an automatic reporting grace, or permission to move an outside date inside the strict window. We have no matched, independently verified transaction/announcement pairs sufficient to estimate a lag distribution this week. The one independently read SEC first-sale record is outside the window and is not matched to the ambiguous provider row.

Open question for Jeff: what evidence supports the approximately three-month lag figure, what population/source types does it cover, and should it be a review band or a formally approved separate reporting-window rule? Retain the user-reported wider case range as unmeasured context, not an estimated statistic.

Eight regression tests cover year ambiguity, whole-month attribution, inclusive boundaries, leap/calendar-month arithmetic, invalid dates, exact cohort/13-ID matching, rejection of transaction/undated evidence as primary disclosure, and preservation of separate transaction/negative labels. The generator rebuilds offline; manual source reading is not reproduced by those tests.

中文：本週完成13家公司第一輪逐筆查核，但未補出13筆原供應商輪次的精度，維持未定。另找到TrueClaim在2024-06-12的投資人披露，嚴格窗口披露候選數103/240；這不證明成交日，也不解決原2026記錄。三個月只作邊界人工複核；交易、披露與未知標記分開保存。
