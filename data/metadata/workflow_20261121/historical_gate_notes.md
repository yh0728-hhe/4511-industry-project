# Historical gate verification — 2026-11-21

Task: historical identity & archive verification only, for Adagy (Task1/Task2), with
Task3 fallback if no usable record. Source prompt:
`docs/workflow_automation_20261121/muse_historical_gate_prompt.md`
(branch `auto/workflow-readiness-20261121`).

**Cutoff: 2024-04-04T23:59:59Z.** Only evidence of identity / historical domain /
readable archive snapshots at or before the cutoff counts as historical evidence.
Current financing and shutdown status were NOT checked for any company. Current
websites, current branding and current founder bios are identity context only,
never historical business evidence. Seed domains were not replaced.

**Archive availability rule applied throughout: absence of exact snapshot evidence
=> UNKNOWN, not "company did not exist".**

Reading grades: BODY = full text read; SUMMARY = search-result snippet only;
REUSE = prior verified notes; RESTRICTED = access denied (403), stopped, not
retried; NOT_LOCATED = searched, not found.

All web reads were performed 2026-11-21 ~21:49–21:51 UTC (page crawl stamps shown
by the fetch tool). Spreadsheet rows read from
`data/processed/w24_spreadsheet_2024-03-25.csv` (241 lines incl. header).

---

## 1. Adagy Robotics (company_id: tuesday-labs)

### 1.1 Identity — ESTABLISHED by dated artifacts

Three pre-cutoff artifacts bind name + founders + domain:

1. **Spreadsheet (2024-03-25)** — BODY (repository file).
   Row: Company Name "Adagy Robotics", Website https://www.adagyrobotics.com/,
   YC Link https://www.ycombinator.com/companies/adagy-robotics,
   description "Rescuing robots", Date Launched 2024-01-31,
   Founder Link 1 https://linkedin.com/in/rosalind-shinkle,
   Founder Link 2 https://linkedin.com/in/kathleen-brandes-4b1a09103.
   Date semantics: spreadsheet snapshot date 2024-03-25 (pre-cutoff);
   "Date Launched 2024-01-31" is a spreadsheet claim, not independently
   confirmed from the launch post itself (see limitations).

2. **Hardware FYI (dated Mar 5, 2024)** — BODY.
   URL: https://www.hardwarefyi.com/startup-news/adagy-robotics-ycw24-have-launched/
   "Adagy Robotics (YCW24) have launched. The company is developing an
   intervention service for autonomous robots (freeing them when stuck, etc)."
   The company name links to www.adagyrobotics.com; "have launched" links to the
   YC launch post (below); Source: ycombinator.com.
   Date semantics: article publication date 2024-03-05 (pre-cutoff). This is a
   dated secondary artifact proving that by 2024-03-05 the name "Adagy Robotics"
   was publicly bound to adagyrobotics.com and to a YC launch post.

3. **YC launch post** — located, content NOT readable in extraction.
   URL: https://www.ycombinator.com/launches/KVF-adagy-robotics-rescuing-robots
   The slug itself confirms the post name "adagy-robotics-rescuing-robots"
   (name + spreadsheet description). The fetched extraction contained only
   generic YC template text (32 lines); launch body, created_at and byline
   were not exposed (JS-rendered). Existence of the post by 2024-03-05 is
   proven by the Hardware FYI link above.

Founder corroboration (identity context, post-cutoff publication):
europeantech.news interview, Published 2024-04-29T13:01:47+00:00 (after cutoff,
identity context only) — quotes Ros Shinkle (CEO) and Kathleen Brandes (CTO),
"Adagy launched earlier this year", photo caption "Ros Shinkle and Kathleen
Brandes, the founders of Adagy Robotics, met at Boston Dynamics. Source:
Y Combinator", links www.adagyrobotics.com.

Current YC company page (identity context only, read 2026-11-21 21:49 UTC):
title "Tuesday Labs: Delightful robots"; Ros (Rosalind Shinkle) described as
Tuesday Labs founder/CEO, former Boston Dynamics Staff Robotics Engineer.
Current branding only; not historical evidence.

**Rename:** Adagy Robotics → Tuesday Labs (current brand). Rename date:
UNKNOWN — no dated rename evidence found; cannot say whether the rename
happened before or after the cutoff. No evidence that the Tuesday Labs brand
or tuesdaylabs.com domain was in use before the cutoff. Adagy Robotics is the
original name (founded 2023 under that name; multiple sources consistent);
no earlier predecessor brand found. Seed domain adagyrobotics.com kept as-is
(not replaced).

### 1.2 Archive availability — UNKNOWN (RESTRICTED)

Wayback CDX query for adagyrobotics.com with to=20240404 returned HTTP 403
(access denied). Per task discipline: recorded as RESTRICTED, stopped, not
retried; the www variant was not queried (same endpoint, new parameters would
be a retry). Codex's first probe ("CDX 200, no qualifying snapshot, exact
domain") could not be independently reproduced in this run.

Therefore: **no readable pre-cutoff snapshot was obtained; archive availability
is UNKNOWN.** This is NOT evidence that no snapshot exists, and NOT evidence
that the company did not exist. Task2 (homepage + up to 2 pre-cutoff links)
could not be executed because no capture could be enumerated or read.

### 1.3 Disposition

Identity established (Adagy Robotics / Rosalind Shinkle + Kathleen Brandes /
adagyrobotics.com) as of the cutoff, via dated artifacts. No readable
pre-cutoff archive snapshot => Task3 trigger condition met ("no readable
pre-cutoff snapshot"), Task3 executed below.

Limitations:
- YC launch post created_at/byline not readable (extraction gap); the
  2024-01-31 launch date rests on the spreadsheet claim only.
- Wayback CDX 403 RESTRICTED; archive availability UNKNOWN.
- Rename date to Tuesday Labs UNKNOWN.

---

## 2. Task3 selection rule

Task3 triggered because Task1+2 yielded identity but **no readable pre-cutoff
archive snapshot**. Selection rule (recorded in advance, fixed): alphabetical
order by spreadsheet Company Name, excluding sealed Abel and target Adagy
Robotics. First two after exclusion: **Aedilic, Aether Energy** (order:
Abel, Adagy Robotics, Aedilic, Aether Energy, AgentHub, …). Selection is
purely alphabetical; no current financing/status/success information was
consulted or used as a selection basis.

---

## 3. Aedilic (company_id: Aedilic — ID source: spreadsheet Company Name)

### 3.1 Identity

- **Spreadsheet (2024-03-25)** — BODY. Row: "Aedilic",
  Website https://www.aedilic.com, YC Link
  https://www.ycombinator.com/companies/aedilic, description "Longer-range
  delivery using fixed-wing drones", Date Launched 2024-03-18,
  Founder Link 1 https://linkedin.com/in/nicholas-waltz-b95067211,
  Founder Link 2 https://linkedin.com/in/lukas-schneider-a27498177.
- **YC company page (current, identity context only)** — BODY, 65 lines,
  read 2026-11-21 21:51 UTC. Title: "Aedilic: Open-Source AI-generated
  image/deepfake detection". Body: "Hi, we're Nico and Lukas, the cofounders
  of Aedilic (doing business as GPUDeploy)"; mentions "the previous iteration
  of this startup (robotics-related)"; contact nico@gpudeploy.com.
  Founders Nico (Nicholas Waltz) + Lukas (Schneider) match the spreadsheet.
  The current tagline (deepfake detection) and GPUDeploy (GPU rental) content
  are post-cutoff pivots and must NOT be treated as pre-cutoff business
  evidence; the drone-delivery description is the cutoff-era one per the
  spreadsheet.
- **YC launch post** — NOT_LOCATED. Two searches did not surface a launch URL;
  the current YC page body is the later GPUDeploy launch text. Date Launched
  2024-03-18 therefore rests on the spreadsheet claim only.
- Search summaries (SUMMARY) consistently name founders Nicholas Waltz +
  Lukas Schneider and website aedilic.com. Financing/status fields appearing
  in snippets were out of scope and not used.

### 3.2 Archive availability — UNKNOWN (RESTRICTED)

Wayback CDX endpoint returned HTTP 403 earlier in this task; per discipline
it was not retried with new parameters. **Archive availability UNKNOWN —
absence of snapshot evidence is not evidence the company did not exist.**

### 3.3 Disposition

Identity basis: spreadsheet (name, aedilic.com, founders, Date Launched
2024-03-18) + current YC page founder match (context only). No readable
pre-cutoff archive snapshot.

---

## 4. Aether Energy (company_id: Aether Energy — ID source: spreadsheet Company Name)

### 4.1 Identity — ESTABLISHED by dated original YC launch post

- **Spreadsheet (2024-03-25)** — BODY. Row: "Aether Energy",
  Website https://aetherenergie.com/, YC Link
  https://www.ycombinator.com/companies/aether-energy, description "AI design
  and workflow software for solar installers worldwide",
  Date Launched 2024-03-03,
  Founder Link 1 https://linkedin.com/in/shelby-bons-ucberkeley,
  Founder Link 2 https://linkedin.com/in/zaynesager.
- **YC launch post (original artifact)** — BODY (full JSON), read
  2026-11-21 21:51 UTC.
  URL: https://www.ycombinator.com/launches/KZ3-aether-energy-ai-platform-for-rooftop-solar
  - title: "Aether - AI platform for rooftop solar"
  - tagline: "Aether is AI design and workflow software for solar installers."
  - body: "[Aether](https://aetherenergie.com/) offers an AI-powered
    end-to-end platform for rooftop solar installers."; "we're Shelby Bons
    (https://linkedin.com/in/shelby-bons-ucberkeley) and Zayne Sagar
    (https://linkedin.com/in/zaynesager), two climate entrepreneurs!";
    contact zsagar@aetherenergy.me.
  - created_at: 2024-03-05T02:02:09.486Z (pre-cutoff); batch: Winter 2024.
  Date semantics: launch-post creation timestamp. Note the spreadsheet's
  Date Launched 2024-03-03 differs from created_at 2024-03-05 by 2 days;
  both are pre-cutoff and are recorded as-is, not force-merged.
- **YC company page (current, identity context only)** — BODY, 101 lines.
  Title: "Feldy: Field-First AI for home services" (feldy.ai). Founders
  Zayne + Shelby match the spreadsheet/launch. Feldy is a later rebrand;
  rebrand date UNKNOWN; current content must not be treated as pre-cutoff
  evidence. The cutoff-era name is Aether Energy, domain aetherenergie.com.

### 4.2 Archive availability — UNKNOWN (RESTRICTED)

Wayback CDX endpoint returned HTTP 403 earlier in this task; not retried.
**Archive availability UNKNOWN — absence of snapshot evidence is not
evidence the company did not exist.**

### 4.3 Disposition

Identity established by dated original YC launch post (Aether Energy /
Shelby Bons + Zayne Sagar / aetherenergie.com, created_at 2024-03-05).
No readable pre-cutoff archive snapshot.

---

## 5. Unread / not-attempted list (honest gaps)

- Wayback CDX for www.adagyrobotics.com, aedilic.com, aetherenergie.com:
  not queried (endpoint 403 RESTRICTED on first query; no retries with new
  parameters per discipline). Codex's earlier "CDX 200, no qualifying
  snapshot (exact domain)" for Adagy was not independently reproduced.
- Adagy YC launch post body/created_at/byline: page located, extraction
  returned only generic template text; launch content unread.
- Aedilic YC launch post: NOT_LOCATED in search.
- Current websites of all three companies: deliberately not read as
  historical evidence (out of scope for the historical gate).
- Financing and shutdown status of all three companies: deliberately not
  checked (out of scope).
- Rename dates (Adagy→Tuesday Labs; Aether Energy→Feldy): no dated evidence
  found; UNKNOWN.
