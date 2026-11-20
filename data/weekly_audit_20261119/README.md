# Funding date review — November 19, 2026

This is a **reviewed candidate**, separate from the frozen November 11 snapshot and PR #3's broader composite Y. It contains outcome-label research, including information published after the decision date. **Do not expose this directory to the historical research agent or use it as X.**

| Measure | Result |
| --- | ---: |
| Frozen strict public-disclosure baseline | 102 / 240 (42.5%) |
| Strict public-disclosure candidate after this review | 103 / 240 (42.9167%) |
| New company with independently read investor disclosure | TrueClaim |
| Original 13 provider round dates precisely resolved | 0 / 13 |
| Original 13 provider rounds still undetermined | 13 / 13 |
| Companies among those 13 still without strict-window disclosure evidence | 12 |
| In-window issuer SEC first-sale companies | 12, unchanged |
| Verified company financing negatives | 0 |

TrueClaim's [KAYA investor newsletter](https://newsletter.kaya.vc/ceefarers-jun-2024/) is explicitly dated June 12, 2024. It welcomes TrueClaim under new investments, identifies the matching founders, and links a report of its $2.1M pre-seed round. This establishes a public investor disclosure inside the strict April 5, 2024–April 4, 2026 window. It does **not** establish the transaction date or resolve the separate provider row dated January 1, 2026. One company-level disclosure addition is made; no claim of a separate new round or additional cash is made.

Haplotype Labs' [issuer Form D](https://www.sec.gov/Archives/edgar/data/2017857/000201785724000001/xslFormDX01/primary_doc.xml) directly gives first sale March 29, 2024, outside the strict window. This is retained as transaction evidence for that offering. A later filing date cannot move the first sale into the window. One outside-window offering does not prove that the company had no later financing.

The baseline 102 disclosures are carried forward, not independently reverified here. The candidate does not combine first-sale and disclosure evidence into a financing-positive union. UNKNOWN remains separate from zero. No two-class evaluation set or 90% coverage is claimed.

## Files

- `reviewed_evidence.json`: manual source-review ledger for all 13 original undetermined companies, checked November 19, 2026. It records primary URLs inspected, inaccessible pages, unresolved original announcement dates, and separate evidence admitted for TrueClaim.
- `pr3_original_round_leads.csv`: the 13 matching company-level leads extracted from PR #3 commit `82bb8e9f6e1224192d402283088b7ef0d809f35f`. These are leads, not newly admitted positives.
- `original_13_date_audit.csv`: per-company date, precision, source type, attribution, and adjudication results.
- `funding_outcomes_candidate.csv`: a 240-row candidate in the existing financing schema. Only TrueClaim changes its public-disclosure fields; transaction labels and all negative-label fields remain unchanged.
- `boundary_cases.csv`: manual-review queue around **both** strict-window boundaries. The `displayed_date_boundary_flags` column screens the displayed date only: **60 rows / 55 companies** fall within ±3 calendar months. Source precision is not inferred from an ISO date string. Widening dates with unreported precision conservatively to the whole year gives **102 rows / 84 companies** potentially overlapping a boundary band. Neither queue establishes a measured lag or admits a positive.
- `summary.json` and `manifest.json`: counts, explicit limitations, source revision, and SHA-256 hashes of audit inputs and generated outputs.
- Other files in this directory may separately review upstream PR #3 or API access; they do not change this candidate's date adjudications.

Rebuild offline from the repository root:

```sh
python3 scripts/audit_funding_dates.py
python3 -m unittest discover -s tests -p test_funding_date_audit.py -v
```

The rebuild checks the frozen cohort, exactly the original 13 company IDs, interval arithmetic, admission semantics, counts, and hashes. It does not re-fetch or independently verify the source pages. No credentials or raw API responses are included.

日期審核維持「原供應商輪次」與「另找到的公開披露」兩層：原本13筆輪次日期仍未確定；TrueClaim另有2024-06-12投資人公告，因此公司層級嚴格披露候選數由102增為103。SEC首次出售證據維持12家，未與披露數相加；無事件、網站讀取失敗與日期不明均不得標成零。三個月只作人工複核提示，不自動平移日期，也未聲稱已測得來源延遲。
