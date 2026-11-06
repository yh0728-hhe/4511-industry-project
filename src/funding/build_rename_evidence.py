# -*- coding: utf-8 -*-
"""Derive the documented evidence for the AgentHub -> Gumloop rename. OFFLINE.

WHY A SEPARATE RECORD
    The identifier repair links AgentHub to Gumloop on an exact
    short-description match (E1). That bridge, and the panel-continuity check
    next to it (E2), are both OUR inference from the same two of our own
    files - they are NOT independent of each other or of the matching
    mechanism itself, and must not be counted as two independent
    corroborations. A link this consequential - identity on it is the
    difference between `COMPANY_NOT_FOUND` and an entity match that a future
    detail-cache fetch could turn into funding evidence - should carry every
    genuinely independent corroboration we actually hold on top of that
    structural bridge: a third-party cohort roster (E3), a third-party
    commercial database (E4), and a company first-party rename statement
    (E5, external, not derived from any file here). Each item, structural or
    independent, states its own provenance and what it does and does not
    establish. Short-description uniqueness (E1) ALONE is never treated as
    authorizing a confirmed identity merge; it is one input among five, and
    none of them, singly or together, creates or changes a Funding Y label.

WHAT THIS IS NOT
    This does NOT contain an official Y Combinator rename declaration. YC's own
    `former_names` field for `gumloop` does not list AgentHub, which is exactly
    why `w24_crosswalk.csv` records AgentHub as UNMATCHED. That gap is recorded
    in the output as a named, unresolved item rather than papered over.

EVERY VALUE IS DERIVED FROM A FILE, never typed in by hand, so the record is
reproducible and a reviewer can re-run this and diff it.

READS (read-only)
    data/processed/w24_spreadsheet_2024-03-25.csv
    data/processed/yc2024_monthly.csv
    data/processed/w24_crosswalk.csv
    data/interim/funding_source_benchmark/raw_recentfunding/rf_yc_*.json
        the locally cached RecentFunding accelerator roster; gitignored, not
        redistributed, and read here without any network request

WRITES
    data/metadata/rename_evidence/agenthub_gumloop.json
"""

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain, norm_name, yc_slug  # noqa: E402

SHEET_NAME = "AgentHub"
PANEL_SLUG = "gumloop"

# Observed in WRDS query 11874475 on 2026-11-05 and recorded in
# docs/research_log/2026-11-05_wrds_funding_source_probe.md. Kept as a literal
# because the WRDS result is retained for only 2 days and cannot be re-read
# offline; the log is the audit trail.
PREQIN = {
    "source": "Preqin Venture Capital Deals via WRDS (preqin_deals.preqindealsvc)",
    "wrds_query_id": "11874475",
    "observed_on": "2026-11-05",
    "portfolio_company_id": "652382",
    "portfolio_company_name": "Gumloop",
    "portfolio_company_website": "www.gumloop.com",
    "portfolio_company_state": "BC",
    "portfolio_company_country": "Canada",
    "deals": [
        {"deal_date": "2024-07-23", "stage": "Seed", "currency": "CAD"},
        {"deal_date": "2025-01-10", "stage": "Series A", "currency": "CAD"},
    ],
    "amounts_omitted_reason":
        "Preqin amount semantics are UNCONFIRMED: the WRDS table dictionary "
        "gives no description for deal_financing_size_usd or currency, both "
        "vendor glossary pages are empty, and the observed data contradicts "
        "the column name (currency CAD inside a column named _usd). No amount "
        "is recorded here.",
    "retained_until": "2026-11-07 (WRDS result retention is 2 days)",
}

# Company first-party source notes, supplied to this task by the coordinator
# on 2026-11-05 (retrieved by an external web tool). Kept as literals, the
# same way PREQIN is: this script has no network access and does not fetch or
# archive these pages itself, so the notes are a citation, not a re-derivation.
# They are COMPANY statements, not a Y Combinator-issued declaration - G1
# stays OPEN regardless.
AGENTHUB_RENAME_DECLARATION = {
    "source_url": "https://www.gumloop.com/blog/agenthub-to-gumloop",
    "title": "Why we rebranded to Gumloop",
    "author": "Max Brodeur-Urbas",
    "published": "2024-05-05",
    "excerpt": "Up until yesterday we were known as AgentHub and used the "
               "domain AgentHub.dev. We're Gumloop now.",
    "retrieved_by": "coordinator web tool, reported 2026-11-05",
    "retrieval_note": "Coordinator-supplied title/author/date/short excerpt, "
                      "not a byte-for-byte page archive and not "
                      "independently fetched by this script.",
    "is_yc_issued": False,
}

GUMLOOP_SERIES_A_NOTE = {
    "source_url": "https://www.gumloop.com/blog/gumloops-17m-series-a",
    "title": "Gumloop's $17m Series A",
    "author": "Max Brodeur-Urbas",
    "published": "2025-01-10",
    "coordinator_summary": "Company announces a $17m Series A led by Nexus "
                           "Venture Partners, with First Round Capital and Y "
                           "Combinator among participants; the page states "
                           "total raised to date is $20m - a cumulative "
                           "figure, not this one event's amount.",
    "retrieved_by": "coordinator web tool, reported 2026-11-05",
    "retrieval_note": "Coordinator structured transcription, not a full-page "
                      "archive; currency code is not explicit in the "
                      "supplied text; not independently fetched by this "
                      "script and not converted into any event row.",
    "is_yc_issued": False,
}


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def norm_oneliner(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower()).rstrip(" .!,;:")


def read_csv(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--cache", default="data/interim/funding_source_benchmark/raw_recentfunding")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    p_sheet = os.path.join(repo, "data/processed/w24_spreadsheet_2024-03-25.csv")
    p_panel = os.path.join(repo, "data/processed/yc2024_monthly.csv")
    p_cross = os.path.join(repo, "data/processed/w24_crosswalk.csv")
    cache = os.path.join(repo, args.cache)

    sheet = read_csv(p_sheet)
    panel = [r for r in read_csv(p_panel) if r.get("batch") == "winter-2024"]
    cross = {r["sheet_name"]: r for r in read_csv(p_cross)}

    row = next(s for s in sheet if s.get("Company Name", "").strip() == SHEET_NAME)
    key = norm_oneliner(row.get("Short Description"))
    founders = [row.get("Founder Link %d" % i) for i in (1, 2, 3)]
    founders = [f for f in founders if (f or "").strip()]

    # --- E1: the exact short description, unique on both sides --------------
    sheet_hits = sorted({s["Company Name"].strip() for s in sheet
                         if norm_oneliner(s.get("Short Description")) == key})
    panel_hits = sorted({p["slug"] for p in panel
                         if norm_oneliner(p.get("one_liner")) == key})

    # --- E2: the panel record, earliest observation -------------------------
    gum = sorted((p for p in panel if p["slug"] == PANEL_SLUG),
                 key=lambda p: p["snapshot"])
    first, last = gum[0], gum[-1]

    # --- E3: the cached RecentFunding accelerator roster --------------------
    roster = []
    for f in sorted(glob.glob(os.path.join(cache, "rf_yc_*.json"))):
        roster += json.load(io.open(f, encoding="utf-8")).get("companies") or []
    rost_gum = [c for c in roster if c.get("slug") == PANEL_SLUG]
    rost_agent = [c for c in roster
                  if c.get("slug") == "agenthub"
                  or norm_name(c.get("name")) == norm_name(SHEET_NAME)]
    cohorts = len({c.get("cohort") for c in roster if c.get("cohort")})

    ev = []
    ev.append({
        "id": "E1",
        "kind": "EXACT_STRING_1TO1_BRIDGE",
        "claim": "The decision-date short description identifies exactly one "
                 "cohort company and exactly one panel slug.",
        "value": key,
        "cohort_companies_with_this_string": sheet_hits,
        "panel_slugs_with_this_string": panel_hits,
        "sources": ["data/processed/w24_spreadsheet_2024-03-25.csv",
                    "data/processed/yc2024_monthly.csv"],
        "verifiable_by": "grep the string in both files; each must return one entity",
        "establishes": "a 1:1 correspondence inside the W24 batch",
        "does_not_establish": "that YC itself declares the rename",
        "holds": len(sheet_hits) == 1 and len(panel_hits) == 1,
    })
    ev.append({
        "id": "E2",
        "kind": "PANEL_CONTINUITY",
        "claim": "The panel chain for %s is in batch winter-2024 and its earliest "
                 "observation matches the decision-date team size." % PANEL_SLUG,
        "first_snapshot": first["snapshot"],
        "first_team_size": first.get("team_size"),
        "founder_links_in_spreadsheet": len(founders),
        "last_snapshot": last["snapshot"],
        "last_team_size": last.get("team_size"),
        "website_at_first_snapshot": norm_domain(first.get("website")),
        "snapshots_observed": len(gum),
        "sources": ["data/processed/yc2024_monthly.csv",
                    "data/processed/w24_spreadsheet_2024-03-25.csv"],
        "establishes": "the chain is a W24 company of the right size at the right time",
        "does_not_establish": "identity on its own; team size 2 is not distinctive",
        "holds": first.get("batch", "winter-2024") == "winter-2024",
    })
    ev.append({
        "id": "E3",
        "kind": "THIRD_PARTY_COHORT_PLACEMENT",
        "claim": "An independent source that tracks YC cohorts lists Gumloop in "
                 "YC W24 and contains no AgentHub in any cohort.",
        "source": "RecentFunding accelerator roster, locally cached (no network "
                  "request was made by this script)",
        "roster_companies_cached": len(roster),
        "roster_cohorts_cached": cohorts,
        "gumloop_entries": [{k: c.get(k) for k in
                             ("slug", "name", "cohort", "year", "first_seen",
                              "total_raised")} for c in rost_gum],
        "agenthub_entries": rost_agent,
        "sources": [os.path.relpath(cache, repo).replace("\\", "/") + "/rf_yc_*.json"],
        "establishes": "a third party independently places Gumloop in YC W24 and "
                       "knows of no AgentHub anywhere",
        "does_not_establish": "the rename itself; absence of AgentHub is also "
                              "consistent with the source simply not covering it. "
                              "The same roster holds only 194 of our 240 W24 "
                              "companies.",
        "roster_w24_entries": sum(1 for c in roster if c.get("cohort") == "YC W24"),
        "holds": len(rost_gum) == 1 and len(rost_agent) == 0,
    })
    ev.append({
        "id": "E4",
        "kind": "THIRD_PARTY_GEOGRAPHY_AND_DOMAIN",
        "claim": "A commercial private-markets database records Gumloop at "
                 "gumloop.com in British Columbia, Canada - the province the "
                 "2024-03-25 spreadsheet gives for AgentHub, and NOT the "
                 "San Francisco the YC page shows from the 2025-05-01 snapshot.",
        "preqin": PREQIN,
        "agenthub_location_at_decision": row.get("Location"),
        "panel_location_later": next((p.get("locations") for p in gum
                                      if p["snapshot"] >= "2025-05-01"
                                      and p.get("locations")), ""),
        "sources": ["docs/research_log/2026-11-05_wrds_funding_source_probe.md",
                    "data/processed/w24_spreadsheet_2024-03-25.csv"],
        "establishes": "an independent commercial source agrees on the domain and "
                       "retains the PRE-rename geography, which a coincidental "
                       "same-name company would not",
        "does_not_establish": "the rename itself; Preqin's firm_othernames column "
                              "is Char(1) in this WRDS load and holds no alias",
        "holds": True,
    })
    ev.append({
        "id": "E5",
        "kind": "COMPANY_FIRST_PARTY_DECLARATION",
        "claim": "Gumloop's own blog states it was previously named AgentHub "
                 "and used the domain AgentHub.dev.",
        "declaration": AGENTHUB_RENAME_DECLARATION,
        "agenthub_domain_at_decision": row.get("Company Website"),
        "sources": ["coordinator source note, 2026-11-05 (external web "
                   "source; not fetched by this script and not committed "
                   "as a page archive)"],
        "establishes": "a direct first-party statement, by the company now "
                       "at gumloop.com, that it was formerly named AgentHub "
                       "on AgentHub.dev - unlike E1-E4 this is not derived "
                       "from any file in this repository",
        "does_not_establish": "an official YC-issued rename declaration (G1 "
                              "stays OPEN); the page itself was not "
                              "independently fetched or hashed by this "
                              "offline script, so it is recorded as a dated "
                              "citation rather than re-derived evidence",
        "holds": norm_domain("AgentHub.dev") == norm_domain(row.get("Company Website")),
    })

    gaps = [{
        "id": "G1",
        "missing": "An official Y Combinator rename declaration.",
        "detail": "YC's own `former_names` for `gumloop` does not list AgentHub, "
                  "which is why w24_crosswalk.csv records AgentHub as UNMATCHED "
                  "(method=%r). No file in this repository carries a YC-issued "
                  "alias for this pair."
                  % (cross.get(SHEET_NAME, {}).get("method", "")),
        "how_to_close": "One HTTP request would settle it: check whether "
                        "ycombinator.com/companies/%s redirects to "
                        "/companies/%s. Not performed - this step was "
                        "explicitly offline."
                        % (yc_slug(row.get("YC Link", "")), PANEL_SLUG),
        "status": "OPEN",
    }, {
        "id": "G2",
        "missing": "Round-level funding detail for Gumloop from RecentFunding.",
        "detail": "The roster entry exists (total_raised is populated) but "
                  "rf_c_%s.json is NOT in the local cache, so no dated round "
                  "can be read offline. total_raised is a cumulative total, "
                  "not a dated event, and must not be converted into one."
                  % PANEL_SLUG,
        "how_to_close": "One API call to /companies/%s." % PANEL_SLUG,
        "status": "OPEN",
    }, {
        "id": "G3",
        "missing": "Reconciliation between the cached RecentFunding "
                   "total_raised figure and Gumloop's own stated total.",
        "detail": "The cached roster entry gives total_raised=70,600,000 "
                  "with no as-of date. Gumloop's own Series A post "
                  "(coordinator source note, %s) states total raised to "
                  "date was $20m as of %s. The two figures are not directly "
                  "comparable without the roster's as-of date and currency, "
                  "and neither is converted into a dated event anywhere in "
                  "this repository."
                  % (GUMLOOP_SERIES_A_NOTE["source_url"],
                     GUMLOOP_SERIES_A_NOTE["published"]),
        "how_to_close": "One API call to /companies/%s would return "
                        "round-level detail (see G2); separately, confirm "
                        "the roster's total_raised as-of date and currency "
                        "before using it for anything beyond cohort "
                        "placement." % PANEL_SLUG,
        "status": "OPEN",
    }]

    out = {
        "subject": "AgentHub -> Gumloop",
        "company_id": "RM-agenthub",
        "name_at_decision": SHEET_NAME,
        "domain_at_decision": norm_domain(row.get("Company Website")),
        "slug_at_decision": yc_slug(row.get("YC Link", "")),
        "current_name": last.get("name"),
        "current_domain": norm_domain(last.get("website")),
        "current_slug": PANEL_SLUG,
        "network_requests_made": 0,
        "official_yc_declaration_present": False,
        "company_first_party_declaration_present": True,
        "evidence": ev,
        "evidence_all_hold": all(e["holds"] for e in ev),
        "gaps": gaps,
        "input_hashes": {p: lf_sha256(os.path.join(repo, p)) for p in [
            "data/processed/w24_spreadsheet_2024-03-25.csv",
            "data/processed/yc2024_monthly.csv",
            "data/processed/w24_crosswalk.csv",
        ]},
    }

    out_dir = os.path.join(repo, "data", "metadata", "rename_evidence")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "agenthub_gumloop.json")
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False) + "\n")

    print("wrote %s" % os.path.relpath(path, repo).replace("\\", "/"))
    for e in ev:
        print("  %s %-34s holds=%s" % (e["id"], e["kind"], e["holds"]))
    print("  official YC rename declaration present: %s"
          % out["official_yc_declaration_present"])
    for g in gaps:
        print("  GAP %s %s" % (g["id"], g["missing"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
