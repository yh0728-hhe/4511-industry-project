# Funding Source Benchmark

**Date:** 2026-10-29
**Status:** Benchmark complete. **Funding Y not built. No model run. The canonical outcome dataset is unchanged.**
**Builds on:** [`2026-10-29_y_methodology_decisions.md`](2026-10-29_y_methodology_decisions.md)

---

## 1. Why this was done

The sponsor decided today that **follow-on funding should be the primary focus of Y**, and that he has no funding dataset to give us. He asked us to investigate APIs, Crunchbase and free sources ourselves.

Funding was the one dimension we had marked `PENDING_BETTER_DATA_SOURCE`, because SEC Form D reaches only **11 of 240** companies. This benchmark asks a narrower question than "build Y": **is there an accessible source, or combination, with enough historical coverage to support it?**

The locked design is unchanged: 240-company cohort, decision point 2024-04-03/04, outcome window **2024-04-04 (exclusive) to 2026-04-04 (inclusive)**.

---

## 2. Headline result

| Source | Companies resolved | Funding-positive | Events in window | With amount | With evidence URL |
| --- | ---: | ---: | ---: | ---: | ---: |
| SEC Form D (baseline) | n/a — filing match | **11** (4.6%) | 14 | 11 | 0 |
| **Recent Funding** | **175** (72.9%) | **48** (20.0%) | **63** | 42 | **63** |
| **Union of both** | — | **53** (22.1%) | 67 deduplicated | — | 60 |

**Recommendation: `PROMISING BUT NEEDS VALIDATION`** — reasoning in §9.

Recent Funding finds **4.4× more funded companies** than Form D and, unlike Form D, every event carries a dated announcement URL. But 22.1% of the cohort showing a funding event is still far below what one would expect of a YC batch two years on, so the remaining 77.9% is *not* interpretable as "did not raise".

---

## 3. Sources tested

### Recent Funding — usable
`https://recentfunding.com` · free API key issued against an email · read-only JSON · every amount carries a source link.

The key issued for this benchmark is a **24-hour "taste" plan** (1,000 requests/day, `live_until` 2026-10-31T02:39Z). A standing key is 100 requests/day, which would make a 240-company run a multi-day job. **Raw responses are cached under `raw_recentfunding/` so the results can be audited and re-derived without the key.**

### Midu — tested and rejected on evidence
`https://midu.si/api` · free key, 1,000/day, 60/min. Rejected because its historical depth does not reach our window:

| Probe | Result |
| --- | --- |
| `/companies?q=` for 7 known-funded cohort companies | **0 results for all 7** |
| `/rounds` inside 2024-04-05 … 2026-04-04 | **30 rounds total** |
| `/rounds` across 2020 … 2026 | 1,628 rounds total, newest 2026-10-30 |
| Of those 30 in-window rounds, matching our cohort | **0** |

The 30 in-window rounds are SEC Form D records from the last days of the window — data we already hold. Midu is a recent-news product; it has essentially no history before mid-2026. It also exposes an anonymous no-key API, but that covers only the last 24 hours to 7 days.

### Crunchbase — `NOT CURRENTLY ACCESSIBLE FOR FREE`
`api.crunchbase.com/api/v4/searches/organizations` returns **HTTP 401** without credentials. No free tier was found. Not pursued further; no attempt was made to work around authentication.

### Fliar — could not be verified to exist
`fliar.io` and `fliar.com` both fail to resolve (curl exit 000, no DNS). A web search for a "Fliar" global startup funding dataset returns nothing of that name. Recorded as **source not found**; no time spent further.

---

## 4. Entity matching

Matching reuses the existing entity-resolution work rather than rebuilding it. Each company carries an ordered candidate list — current domain, decision-date domain, current name, decision-date name, every former name — built by `src/funding/build_company_identifiers.py` from the committed outcome dataset. **All 240 companies have at least one usable domain**, and 127 have more than one candidate name.

Two passes, cheapest and strongest first:

1. **YC roster.** `/accelerators/yc` lists 4,164 YC companies with cohort labels; its own summary reports **194 for "YC W24"**. Paging it costs 42 requests and resolves most of the cohort by exact YC slug.
2. **Name search**, then disambiguation on the candidate's published website.

### Two matcher defects found on the validation sample and fixed before scaling

The sample was 22 companies, deliberately mixed: 7 known-funded, 6 renamed, 4 with no prior evidence, 4 absent from the current YC directory, 1 unchanged.

**Domain queries silently return nothing.** The source's `q` matches names only — `momentic.ai` returns 0 results while `momentic` returns 1. Sending domains as queries wasted requests and lost matches. Domains are now used to *choose between* candidates rather than to search.

**A lone candidate is not automatically the right company.** Our **Lantern** is `lantern.dev`; the source's only "Lantern" is `lanternhq.com` — a different company. The first version accepted it on the strength of the name alone, reproducing exactly the same-name collision that previously produced a false Form D match. A name-only match whose domain contradicts a domain we hold is now **refused** and recorded as `AMBIGUOUS_MATCH`.

Both defects were caught on 22 companies rather than on 240.

---

## 5. Match statuses across the full cohort

| Status | Count | Share |
| --- | ---: | ---: |
| `COMPANY_FOUND_NO_EVENT_RETURNED` | 127 | 52.9% |
| `FUNDING_EVENT_FOUND` | 48 | 20.0% |
| `AMBIGUOUS_MATCH` | 38 | 15.8% |
| `COMPANY_NOT_FOUND` | 27 | 11.2% |

**None of these except the second is evidence about funding.** `COMPANY_FOUND_NO_EVENT_RETURNED` means the source knows the company and returned no round — which, given that the source is news-driven, is as likely to mean "unannounced" as "did not happen". The 38 ambiguous rows are the conservative outcome of refusing name-only matches.

Events outside the window are retained separately and never counted: **13 post-cutoff** events and **183 pre-decision or undated** ones.

---

## 6. Union and corroboration

| | Count |
| --- | ---: |
| Companies with a funding event in either source | **53** (22.1%) |
| Corroborated by both sources | 6 |
| Only Form D | 5 |
| Only Recent Funding | 42 |
| Deduplicated events | **67** |
| Reported by 2+ sources | 4 |
| Single-source | 63 |
| With a traceable URL | 60 |

The two sources are **complementary, not redundant**: 42 companies are found only by Recent Funding, and 5 only by Form D. Form D keeps its role as independent validation evidence.

### The four corroborated events, and what the disagreements look like

| Company | News date / amount | Form D date / amount | Gap |
| --- | --- | --- | ---: |
| Driver AI | 2024-10-08 | 2024-10-08 · \$8,269,998 | 0 days |
| Legora (ex Leya) | 2025-05-21 · \$80.0M | 2025-07-01 · \$79,849,626 | 41 days |
| Momentic | 2025-11-24 · \$15.0M | 2026-01-27 · \$18,609,221 | 64 days |
| Parallel (ex Kiosk) | 2026-03-18 · \$20.0M | 2026-03-31 · \$19,366,387 | 13 days |

The pattern is consistent and reassuring: the SEC filing follows the press announcement by days to weeks, and amounts agree to within a few percent. **This is a working cross-check**, and it is the practical argument for keeping Form D.

### A deduplication rule that had to be tightened

The first rule merged events when **either** the dates were close **or** the amounts agreed within 5%. On amount alone it merged a 2024-06-21 filing with a 2025-12-08 announcement for **Guide Labs** (18 months apart) and two reports nine months apart for **Tamarind Bio** — far more likely to be separate rounds of similar size than one round reported a year later. Amount agreement now additionally requires the reports to be within 120 days. Event count went from 65 to **67**.

---

## 7. Known-case recall check

| Company | Form D | Recent Funding |
| --- | --- | --- |
| Legora / Leya | 1 event | **5 events**, incl. \$25M Series A 2024-07-17 and \$550M at \$5.55B 2026-03-10 |
| Momentic | 1 event | 2 events, with TechCrunch and GlobeNewswire links |
| Tamarind Bio | 1 event | 1 event, 2026-02-24 \$13.6M |
| Guide Labs | 1 event | 1 event, 2025-12-08 \$9.0M |
| Argon AI | 1 event | company found, **no round returned** |
| Haplotype Labs | 1 event | company found, **no round returned** |
| **Trieve** | no event | **`AMBIGUOUS_MATCH` — not recovered** |

Recent Funding materially deepens the record for companies it covers — Legora goes from one event to five — but it is **not a superset of Form D**: Argon AI and Haplotype Labs are found in Form D and not here.

**The Trieve case is the clearest limitation.** Its \$3.5M September 2024 seed, which we independently verified, is missed by Form D *and* not recovered here, because the name resolves ambiguously and the domain check correctly refuses the candidates. A verified real round is absent from the union. That one case is why the recommendation is not `SUFFICIENT`.

---

## 8. Data-quality problems found

1. **Trieve-style misses.** A real, verified round absent from both sources.
2. **38 ambiguous companies (15.8%).** Conservative by design, but unresolved coverage all the same.
3. **Amounts missing on a third of events.** 42 of 63 Recent Funding events carry an amount; cumulative funding is therefore not computable for every company.
4. **Evidence quality varies.** Of 63 event URLs, many point to primary coverage (TechCrunch, GlobeNewswire, a company's own blog), but some point to aggregator pages (`fundraisingfox.com`) or Google News RSS redirects, which are weaker provenance and should be spot-checked before any event is used.
5. **Date and amount disagreements** on 6 and 4 merged events respectively — all small and explainable, but they must be carried, not averaged away.
6. **Key fragility.** The Recent Funding key used here expires within 24 hours; the standing free tier is 100 requests/day.

---

## 9. Recommendation: `PROMISING BUT NEEDS VALIDATION`

**Not `SUFFICIENT`**, because:

- 22.1% of the cohort showing any funding event is implausibly low as a true rate for a YC batch two years after Demo Day, so the remaining 77.9% cannot be read as "did not raise" — which is precisely the inference primary Y would need;
- a verified round (Trieve) is missing from the union;
- 15.8% of the cohort is unresolved;
- a third of events lack an amount, so a cumulative-funding measure would be partly blank.

**Not `INSUFFICIENT`**, because the improvement over the baseline is large and real: 4.4× the funded companies, every event dated and linked, and four events independently corroborated against SEC filings with a consistent, explainable offset.

### What would move this to `SUFFICIENT`

1. Resolve the 38 ambiguous and 27 not-found companies, by hand if necessary — 65 companies is tractable.
2. Add one more independent source with real history. Dealroom and Tracxn remain untested; Crunchbase remains the obvious paid or academic option and is worth one request to the sponsor's network.
3. Spot-check a sample of event URLs to confirm each supports the round it is attached to.
4. Decide how `COMPANY_FOUND_NO_EVENT_RETURNED` is treated in Y. It must not silently become zero.

Until then **funding stays `PENDING_BETTER_DATA_SOURCE` in the canonical dataset**, which this benchmark does not modify.

---

## 10. Files

Code, under `src/funding/`:

| File | Purpose |
| --- | --- |
| `build_company_identifiers.py` | ordered query identifiers per company + the validation sample |
| `sources.py` | shared client, rate limiting, the match-status taxonomy |
| `fetch_recentfunding_yc.py` | pages the YC roster, keeps the W24 cohort |
| `run_recentfunding_benchmark.py` | resolves each company, pulls and windows its rounds |
| `analyze_funding_benchmark.py` | coverage, union, corroboration, deduplication |

Data, under `data/interim/funding_source_benchmark/`:

| File | Rows | Purpose |
| --- | ---: | --- |
| `company_identifiers.csv` | 240 | query identifiers per company |
| `validation_sample.csv` | 22 | the mixed pre-scale sample |
| `recentfunding_yc_roster.csv` | 194 | the source's own W24 roster |
| `recentfunding_company_matches.csv` | 240 | per-company status and counts |
| `recentfunding_events_raw.csv` | 259 | every round, windowed and labelled |
| `funding_source_coverage.csv` | 2 | the comparison table |
| `funding_source_overlap.csv` | 240 | per-company, which source found what |
| `funding_events_deduplicated.csv` | 67 | merged events with provenance |
| `raw_recentfunding/*.json` | — | cached API responses — **kept locally, gitignored**, not redistributed; regenerate with the fetch scripts |

API keys live in a local `.env` and are gitignored. None is committed.

---

## 11. What was deliberately not done

No Funding Y was constructed. No composite or weighted funding score was created. `w24_raw_outcomes_24m.csv` was not modified. DIALECTIC was not run and the multi-agent committee was not run. The cohort, decision date and outcome window were not changed.
