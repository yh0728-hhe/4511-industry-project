# W24 Demo Day Investment-Decision Backtest — Research Design

**Date:** 2026-10-29
**Status:** Design agreed; baseline experiment not yet run
**Supersedes:** nothing. The 2026-10-21/22 data inventory in [`README.md`](../../README.md) and [`docs/data_manifest.json`](../data_manifest.json) remains valid as the earlier stage of this project.

This log records the research decisions reached as of 2026-10-29. It is a point-in-time document. Future major methodological changes should be written as their own dated research-log file rather than overwriting this one.

---

## 1. Research question

> **At W24 Demo Day, should a VC invest in this startup?**

The experiment simulates an **external VC** evaluating Y Combinator Winter 2024 startups around Demo Day.

The distinction matters. A question framed at YC entry ("should YC select this company?") is a different question with a different decision-maker, a different information set, and a different counterfactual. Our sponsor is a VC fund, so the relevant question is the one an outside investor faces **after** YC has already done its own screening and after the companies have been through the program.

---

## 2. Decision point (t)

**t = W24 Demo Day, 2024-04-03 / 2024-04-04.**

Conceptual timeline:

```
YC Entry  ->  YC Program  ->  Demo Day investment decision (t)  ->  External VC investment  ->  Future outcome
```

Demo Day dates are corroborated by a contemporaneous third-party source published 2024-04-01, which states that YC's Demo Day for the Winter 2024 batch was "happening on April 3rd and 4th."

**Explicitly rejected alternatives for t:**

- company founding date
- YC entry date
- the first available `yc-oss` repository snapshot date
- any date chosen because it is easier to observe

Convenience of observation is not a reason to move the decision point. Moving t to a later, more observable date would silently grant the model information that a real investor at Demo Day did not have.

---

## 3. Point-in-time rule

Intended backtest structure:

```
X(i, t)  ->  model decision at t  ->  Y(i, t + 24m)
```

Future information must not leak into `X`. This is the core validity constraint of the whole experiment.

### 3.1 Two things that must not be confused

| Concept | Question it answers | What a negative result means |
| --- | --- | --- |
| **Eligibility / investment universe** | Was this company available for an external VC to invest in at t? | A company is outside the universe only on positive, dated evidence that it was not available. |
| **X availability / historical evidence coverage** | Can *we*, in 2026, recover the information that was visible at t? | Only that our reconstruction is incomplete. |

**Failure to recover a historical webpage does NOT prove that the company was not part of W24, and does NOT prove it was unavailable to investors.**

Archive coverage is a property of the Internet Archive's crawl schedule, not a property of the company. Treating a missing archive as a negative fact would introduce a selection effect correlated with company visibility — which is plausibly correlated with the outcome we are trying to predict. That would bias the backtest in the most damaging possible direction.

### 3.2 Practical consequence

Low evidence coverage is a reason to record `insufficient evidence`, or to route the company to `MORE DD` (see §9), or to report coverage as a separate diagnostic. It is **not** a reason to drop the company from the universe.

---

## 4. Current primary cohort

**Primary cohort for the first controlled experiment: the 240 companies in the 2024-03-25 historical W24 spreadsheet.**

Reason for this choice: it is a **clearly dated, pre-Demo-Day** baseline universe. The snapshot date (2024-03-25) is nine days before Demo Day, so membership in this list is dated evidence that the company was publicly visible as a W24 company before t. That is exactly the property a point-in-time universe needs.

**What this cohort is NOT:**

- It is **not** a claim that 240 is the definitive official W24 Demo Day attendance count.
- It is **not** a claim that companies outside it were absent from W24.

The broader W24 crosswalk, and the additional companies found in current `yc-oss` and in other historical sources, are retained as **supplementary universe analysis** (see §5).

The earlier 27-company eligibility investigation is **preserved, not deleted** (see §5.3). It is no longer the blocker for the baseline experiment, because the baseline experiment now runs on the dated 240-company cohort and treats universe reconstruction as a separate robustness question.

---

## 5. W24 universe finding

**Different historical and current sources report different W24 universe sizes.** This is an empirical finding about the sources, not an artifact of our processing.

Observed, as of 2026-10-29:

| Source | Date | W24 companies reported |
| --- | --- | --- |
| Historical W24 spreadsheet | 2024-03-25 | 240 |
| Contemporaneous third-party analysis | 2024-04-01 | "all 161 companies that have gone through the W24 batch" |
| `yc-oss` community mirror, current | 2026-10 | 248 |
| YC's own later descriptions of W24 | various | approximately 260 |

Four sources, four numbers. The disagreement already existed **in April 2024**, before any of our processing. It is not something we introduced and not something we can resolve by picking the most convenient figure.

### 5.1 Rules adopted

- **Do not** force the dataset to equal 260 merely because YC later described W24 as approximately 260 companies.
- **Do not** infer exclusion solely from absence in one historical source.
- **Preserve source-specific membership flags and dates** rather than collapsing them into a single boolean.
- **Treat universe reconstruction as a separate robustness / supplementary analysis**, not as a precondition for the baseline experiment.

### 5.2 Source-specific flags to preserve

Per company, keep membership and its date **per source**, for example:

```
in_mar25_spreadsheet        (TRUE/FALSE, source date 2024-03-25)
in_oct2024_ycoss            (TRUE/FALSE, source date 2024-10-01)
in_oct2026_ycoss            (TRUE/FALSE, source date 2026-10-01)
removed_from_yc_directory   (TRUE/FALSE, with the snapshot range observed)
```

A single `demo_day_eligible` boolean is **not** an adequate representation and earlier drafts that hardcoded it to `TRUE` were wrong (see §11).

### 5.3 Status of the 27-company investigation

27 companies appear in the current `yc-oss` W24 universe but **not** in the 2024-03-25 spreadsheet. We investigated whether there is positive dated evidence that each was a publicly visible W24 investment opportunity on or before 2024-04-04.

Findings so far, recorded for preservation:

- **5 companies CONFIRMED** by archived YC company detail pages whose HTML contains `W24` / `Winter 2024`, captured before the cutoff: Ryse (2024-03-27), K-Scale Labs (2024-03-27), Astro Mechanica (2024-03-29), Happenstance (2024-03-29), Triply (2024-03-29).
- **Two "resolve many at once" sources were tested and failed.** The archived YC batch listing page `ycombinator.com/companies?batch=W24` has captures on 2024-02-18, 2024-03-24 and 2024-03-30 — the last only five days before Demo Day — but the directory is an Algolia-driven front end, so company names never appear in the archived HTML. The contemporaneous 2024-04-01 third-party article explicitly about W24 names only about 10 companies in its prose (verified against the 240-company spreadsheet as a control), so absence from it carries no information.
- Consequently, for the remaining companies only per-company website archives and Hacker News records are available. **Neither can establish W24 membership** — at best they establish that the company was publicly in existence before t. Those companies can therefore reach `PROBABLE` but not `CONFIRMED`.
- The classification is deliberately **CONFIRMED / PROBABLE / UNRESOLVED**. There is **no NOT-ELIGIBLE category**, because we found no company with positive evidence of joining W24 after Demo Day.

`UNRESOLVED` means our evidence is insufficient. It does not mean the company was ineligible, and the set will not be emptied by searching harder — the limiting factor is archive coverage in 2024, which is fixed.

---

## 6. `launched_at` warning

**`launched_at` in `yc-oss` is the Launch YC posting date.**

It must **NOT** be interpreted as:

- company founding date
- YC entry date
- YC investment date
- Demo Day date

### Why this matters: StarJar

**StarJar** is currently tagged as a W24 company, and its `launched_at` is **2025-03-15** — roughly eleven months *after* W24 Demo Day. If `launched_at` were read as a membership or founding date, StarJar would look like it could not possibly have been in W24, and would be wrongly excluded. The field simply records when the company posted to Launch YC, which a company may do long after its batch.

The same caution applies to the `Date Launched` column in the 2024-03-25 spreadsheet.

---

## 7. Entity resolution

**Do not use company name as the only identifier.** Approximately 27% of current W24 companies have been renamed since 2024-03, which caused earlier matching attempts to fail and initially understated spreadsheet coverage of the current universe as 67.7% when the correct figure, after accounting for renames, is 89.1%.

Preserve, where available:

- stable company / entity ID
- `name_at_decision`
- `current_name`
- `former_names`
- `domain_at_decision`
- `current_domain`
- rename flag
- source-specific IDs

### Rules

- **Uncertain matches must remain separate and must not be silently merged.** Multi-candidate matches are written to a separate uncertain-matches file for human review, never auto-resolved.
- Name normalization must strip **legal suffixes only** (`Inc`, `LLC`, `Ltd`, `Corp`, `GmbH`, `Pte`, …). Aggressive token stripping produced a false match of YC's "Pax" to "Pax Labs"/JUUL Labs at a filing value of about \$1.98B — a single normalization bug large enough to corrupt any funding-based outcome measure.
- Matching on domain is preferred over matching on name, and a single-candidate requirement is enforced before accepting an automatic match.

---

## 8. X design

`X` represents **information legitimately available to an external VC at or before the Demo Day decision point.**

Potential sources:

- historical YC information (archived YC company pages)
- historical company websites / Wayback Machine captures dated on or before 2024-04-04
- contemporaneous public sources (dated articles, Launch HN / Hacker News records with exact timestamps)
- other dated public evidence

### Constraint on `yc-oss`

`yc-oss` is useful but **must not be treated as the only historical X source**, because usable repository snapshots begin **later than W24 Demo Day**. Our reconstructed `yc-oss` time series runs 2024-10-01 to 2026-10-01 — it starts roughly six months *after* t. Every field in it is therefore post-decision information and is unusable as `X` without a dated pre-t source.

A related trap, recorded because it already cost us real work: `yc-oss` serves both `batches/winter-2024.json` and a stale frozen `batches/w24.json`. The stale file reported 7 Inactive / 2 Acquired where the live file reported 25 Inactive / 14 Acquired. Reading the wrong filename produced about eighteen months of plausible-looking but incorrect status history **with no error raised**. Any snapshot-based pipeline must pin the exact file path and validate counts against an independent snapshot.

---

## 9. Y design

**Primary outcome horizon: 24 months after W24 Demo Day, ending approximately 2026-04-04.**

**Do NOT immediately reduce `Y` to `success = 1 / failure = 0`.** Preserve the raw outcome dimensions separately first:

- survival / status
- follow-on financing
- acquisition
- team growth
- evidence / source quality

### Interpretation rules

- `Active` **≠** automatically a successful investment.
- `Inactive` **≠** automatically a complete investment failure, without context.
- `Acquired` **≠** automatically a successful exit. An acqui-hire below the post-money valuation can be a loss.
- Missing funding evidence **≠** zero funding. SEC Form D covers US exempt offerings only, and many rounds never appear in it.
- Removal from the YC directory **≠** failure.

### Cutoff handling

Events after the primary 2026-04-04 cutoff may be **retained separately** but **must not enter** the primary 24-month outcome. The outcome sample must not be pre-filtered: companies still `Active` at the cutoff have an outcome too, and the 55 observed dated status transitions in our time series are not the whole outcome sample.

---

## 10. Evaluation direction

Compare investment recommendations using **portfolio / ranking metrics** rather than only company-level classification. A VC does not make 240 independent binary calls; it builds a portfolio.

Potential evaluation:

- Top-K recommendations
- Precision@K
- outcome differences between `INVEST` and `PASS` groups
- comparison between the DIALECTIC baseline and our improved Multi-Agent Investment Committee

### Three-way output

Our improved system may support:

```
INVEST / PASS / MORE DD
```

where **`MORE DD` represents insufficient decision-critical evidence** rather than forcing a binary decision. This is a deliberate design choice: abstention is informative, and a system that is forced to guess under thin evidence hides exactly the failure mode we want to study.

### Baseline note

The shipped DIALECTIC configuration is **not** the paper's configuration (shipped defaults: 3 pro / 3 contra arguments, `k_best = [1, 1]`, `max_iterations = 2`, versus K = 4 in the paper). Any baseline comparison must state which configuration was run. The paper itself reports test-set AUC-PR of 0.2422, not clearly better than naive GPT prompting, and reports degradation beyond T ≥ 3 iterations — so "more agents is better" is a **hypothesis to test, not a premise**.

---

## 11. Intended architecture

```
Investor Context
  -> Lead Investor / Orchestrator
  -> Task Decomposition
  -> Dynamic Specialist Research
  -> Structured Fact Base
  -> PRO / CON Debate
  -> Critic
  -> Evaluator
  -> Evidence Reviewer
  -> if evidence is insufficient: Targeted Additional Due Diligence
  -> Thesis Synthesis
  -> INVEST / PASS / MORE DD
  -> human VC final decision
```

The central design idea:

> **Research -> Debate -> Identify evidence gaps -> Research again -> Debate/review again -> Decision**

rather than a purely linear research -> debate -> decision pipeline. The closed loop is the contribution; the Evidence Reviewer exists specifically to send work back rather than to rubber-stamp whatever the first research pass produced.

### Unresolved

**The stopping rule / evidence sufficiency criterion is still unresolved and must NOT be presented as finalized.** Open questions include what counts as sufficient evidence for a decision-critical claim, how many re-research loops are permitted, and whether stopping should be fixed or adaptive. This is an open design problem, not a settled part of the architecture.

---

## 12. Known errors corrected in this design

Recorded so the same mistakes are not repeated:

| Error | Correction |
| --- | --- |
| Hardcoding `demo_day_eligible = TRUE` with evidence string "W24 batch membership (yc-oss)" | Current `yc-oss` batch membership is not dated pre-t evidence. Replaced by source-specific dated membership flags (§5.2). |
| Treating "batch membership implies eligibility" as settled | Requires positive dated evidence per company (§5.3). |
| Reading the stale `batches/w24.json` instead of `batches/winter-2024.json` | Pin exact paths; cross-validate status counts (§8). |
| Conflating a failed Wayback CDX query with zero captures | Query failures are recorded as `QUERY_FAILED`, never as absence of evidence (§3.1). |
| Over-aggressive name normalization (Pax / JUUL false match) | Strip legal suffixes only (§7). |
| Matching a company by a generic word appearing in unrelated text | A Hacker News record counted as W24 evidence only if it binds the company name directly to the batch, e.g. `<name> (YC W24)`. A match on the bare word "sample" inside another company's Launch HN title was a false positive and was removed. |

---

## 13. Open items

- Sponsor's investment mandate (stage, check size, horizon, sector, priorities) — requested, not yet received. The mandate is a **system input**, so the baseline cannot be finalized without it.
- Crunchbase API key — offered by sponsor, not yet received or tested.
- Stopping rule / evidence sufficiency criterion (§11).
- Final `Y` aggregation from the preserved raw dimensions (§9).
- Entity resolution between the W24 cohort and SEC Form D filings, at acceptable precision (§7).

---

## 14. Next step

Run the **DIALECTIC baseline on the 240-company dated cohort** with search locked to on-or-before 2024-04-04 — **after** the design above is confirmed and the mandate is received. Not started as of this log.
