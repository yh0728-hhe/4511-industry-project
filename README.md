# 4511 Industry Project — Startup Data Inventory

**Recommendation: use the historical Crunchbase data to prepare an initial baseline, and use YC company profiles to test research agents.**

The files below were downloaded in the local research workspace on **October 21, 2026**. Their row counts, columns, and file hashes were checked again on **October 22, 2026**. They are candidate research data; no model has been trained or evaluated using them.

## Data found and available to download

| Dataset | Verified count | Contents and potential use | Direct download |
| --- | ---: | --- | --- |
| Crunchbase company profiles | **66,368 companies** | Names, websites, industries, countries, founding dates, total funding, and `operating` / `acquired` / `closed` / `ipo` status. Useful for exploring coverage and defining a historical company cohort. | [companies.csv](https://raw.githubusercontent.com/notpeter/crunchbase-data/master/companies.csv) |
| Crunchbase funding rounds | **114,949 records** | Funding dates, types, round codes, and amounts. Useful for constructing recorded funding sequences and potential labels such as whether a company subsequently raises Series A. | [rounds.csv](https://raw.githubusercontent.com/notpeter/crunchbase-data/master/rounds.csv) |
| Crunchbase acquisitions | **18,968 records** | Acquired companies, buyers, acquisition dates, and some transaction prices. Useful for identifying recorded acquisition events. | [acquisitions.csv](https://raw.githubusercontent.com/notpeter/crunchbase-data/master/acquisitions.csv) |
| YC company directory | **6,320 companies** | Company descriptions, websites, industries, YC batches, team sizes, and current status. Useful for testing company research, evidence collection, and evidence organization. | [companies.json](https://yc-oss.github.io/api/companies/all.json) |

Counts refer to the downloaded snapshots, not guaranteed live counts. The YC endpoint changes over time. Company and event counts overlap and **must not be added together as a total number of startups**.

The raw datasets remain in the local research workspace under `data_sources/2026-10-21/`. This repository contains the inventory and audit metadata, with links to the original downloads. See the [data manifest](docs/data_manifest.json) for all six files' source URLs, exact columns, row counts, byte sizes, SHA-256 hashes, and missing-value counts.

## Three limits that matter before modeling

1. **Crunchbase ends at December 4, 2015.** These files are an unofficial CSV conversion of a historical export, suitable for initial historical exploration rather than a description of today's startup market. The [source repository](https://github.com/notpeter/crunchbase-data) states **CC BY-NC 4.0**. Permission for the intended Golden Gate project use still needs confirmation; public download availability does not establish that permission.

2. **YC is a current community mirror, not a historical funding database.** The [YC community API](https://github.com/yc-oss/api) is not an official YC API and does not provide a complete sequence of historical funding events in this file. Today's company descriptions, team sizes, and status cannot automatically be used as inputs for past investment decisions. Reuse terms have not been established in this inspection.

3. **Company status is not investment return.** `operating` does not mean failure, and `acquired` does not establish a profitable investment. Before backtesting, define the decision date and follow-up period. Exclude information that became available after the decision date, including later funding totals or status. Missing follow-up should remain unknown rather than automatically becoming a failure label.

## How the data can be connected

- Use `companies.permalink` to match `rounds.company_permalink` and `acquisitions.company_permalink`; company names are not reliable unique identifiers.
- Funding and acquisition tables contain event rows, so a company may appear more than once. Check matching coverage and repeated identifiers. Aggregate events for the chosen decision date before combining the tables into a company-level analysis.
- YC uses separate company IDs. Any matching between YC and Crunchbase needs a verified company or domain mapping.
- Event dates help separate earlier records from later outcomes, but do not by themselves prove that every field was known at the decision date.

The audit also found **19,990 funding records with no raised amount** and **13,956 acquisition records with no price amount**. Blank amounts mean unknown, not zero. The company table contains **12,785 `-` values in `funding_total_usd`**, which also need explicit missing-value handling.

## Optional supplementary data

| Source | What is available | Appropriate use and limitation |
| --- | --- | --- |
| [SEC Form D datasets](https://www.sec.gov/data-research/sec-markets-data/form-d-data-sets) | Located, **not yet downloaded or matched**. Dated US exempt-offering filings. | Potential supplementary fundraising evidence. These filings do not cover all venture funding and are not direct Series A or investment-success labels. |
| [YC Bench](https://github.com/benstaf/ycbench) | Two downloaded CSVs: **198 company rows** and **184 score rows**. | Optional short-term traction or visibility comparison. Match domains and inspect unmatched records before use. These proxy scores are not suitable as the main investment-success label; reuse terms remain unverified. |

YC Bench direct downloads:

- [Company list — yc_w26_startups.csv](https://raw.githubusercontent.com/benstaf/ycbench/main/yc_w26_startups.csv)
- [Score table — yc_w26_pre_demo_scores.csv](https://raw.githubusercontent.com/benstaf/ycbench/main/yc_w26_pre_demo_scores.csv)

The six inspected files are the four main files above plus these two YC Bench files. The YC Bench README reports 196 companies; the counts shown here come from the downloaded files.

## File downloads versus API access

| Source | Access method |
| --- | --- |
| Crunchbase 2015 export | Static CSV downloads; no API key used. |
| YC company directory | Public JSON API; retrieved successfully without an API key. |
| YC Bench | Static GitHub CSV downloads; no API key used. |
| Official Crunchbase API | Separate licensed access requiring provisioned credentials. The offered access has **not yet been tested or used** for these downloads. |

Before relying on the offered [official Crunchbase API](https://data.crunchbase.com/docs/using-the-api), confirm available fields, request quotas, access expiry, permitted use, and whether historical snapshots are included. Having an API key does not establish that the data available at a past investment decision can be reconstructed.

## Decisions needed before building the model

Agree on the company cohort, outcome definition, decision date, and observation period. Define how research quality will be assessed, including support for claims, source citations, and identification of missing evidence. Then prepare a small joined sample, review its coverage and missingness, and validate the offered API access.

The inspected files do not provide verified revenue, retention, churn, customer acquisition cost, customer concentration, or pitch-deck information. Those would require additional dated company evidence or authorized project materials.

## Project updates

### 2026-10-29 — W24 Demo Day Backtest Design

The project has moved from the initial data inventory above toward a **historical investment-decision backtest**: simulating an external VC deciding, at YC Winter 2024 Demo Day (**2024-04-03 / 04**), whether to invest in each W24 startup, and comparing those decisions against outcomes 24 months later.

The data inventory in this README remains the record of the 2026-10-21/22 stage and is unchanged.

Full design: [`docs/research_log/2026-10-29_w24_backtest_design.md`](docs/research_log/2026-10-29_w24_backtest_design.md)

In brief:

- **Decision point** is Demo Day, not founding date, YC entry, or the first available `yc-oss` snapshot.
- **Primary cohort** is the 240 companies in the dated 2024-03-25 W24 spreadsheet, chosen because it is clearly dated *before* Demo Day. 240 is not a claim about official attendance — four sources report four different W24 universe sizes.
- **Eligibility and evidence coverage are kept separate.** Failing to recover a historical page does not show that a company was absent from W24.
- **`Y` is not yet collapsed to success/failure.** Survival, follow-on financing, acquisition, team growth, and evidence quality are preserved separately.
- The system may output **`INVEST` / `PASS` / `MORE DD`**, where `MORE DD` means the evidence is insufficient rather than forcing a binary call.
- The **stopping rule is still unresolved** and is not presented as settled.

Pipeline code is under [`src/`](src/README.md); derived tables and their cautions are under [`data/`](data/metadata/w24_backtest_datasets.md).

Future major methodological changes should get their own dated research-log file rather than overwriting this one.

### 2026-10-29 — Raw 24-month outcome dataset and Y methodology decisions

Y has been recorded for the 240-company cohort as **raw, separate dimensions**, with no success/failure label and no weighted score. Survival (95.0% resolved at the endpoint) and team growth (97.1%) are usable; acquisition is kept as an event only, since no acquirer or transaction amount is public for any company in the cohort; follow-on funding is held at `PENDING_BETTER_DATA_SOURCE` because SEC Form D recall on this cohort is only 4.6%.

The 24-month horizon stays 2024-04-04 → 2026-04-04. It is not observable directly: yc-oss stopped updating for 86 days across the cutoff, so 8 companies are carried as an explicit `ENDPOINT_UNCERTAIN` set rather than resolved by assumption.

Coverage and quality: [`docs/research_log/2026-10-29_raw_outcome_coverage.md`](docs/research_log/2026-10-29_raw_outcome_coverage.md)
Sponsor update (open the file locally to view it rendered): [`docs/updates/W24_Historical_Backtest_Update.html`](docs/updates/W24_Historical_Backtest_Update.html)
Decisions, corrections and uncertainty sets: [`docs/research_log/2026-10-29_y_methodology_decisions.md`](docs/research_log/2026-10-29_y_methodology_decisions.md)
