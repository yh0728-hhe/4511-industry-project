# Historical X — 240-company first collection

Cutoff: **2024-04-04**. The dataset covers all240 original cohort rows, with explicit evidence gaps.

- **57** companies: archived YC structured fields recovered by cutoff.
- **24** companies: exact-name dated HN titles; these overlap with6 archived profiles.
- **75** unique companies with a dated source; **165** still have evidence gaps.
- **0** model-ready packets. No investment ranking or market-size verification.

`company_historical_data.csv` is the flat overview. `company_packets.json` contains the original spreadsheet observation, archived product/team/founder fields, dated HN references, provenance and unknowns. `manifest.json` hashes inputs and reports source-query failures separately from successful empty results.

Archived fields are historical company self-reports. Local spreadsheet label dates do not prove external availability. Missing team size stays blank; market size/revenue are not invented. HN titles do not establish biographies or traction. No Y data is read to build these inputs.

Reproduce offline: `python src/historical_x/build_cohort_historical_dataset.py`. Curated extracted fields are included; raw page bodies are retained locally and not needed for deterministic reconstruction. Collection paused after Internet Archive429; do not bypass the rate-limit stop or interpret failures as source absence.

Full record: `docs/research_log/2026-11-05_historical_x_full_cohort.md`.
