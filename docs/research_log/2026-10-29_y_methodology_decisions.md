# Y Methodology Decisions and Status

**Date:** 2026-10-29
**Status:** Decisions adopted and implemented. **No composite score. No binary label. No model evaluation.**
**Does not supersede:** [`2026-10-29_w24_backtest_design.md`](2026-10-29_w24_backtest_design.md) or [`2026-10-29_raw_outcome_coverage.md`](2026-10-29_raw_outcome_coverage.md). Both stand as written.

Six decisions were taken after reading the raw outcome coverage report. This
log records them, what changed in the data, and one figure from the previous
report that was **wrong and is corrected here**.

---

## 1. Y status summary

| Dimension | Status | Coverage | Role in primary Y |
| --- | --- | ---: | --- |
| **Survival** | **usable** | 95.0% resolved at endpoint | raw dimension |
| **Team growth** | **usable** | 97.1% both observations | major outcome signal, not a return |
| **Acquisition** | **event only / return unknown** | 97.5% determinable | raw event indicator |
| **Funding** | **`PENDING_BETTER_DATA_SOURCE`** | 4.6% | **excluded**; supplementary validation only |
| **Endpoint uncertainty** | explicit set | **8 companies** | carried as declared uncertainty |
| **Pre-panel missingness** | explicit set | **4 companies** | retained in cohort, never labelled |

Dataset: [`data/processed/w24_raw_outcomes_24m.csv`](../../data/processed/w24_raw_outcomes_24m.csv), 240 rows, 46 columns.

### Survival at the 2026-04-04 endpoint

| | Count | Share |
| --- | ---: | ---: |
| Active | 210 | 87.5% |
| Inactive | 16 | 6.7% |
| Acquired | 2 | 0.8% |
| UNCERTAIN (blind window) | 8 | 3.3% |
| UNKNOWN (never observed) | 4 | 1.7% |

---

## 2. Correction to the previous report

The coverage report stated that survival `Unknown`, acquisition `UNKNOWN` and
missing team size "are the same 19 companies". **That was wrong.** It was an
inference, not a verified cross-tabulation, and checking it revealed a bug.

The real structure of the 240-company cohort:

| Group | Count | What is true of them |
| --- | ---: | --- |
| A | **4** | No current directory entry **and** no observation ever. Genuinely unobserved. |
| B | **15** | No current directory entry, but observed while still listed. Last observed status is real data. |
| C | **15** | Have a current entry, but the entity chain had broken at a rename — **a bug, now fixed.** |
| D | 206 | Observed throughout. |

Group C was a defect in the chain builder, not missing data. Fixing it changed
coverage materially:

| Metric | Before fix | After fix |
| --- | ---: | ---: |
| Survival resolved at endpoint | 88.8% | **95.0%** |
| Survival UNKNOWN | 19 | **4** |
| Team size, both observations | 90.8% | **97.1%** |
| Acquisition UNKNOWN | 19 | **4** |
| Low-confidence rows | 29 | **14** |

**The structurally missing set is 4 companies, not 19.** Both sets are
exported, because the 19 remain a meaningful group for the survivorship
question even though 15 of them carry real observations.

All 15 observed group-B companies were **`Active` at their last pre-cutoff
observation**. They left the directory while alive. This is direct evidence for
the rule that directory removal is not failure.

---

## 3. Decision 1 — Funding is `PENDING_BETTER_DATA_SOURCE`

Form D absence is **not** evidence of no follow-on funding and is not used as
such anywhere.

Implemented as two explicit columns on every row:

```
funding_dimension_status = PENDING_BETTER_DATA_SOURCE
funding_role_in_primary_Y = SUPPLEMENTARY_VALIDATION_ONLY
```

Follow-on funding is **not** removed from the conceptual Y. It is economically
central to a VC evaluation; it is held out only because 4.6% recall cannot
support it. The **11 verified Form D matches are preserved in full** — date,
type, amount sold, amount offered, filing count, accession number — so they can
be cross-checked against a higher-coverage source later. That set is the
validation sample for whatever source replaces it.

The `NO_EVIDENCE_FOUND` note on the other 229 rows now states the mechanism
directly: Form D covers US exempt offerings only, most early YC rounds are
SAFEs under Section 4(a)(2) which requires no filing, so this is absence of
evidence and must not enter primary Y.

---

## 4. Decision 2 — The 24-month endpoint does not move

The horizon remains **2024-04-04 → 2026-04-04**. The yc-oss observation gap is
a property of our instrument, not a reason to redefine the experiment. Moving
the cutoff to fit the data would reintroduce exactly the convenience-driven
date selection the design rejects for `t`.

Survival columns were restructured so that **no single observation can pass
itself off as the endpoint**:

| Column | Meaning |
| --- | --- |
| `survival_last_pre_cutoff_status` / `_date` | last reliable observation at or before 2026-04-04 |
| `survival_first_post_cutoff_status` / `_date` | first reliable observation after it |
| `survival_at_cutoff_2026_04_04` | the endpoint value, or `UNCERTAIN`, or `UNKNOWN` |
| `endpoint_status` | `OK` / `ENDPOINT_UNCERTAIN` / `NO_OBSERVATION` |
| `survival_blind_window` | the 2026-02-08..2026-05-04 gap, recorded on every row |

The previous single `survival_status` column is gone. **2026-02-08 is never
substituted for the endpoint**: where the two observations disagree the
endpoint value is literally `UNCERTAIN` and no inference is made about which
side of 2026-04-04 the transition fell on.

### The 8-company uncertainty set

Exported to
[`data/processed/w24_endpoint_uncertain.csv`](../../data/processed/w24_endpoint_uncertain.csv).

| Company | Last pre-cutoff | First post-cutoff |
| --- | --- | --- |
| Aedilic | Active | Inactive |
| BiteSight | Inactive | Active |
| Browser Buddy | Active | Acquired |
| Glimmer | Active | Inactive |
| Okapi | Active | Inactive |
| Resonance | Active | Acquired |
| Speck | Active | Acquired |
| thorntale | Active | Inactive |

BiteSight runs Inactive → Active, which also shows `Inactive` is not terminal
in this source.

---

## 5. Decision 3 — No binary Active=Success label

No `Active = 1 / Inactive = 0` label exists in the dataset and none will be
built at this stage. With 210 Active against 16 Inactive the label would be
extremely imbalanced, and survival alone does not represent investment return.

- **Survival** stays one raw dimension among several.
- **Team growth** is preserved carefully as a major outcome signal: 97.1%
  coverage, 231 companies with computable percentage growth, and genuine
  cross-sectional variation. It is **not** treated as investment return.
- **Acquisition** stays a raw event indicator. With **0 named acquirers and 0
  disclosed transaction amounts** in the entire cohort there is no return
  information, so it cannot be read as a successful exit.

### Team-growth caveats that survive into any use of it

The measurement window is each company's own first panel snapshot (usually
2024-10-01, about six months after Demo Day) to its last pre-cutoff
observation — roughly **16 months, not 24** — and it varies per company. Both
dates are on every row and must be used rather than assumed. `team_size` is
self-reported current headcount, not audited. Missing values are blank;
**nothing is imputed as zero**, and percentage growth is blank where the
baseline is 0.

---

## 6. Decision 4 — The structurally missing companies are retained

No company was removed from the 240-company cohort.

The 4 genuinely unobserved companies carry
`missingness_reason = PRE_YCOSS_DIRECTORY_DISAPPEARANCE` and are exported to
[`data/processed/w24_pre_panel_missing.csv`](../../data/processed/w24_pre_panel_missing.csv)
for external or manual outcome research:

**AgentHub, SevnAI, Skygaze, Tatara**

The wider set of 19 companies absent from the current directory is exported to
[`data/processed/w24_directory_disappearance.csv`](../../data/processed/w24_directory_disappearance.csv)
with each one's last observed status and team size.

Missingness here is plausibly **non-random** — it is correlated with whatever
caused a company to leave the directory — so dropping these companies could
introduce survivorship bias in the direction that most flatters the model.
**Failure is not inferred from disappearance anywhere in the pipeline.**

---

## 7. Decision 5 — The entity-chain solution is kept and documented

Point-in-time matching on any single key is not restored. The finding is itself
methodological evidence and belongs in the write-up.

### The worked example

**Adagy Robotics** changed every identifier at once:

```
slug    adagy-robotics      ->  tuesday-lab   ->  tuesday-labs
domain  adagyrobotics.com   ->  tuesdaylab.com
name    "Adagy Robotics"    ->  "Tuesday Lab" ->  "Tuesday Labs"
```

Even the singular/plural changed. No panel row carries a key from both
identities, so a union-find over co-occurring keys **cannot bridge the rename
by itself**. The bridge is yc-oss `former_names`, supplied as a weak candidate.

After the fix Adagy Robotics reads correctly: team size **2 at 2024-10-01 → 5
at 2026-02-08**, `Active`, `endpoint_status = OK`. Before the fix it had no
pre-cutoff observation at all.

### The collision guard, and why it is necessary

Bridging by former name introduced a second failure: a former name can equal a
**different** company's current name. Three chains were wrongly merged:

| Company | Wrongly merged with | Domains |
| --- | --- | --- |
| Ecliptor | Hatchet | ecliptor.ai vs hatchet.run |
| Forge Rewards | Forge | joinforge.app vs forgehq.com |
| Lumona | Scout | lumona.ai vs cpgscout.ai |

Candidates are now ordered by key strength — verifiable identifiers first,
names next, the former-name bridge last — and a chain is merged **only if it
does not place two records in the same snapshot**. A snapshot collision means
two companies, so the weaker candidate is refused and the refusal is recorded
on the row.

Result: **0 chains hold more than one record per snapshot**, 3 merges refused
and reported, and the three companies now carry their own correct data.

---

## 8. Decision 6 — The 27-company audit stays supplementary

The audit completed: **5 CONFIRMED, 6 PROBABLE, 16 UNRESOLVED**, with 7 rows
carrying a `QUERY_FAILED` status from Wayback rate limiting. No further time is
being spent re-running the failed queries.

Universe reconstruction is not the main task. The baseline experiment runs on
the dated 240-company cohort.

Worth recording: a fifth source count appeared while checking acquisitions — a
third-party tracker lists **249** W24 companies. The sources now disagree five
ways (240 / 161 / 248 / 249 / ~260), which continues to support treating
universe size as a robustness question rather than a fact to pin down.

---

## 9. What is explicitly NOT done

- No composite success score.
- No binary success label.
- No DIALECTIC run, no model evaluation.
- No inference about which side of 2026-04-04 the 8 uncertain transitions fell.
- No failure label on any of the 4 unobserved or 19 disappeared companies.
- No funding conclusion drawn from Form D absence.

## 10. Open items before model evaluation

1. **A funding source with real coverage.** The sponsor's Crunchbase API is the
   obvious candidate and has not been received. The 11 Form D matches are the
   ready-made validation sample for it.
2. **How the 8 endpoint-uncertain companies are handled in evaluation** — carried
   as uncertain, excluded with the exclusion declared, or resolved from another
   dated source.
3. **Outcome research on the 4 unobserved companies**, externally.
4. **Whether team growth, acquisition events and survival are reported
   separately or combined**, and if combined, on what justification. Given 0
   return information anywhere in the dataset, the portfolio/ranking evaluation
   in the design log §10 remains better supported than company-level
   classification.
5. The sponsor's investment mandate, still outstanding, which is a system input.
