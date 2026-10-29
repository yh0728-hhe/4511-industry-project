# Raw 24-Month Outcome Dataset — Coverage and Quality Report

**Date:** 2026-10-29
**Status:** Raw Y recorded. **No composite label built. No weighted score built.**
**Companion to:** [`2026-10-29_w24_backtest_design.md`](2026-10-29_w24_backtest_design.md)
**Dataset:** [`data/processed/w24_raw_outcomes_24m.csv`](../../data/processed/w24_raw_outcomes_24m.csv), 240 rows, 41 columns
**Built by:** [`src/outcome_tracking/build_raw_outcomes.py`](../../src/outcome_tracking/build_raw_outcomes.py)

Cohort: the 240 companies in the dated 2024-03-25 W24 spreadsheet.
Decision point t = 2024-04-03/04. Primary outcome cutoff = 2026-04-04.

This report stops at coverage. The evaluation rule is to be defined after
reading it, not before.

---

## 1. Headline coverage

| Dimension | Coverage | Of 240 |
| --- | ---: | --- |
| Survival (status known at or before cutoff) | **92.1%** | 221 |
| Team size (both observations present) | **90.8%** | 218 |
| Acquisition (determinable by cutoff) | **92.1%** | 221 |
| **Follow-on funding (SEC Form D)** | **4.6%** | **11** |

Three dimensions are usable. **One is not.** That asymmetry is the main
finding of this report and it is a property of the source, not of the cohort.

### The same 19 companies limit three dimensions

Survival `Unknown` = 19. Acquisition `UNKNOWN` = 19. Team size with neither
observation = 19. These are the **same 19 companies**: those absent from the
current YC directory, which left before our panel begins (2024-10-01), so
yc-oss never observed them.

This is a structural, fully-identified gap, not random missingness.
**Per the design rules these 19 must not be labelled failed.** Removal from
the YC directory is not an outcome.

---

## 2. Survival

| Status at or before 2026-04-04 | Count | Share |
| --- | ---: | ---: |
| Active | 202 | 84.2% |
| Inactive | 17 | 7.1% |
| Acquired | 2 | 0.8% |
| Unknown | 19 | 7.9% |

Source: yc-oss `batches/winter-2024.json` at the monthly commit snapshot.
`survival_evidence_date` records the actual observation date **per company**,
not a cohort-wide date.

### 2.1 An 86-day blind window straddles the cutoff

**There is no observation at the cutoff.** yc-oss stopped updating between
**2026-02-08 and 2026-05-04** because YC rotated the Algolia key the scraper
depended on; the upstream commit that resumes service is titled
*"Fix YC API fetcher by reading current Algolia key"*.

| | Date | Relative to cutoff |
| --- | --- | --- |
| Last observation before cutoff | 2026-02-08 | 55 days before |
| First observation after cutoff | 2026-05-04 | 30 days after |
| Blind window | 86 days | **contains 2026-04-04** |

**8 companies changed status inside this window** and their change cannot be
dated relative to the cutoff:

| Company | At 2026-02-08 | After the window |
| --- | --- | --- |
| Aedilic | Active | Inactive |
| BiteSight | Inactive | Active |
| Browser Buddy | Active | Acquired |
| Glimmer | Active | Inactive |
| Okapi | Active | Inactive |
| Resonance | Active | Acquired |
| Speck | Active | Acquired |
| thorntale | Active | Inactive |

These are flagged `status_changed_in_blind_window=TRUE` and are recorded with
their pre-window status in the primary field. **They are genuinely uncertain
and must not be resolved by assumption in either direction.** Note BiteSight
moved Inactive → Active, which also shows that `Inactive` in this source is
not always terminal.

---

## 3. Follow-on funding — the dimension that does not work

| | Count |
| --- | ---: |
| Form D evidence found in window | 11 (4.6%) |
| No Form D evidence found | 229 |
| Name-matched with a caveat | 4 |
| With a disclosed amount sold | 11 |

### 3.1 The problem is recall, not precision

The 11 matches look largely genuine — Legora (formerly Leya) at \$79.8M,
Momentic at \$18.6M, Tamarind Bio at \$13.6M, Guide Labs at \$9.3M.

The failure is that the other 229 are mostly **not in Form D at all**. A
substring search over 99,347 distinct normalised issuer names finds no trace
of Gumloop, Reducto, Circleback or Artisan AI.

**Why:** Form D is required only when relying on the Regulation D safe
harbour. Most early-stage YC rounds are SAFEs placed under the
**Section 4(a)(2)** private-placement exemption, which requires no filing.
Form D also covers US offerings only, and several cohort companies are
non-US.

**Demonstration.** Trieve raised a \$3.5M seed led by Root Ventures,
announced September 2024 — inside the window — and has **no Form D filing**.
Recorded as supplementary evidence in
[`manual_outcome_evidence.csv`](../../data/metadata/manual_outcome_evidence.csv),
deliberately *not* merged into the Form D fields.

**Consequence:** `followon_funding_evidence = NO_EVIDENCE_FOUND` on 229
companies carries almost no information. Reading it as "did not raise" would
be wrong for most of them. **Funding cannot enter Y from this source.**

### 3.2 One confirmed conflict

**Lantern** was observed `Inactive` by 2025-11-01 but a name-matched Form D
filing is dated 2026-03-16, from an issuer in FL against a cohort location of
CA. A dead company does not file a new offering: this is almost certainly a
different company of the same name. Flagged in `funding_match_caveat` and
treated as **unverified**.

Three further matches carry an issuer-state mismatch (Argon AI NY/CA,
Intercept VA/CA, Lumona VA/CA) and need individual checks. Form D has no
domain field, so there is no automatic way to disambiguate a common name.

---

## 4. Acquisition

| | Count |
| --- | ---: |
| Acquired by cutoff | 2 (0.8%) |
| No evidence by cutoff | 219 |
| Unknown (the 19) | 19 |
| Acquired **after** cutoff, held separately | 10 |
| Acquirer **named** | **0** |
| Transaction amount disclosed | **0** |

The two pre-cutoff acquisitions are **Arcane** (detected between 2024-10-01
and 2024-11-01) and **Trieve** (between 2025-09-01 and 2025-10-01). Both were
looked up by hand on 2026-10-29; **neither acquirer nor amount is public for
either.** Recorded as `NOT_DISCLOSED`, which is distinct from "not looked up".

### Why `Acquired` must not become success

Arcane's co-founder's public profile lists a current employer of OpenAI and
"previously founded Arcane (W24)". For a two-person team this pattern is
consistent with an **acqui-hire**, which can return less than invested capital.

**This hint does not establish an acquirer** and is recorded at Low confidence
as a hint only. It is concrete support for the design rule: `Acquired` is a
raw fact, not a success label.

The 10 post-cutoff acquisitions sit in `acquisition_post_cutoff` and **must
not enter primary Y**. Three of them (Browser Buddy, Resonance, Speck) are the
blind-window cases from §2.1, so even their exclusion rests on an undatable
observation.

---

## 5. Team growth

| | Count |
| --- | ---: |
| Both observations present | 218 (90.8%) |
| First observation only | 3 |
| Last observation only | 0 |
| Neither (the 19) | 19 |
| Percentage growth computable | 216 |

Missing values are left blank. **Nothing is imputed as zero.** Percentage
growth is left blank where the baseline is 0, since the ratio is undefined.

### Window caveat

The first observation is each company's earliest panel snapshot, typically
**2024-10-01 — about six months after Demo Day**. The measured window is
therefore roughly **16 months, not 24**, and it varies slightly per company;
both dates are recorded per row. Any cross-company comparison of growth must
use the recorded dates rather than assuming a common window.

`team_size` from yc-oss is a self-reported current headcount, not an audited
figure.

---

## 6. Evidence quality

| Confidence | Count | Share |
| --- | ---: | ---: |
| High | 13 | 5.4% |
| Medium | 198 | 82.5% |
| Low | 29 | 12.1% |

`High` requires two or more independent sources agreeing with no blind-window
change — which, given that funding coverage is 4.6%, is only reachable for
companies that have both a panel record and a Form D match. **The scarcity of
`High` is a direct consequence of having effectively one usable source.**

---

## 7. Conflicting and uncertain cases

| Case | Count |
| --- | ---: |
| Status changed inside the blind window | 8 |
| Funding name-match caveat (incl. 1 hard conflict) | 4 |
| Renamed since the decision date | 63 |
| Absent from current YC directory | 19 |
| Entity chains over-merged by a shared key | **0** |

**63 of 240 companies (26.3%) renamed**, consistent with the ~27% rate found
earlier. Searching funding or acquisition by the 2024-03-25 name alone would
miss them, which is why all lookups try current name, decision-date name and
every known former name.

Entity chains were built with a union-find over slug, domain and name because
**all three keys are unstable**: Adagy Robotics moved
`adagy-robotics` → `tuesday-lab` → `tuesday-labs` and
`adagyrobotics.com` → `tuesdaylab.com`. Keying on the current slug alone
silently lost 18 companies in a first pass. No chain holds more than one
record per snapshot, so there is no detected over-merge.

---

## 8. Sources used

| Source | Used for | Access |
| --- | --- | --- |
| 2024-03-25 W24 spreadsheet | cohort definition, decision-date names/domains/locations | local, dated |
| yc-oss `batches/winter-2024.json` monthly commits | survival, team size, acquisition events, former_names | public, no key |
| SEC Form D 2024Q2–2026Q2 (129,425 submissions) | follow-on funding | public bulk, no key |
| Hand verification, 2026-10-29 | acquirer / amount for the 2 pre-cutoff acquisitions; Trieve funding | web search, recorded in a side file |

**Not used:** Crunchbase 2015 (ends 2015-12-04, eight years before this
cohort); YC Bench (W26, a different batch). The official Crunchbase API
offered by the sponsor has not been received.

---

## 9. What this means for defining Y — decision required

Three findings bear on the evaluation rule. **No choice is made here.**

1. **Funding cannot come from Form D.** 4.6% recall makes it unusable as a Y
   dimension. Either obtain a funding source with real coverage (the sponsor's
   Crunchbase API is the obvious candidate) or drop funding from primary Y and
   state that it was dropped for coverage reasons.

2. **The cutoff cannot be observed exactly.** Options are to accept
   2026-02-08 as the effective status date and rename the horizon honestly
   (~22 months), to carry the 8 blind-window companies as a declared
   uncertainty set, or to source status for March–April 2026 elsewhere. Moving
   the cutoff to fit the data would reintroduce exactly the convenience-driven
   date selection the design rejects for t.

3. **The outcome distribution is thin.** 202 Active / 17 Inactive /
   2 Acquired / 19 Unknown. Any binary success label would be extremely
   imbalanced, and with 0 named acquirers and 0 disclosed amounts there is no
   return information anywhere in the dataset. This is a strong argument for
   the portfolio/ranking evaluation in the design log §10 rather than
   company-level classification.

**Next step is a decision, not code.** Nothing downstream — composite label,
DIALECTIC baseline — should be built until the funding source and the cutoff
treatment are settled.
