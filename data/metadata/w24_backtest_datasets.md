# W24 backtest datasets — metadata

Generated 2026-10-29. Companion to
[`docs/research_log/2026-10-29_w24_backtest_design.md`](../../docs/research_log/2026-10-29_w24_backtest_design.md).

This file documents the derived tables under `data/processed/`. For the earlier
2026-10-21/22 source inventory see [`docs/data_manifest.json`](../../docs/data_manifest.json),
which remains valid and is not superseded.

---

## `w24_spreadsheet_2024-03-25.csv` — 240 rows

**The primary cohort.** Historical W24 company list captured 2024-03-25, nine
days before Demo Day.

Columns: `Company Name`, `Company Website`, `YC Link`, `Short Description`,
`Tags`, `Location`, `Date Launched`, `Founder Link 1/2/3`.

| Property | Value |
| --- | --- |
| Snapshot date | 2024-03-25 |
| Relationship to t | 9 days before t = 2024-04-03/04 |
| Role | dated pre-Demo-Day baseline universe; source of `X` baseline fields |

**Cautions**

- `Date Launched` is the **Launch YC posting date**. It is not the founding
  date, YC entry date, or Demo Day date.
- 240 is **not** a claim about official W24 Demo Day attendance. Four sources
  report four different universe sizes (240 / 161 / 248 / ~260). See research
  log §5.
- Membership in this list **is** dated evidence of pre-Demo-Day public
  visibility. Absence from it is **not** evidence of non-membership.
- Contains founder LinkedIn URLs. Retained so that both team members hold a
  byte-identical copy of the source spreadsheet.

---

## `yc2024_monthly.csv` — 13,577 rows

Monthly panel of YC 2024-batch companies reconstructed from the git history of
the `yc-oss/api` mirror.

Columns: `snapshot`, `batch`, `slug`, `name`, `status`, `team_size`,
`one_liner`, `website`, `locations`, `industry`.

| Property | Value |
| --- | --- |
| Snapshots | 23 monthly, 2024-10-01 .. 2026-10-01 |
| Batches | winter-2024, summer-2024, fall-2024 |
| Companies tracked | 822 |
| Produced by | `src/data_collection/build_yc_timeseries.py` |

**Cautions**

- The series starts **about six months after t**. Every field is post-decision
  information and may not be used as `X`.
- Committed rather than regenerated on demand because it is a reconstruction of
  a **mutable** upstream source. Re-running later may not reproduce it.
- `yc-oss` serves both `batches/winter-2024.json` (live) and a stale frozen
  `batches/w24.json`; they disagree (25 Inactive / 14 Acquired vs 7 / 2). This
  file was built from the live path. See research log §8.

---

## `status_transitions.csv` — 55 rows

Dated status changes derived by comparing consecutive snapshots.

Columns: `batch`, `slug`, `name`, `from_status`, `to_status`,
`changed_between`, `detected_at`, `website`, `industry`.

| Transition | Count |
| --- | ---: |
| Active → Inactive | 31 |
| Active → Acquired | 21 |
| Acquired → Inactive | 1 |
| Inactive → Active | 1 |
| Inactive → Acquired | 1 |

Produced by `src/outcome_tracking/extract_status_transitions.py`, verified to
reproduce this file exactly.

**Cautions**

- The change occurred somewhere **between** `changed_between` and
  `detected_at`. Monthly sampling cannot narrow it further; `detected_at` is
  not the event date.
- **These 55 rows are not the outcome sample.** Companies still Active at the
  cutoff have an outcome too. Restricting `Y` to companies that changed status
  would condition the sample on the label.
- The single `Inactive → Active` and single `Acquired → Inactive` rows run in
  directions that are rare in reality and are more likely upstream data
  corrections. Inspect them individually before using them as events.
- Active ≠ success, Inactive ≠ total loss, Acquired ≠ successful exit. See
  research log §9.

---

## `w24_crosswalk.csv` — 240 rows

Links each 2024-03-25 spreadsheet company to its current `yc-oss` record.

Columns: `sheet_name`, `sheet_domain`, `sheet_slug`, `matched_slug`,
`matched_name`, `method`, `renamed`.

| Property | Value |
| --- | --- |
| Coverage of current W24 universe | 89.1% |
| Coverage without using `former_names` | 67.7% — the difference is renames alone |
| Rename rate among matched | ~27% |
| Match methods | `slug` (exact), `domain` (unique), `former_name` (unique) |
| Produced by | `src/entity_resolution/build_w24_crosswalk.py` |

**Cautions**

- A blank `matched_slug` means the current directory no longer lists that
  company. It does **not** mean the company was not in W24, and it does not
  mean failure.
- No fuzzy matching. Multi-candidate cases go to `w24_uncertain_matches.csv`
  and are left for human review, never merged.

---

## `w24_late_published_27.csv` — 27 rows

The 27 companies in the current `yc-oss` W24 universe that are **absent** from
the 2024-03-25 spreadsheet. Input list for the pre-Demo-Day evidence audit.

Columns: `slug`, `name`, `launched_at_launchyc_posting_date`,
`yc_page_captures_by_2024_04_04`, `website_captures_by_2024_04_04`.

The `launched_at` column is named in full on purpose. **StarJar**'s value is
`2025-03-15`, about eleven months after Demo Day — reading that field as a
membership or founding date would wrongly exclude the company. See research
log §6.

Capture counts are archive-coverage diagnostics, **not** eligibility scores. A
zero means the Internet Archive has nothing, which says nothing about the
company.

### Audit status

5 of 27 are **CONFIRMED** by archived YC company pages whose HTML contains
`W24`/`Winter 2024`, captured before the 2024-04-04 cutoff:

| Company | Earliest pre-cutoff YC page capture | Captures |
| --- | --- | ---: |
| Ryse | 2024-03-27 | 6 |
| K-Scale Labs | 2024-03-27 | 4 |
| Astro Mechanica | 2024-03-29 | 2 |
| Happenstance | 2024-03-29 | 2 |
| Triply | 2024-03-29 | 4 |

Archive URL form:
`https://web.archive.org/web/<timestamp>/https://www.ycombinator.com/companies/<slug>`

The remaining 22 cannot reach CONFIRMED from the sources available: the
archived YC **batch listing** page carries no company names (Algolia front
end), and the contemporaneous 2024-04-01 third-party article names only ~10
companies in its prose. Website archives and Hacker News can at best establish
that a company was publicly in existence before t, not that it was in W24.

The full audit table is still being generated and is **not yet in this
repository**; Wayback rate limiting makes it an hours-long run. Classification
is CONFIRMED / PROBABLE / UNRESOLVED with **no NOT-ELIGIBLE category**: no
company was found with positive evidence of joining W24 after Demo Day, and
`UNRESOLVED` describes the state of our evidence, not the company.

---

## `w24_raw_outcomes_24m.csv` — 240 rows, 41 columns

Raw 24-month outcome dataset for the dated cohort. Decision point
2024-04-03/04, primary cutoff 2026-04-04. Produced by
`src/outcome_tracking/build_raw_outcomes.py`.

**Contains no success/failure label and no weighted score, by design.** The
five dimensions are kept independent: survival, follow-on funding,
acquisition, team growth, evidence quality.

Full coverage and quality analysis:
[`docs/research_log/2026-10-29_raw_outcome_coverage.md`](../../docs/research_log/2026-10-29_raw_outcome_coverage.md).

| Dimension | Coverage |
| --- | ---: |
| Survival | 92.1% |
| Team size (both observations) | 90.8% |
| Acquisition | 92.1% |
| Follow-on funding (SEC Form D) | **4.6%** |

**Cautions**

- **Funding is not usable from this source.** Form D recall on this cohort is
  about 5%, because most early YC rounds are SAFEs under Section 4(a)(2),
  which requires no filing. `NO_EVIDENCE_FOUND` on 229 companies is absence of
  evidence, not zero funding. Trieve's \$3.5M September 2024 seed is absent
  from Form D entirely.
- **No observation exists at the cutoff.** yc-oss stopped updating from
  2026-02-08 to 2026-05-04 (YC rotated the Algolia key its scraper used), an
  86-day blind window containing 2026-04-04. 8 companies changed status inside
  it; their change cannot be dated against the cutoff.
- **Survival `Unknown`, acquisition `UNKNOWN`, and team-size "neither
  observation" are the same 19 companies** — those absent from the current YC
  directory. Not to be labelled failed.
- 0 acquirers named and 0 transaction amounts disclosed, so the dataset
  carries no return information at all.
- The team-growth window is roughly 16 months, not 24, and varies per company.
  Use the per-row dates.
- Hand-verified items come from `manual_outcome_evidence.csv` and are applied
  reproducibly rather than edited into the CSV.

---

## File integrity

Generated 2026-10-29 at commit `81d1b4c`.

**The checksum is taken over LF-normalised content, not over the file as it
sits in your working copy.** Git converts line endings on checkout, so the same
repository file is 70,635 bytes with LF on macOS/Linux and 70,875 bytes with
CRLF on Windows, and a naive `sha256sum` of the working copy therefore
disagrees between the two platforms. Normalising to LF makes the value
reproducible on any machine. `byte_size` below is the LF size, which is also
what the GitHub API reports for the blob.

| File | Bytes (LF) | Data rows | Columns | SHA-256 (LF-normalised) | git blob |
| --- | ---: | ---: | ---: | --- | --- |
| `w24_spreadsheet_2024-03-25.csv` | 70,635 | 240 | 10 | `21c9f421f1fedd47008fe9d72f091d95ed76a63fad3832f235ff4a53d793cb76` | `797c4ad256f2` |
| `yc2024_monthly.csv` | 1,980,225 | 13,577 | 10 | `1175af0ead3329beabe07f6ef54fb8682e4987805df7a98d787a33e1ca513794` | `c4ed6268faab` |
| `status_transitions.csv` | 5,460 | 55 | 9 | `044b4d227e7002a0932fcfebb9548837264416f0ff85790238c1ac55de1c7df5` | `38e2e378b476` |
| `w24_crosswalk.csv` | 13,977 | 240 | 7 | `b5151319062ccc1fcd52f9622f2749ba150c87f76783979b51ace86da3066520` | `d5638b39ef90` |
| `w24_late_published_27.csv` | 1,048 | 27 | 5 | `d69879be20642878b55a318e7802e7d940ed4c387812dd7a739065aa706f3b31` | `22c707174898` |
| `w24_raw_outcomes_24m.csv` | 132,566 | 240 | 41 | `b19798e7b18e4ac0aa6819c5f88148afb31973c7102ba19010db7a86935f01b5` | `d1e1a6aba78f` |

`Data rows` excludes the header row. All five row counts match the figures
quoted in the sections above, which is a check that the documentation and the
committed files have not drifted apart.

### Verify

Platform-independent, from the repository root:

```bash
python - <<'PY'
import hashlib, pathlib
for p in sorted(pathlib.Path("data/processed").glob("*.csv")):
    lf = p.read_bytes().replace(b"\r\n", b"\n")
    print(hashlib.sha256(lf).hexdigest(), len(lf), p.name)
PY
```

Or check what git itself stored, which ignores your working-copy line endings:

```bash
git ls-tree -l HEAD data/processed/
```

### Why this matters more for these files than for the 2026-10-21 inventory

The files in [`docs/data_manifest.json`](../../docs/data_manifest.json) are
static third-party downloads: if a hash ever mismatches, the original can be
re-downloaded from its source URL.

`yc2024_monthly.csv` cannot. It is reconstructed by walking the git history of
the `yc-oss/api` mirror and reading batch files as they stood at one commit per
month. That upstream history is mutable, the GitHub API is rate-limited, and a
later re-run may silently select different commits. The checksum is the only
way to establish that two people are analysing the same panel.

`status_transitions.csv` and `w24_crosswalk.csv` are derived from it, so their
checksums only mean anything relative to the panel's checksum above.
