# -*- coding: utf-8 -*-
"""T002 — offline, single-company repair of the Trellis (RM-trellis) match.

SCOPE, DELIBERATELY NARROW
    T001 found that the funding identifier builder blanks `current_domain` for
    any company the crosswalk missed, and that this is very likely true for
    more than one company (38 AMBIGUOUS_MATCH + 27 COMPANY_NOT_FOUND = 65).
    This script does NOT fix the identifier builder and does NOT touch any of
    those other rows. It repairs exactly one company, RM-trellis, using the
    alias chain already verified in T001 from this repo's own committed data,
    and leaves every cohort-identity field (name_at_decision, current_name,
    domain_at_decision, current_domain, renamed) untouched. Only the
    *query-candidate* field (query_domains, which is a lookup helper, not an
    identity field) gains one verified alias.

ZERO API CALLS
    Everything here reads committed CSVs and coordination/results/T001.md.
    No network request is made. The one RecentFunding detail call already
    spent is the one documented in T001.md; it is not repeated.

WHAT THIS DOES
    1. Re-derives the trellis -> runtrellis.com -> trellis-ai identity chain
       from data/processed/yc2024_monthly.csv and asserts T001.md documents
       the same chain and the same single undated $500,000 YC-deal round.
    2. Adds runtrellis.com as a second query domain for RM-trellis only, in
       data/interim/funding_source_benchmark/company_identifiers.csv.
    3. Updates the RM-trellis row only in recentfunding_company_matches.csv:
       AMBIGUOUS_MATCH -> COMPANY_FOUND_NO_EVENT_RETURNED. No in-window event
       is added (the one round found has no announced_at date and is YC's
       standard batch deal, i.e. prior funding / X, not follow-on Y).
    4. Appends the one undated round to recentfunding_events_raw.csv with
       in_window=NO_DATE, matching how run_recentfunding_benchmark.py would
       have recorded a live detail response with no parseable date.
    5. Regenerates the three downstream benchmark outputs
       (funding_source_coverage.csv, funding_source_overlap.csv,
       funding_events_deduplicated.csv) by calling analyze_funding_benchmark
       in-process against the updated interim CSVs. No other input changes.
    6. Verifies: every other row of every touched CSV is byte-identical to
       before; the Lantern collision (lantern.dev vs lanternhq.com) is still
       refused; frozen Funding Y v1 is byte-identical to before; the union
       totals (53 companies / 67 events) are unchanged, since no event was
       added for Trellis.

Run: python src/funding/repair_trellis_match.py --repo .
"""

import csv
import argparse
import hashlib
import io
import os
import runpy
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "src"))

D = os.path.join(REPO, "data", "interim", "funding_source_benchmark")
IDENT = os.path.join(D, "company_identifiers.csv")
MATCHES = os.path.join(D, "recentfunding_company_matches.csv")
EVENTS = os.path.join(D, "recentfunding_events_raw.csv")
YC_MONTHLY = os.path.join(REPO, "data", "processed", "yc2024_monthly.csv")
T001 = os.path.join(REPO, "coordination", "results", "T001.md")
FROZEN_DIR = os.path.join(REPO, "results", "verified", "funding_y_v1")

COMPANY_ID = "RM-trellis"
VERIFIED_ALIAS_DOMAIN = "runtrellis.com"
VERIFIED_ALIAS_SLUG = "trellis-ai"


def read_csv(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, cols):
    with io.open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def hash_tree(dirpath):
    out = {}
    for name in sorted(os.listdir(dirpath)):
        p = os.path.join(dirpath, name)
        if os.path.isfile(p):
            out[name] = sha256_file(p)
    return out


def step(msg):
    print("== %s" % msg)


def fail(msg):
    print("FAIL: %s" % msg)
    sys.exit(1)


def verify_chain_from_panel():
    """Step 1: re-derive the alias chain from committed panel data only."""
    step("1. Verifying trellis -> runtrellis.com -> trellis-ai chain from yc2024_monthly.csv")
    rows = read_csv(YC_MONTHLY)
    trellis_rows = [r for r in rows if r["slug"] == "trellis"]
    trellis_ai_rows = [r for r in rows if r["slug"] == "trellis-ai"]
    if not trellis_rows:
        fail("no snapshot carries yc slug 'trellis' - chain cannot be verified")
    if not trellis_ai_rows:
        fail("no snapshot carries yc slug 'trellis-ai' - chain cannot be verified")
    websites_trellis = {r["website"].rstrip("/") for r in trellis_rows}
    websites_trellis_ai = {r["website"].rstrip("/") for r in trellis_ai_rows}
    if websites_trellis != {"https://runtrellis.com"}:
        fail("slug 'trellis' snapshots do not all publish runtrellis.com: %r" % websites_trellis)
    if websites_trellis_ai != {"https://runtrellis.com"}:
        fail("slug 'trellis-ai' snapshots do not all publish runtrellis.com: %r" % websites_trellis_ai)
    first_trellis = min(r["snapshot"] for r in trellis_rows)
    first_trellis_ai = min(r["snapshot"] for r in trellis_ai_rows)
    if not (first_trellis < first_trellis_ai):
        fail("slug 'trellis' does not precede slug 'trellis-ai' in time")
    print("   slug 'trellis' first seen %s, both publish runtrellis.com" % first_trellis)
    print("   slug 'trellis-ai' first seen %s, same website -> same entity" % first_trellis_ai)

    ident = read_csv(IDENT)
    rm = [r for r in ident if r["company_id"] == COMPANY_ID]
    if len(rm) != 1:
        fail("expected exactly one RM-trellis row in company_identifiers.csv, found %d" % len(rm))
    rm = rm[0]
    if rm["domain_at_decision"] != "usetrellis.co" or rm["name_at_decision"] != "Trellis":
        fail("RM-trellis decision-time identity does not match T001 evidence: %r" % rm)
    print("   RM-trellis at decision: %s / %s (matches T001 evidence)"
          % (rm["name_at_decision"], rm["domain_at_decision"]))
    historical = read_csv(os.path.join(REPO, "data", "processed", "w24_spreadsheet_2024-03-25.csv"))
    linked = [r for r in historical if r["Company Name"] == "Trellis"
              and r["YC Link"].rstrip("/") == "https://www.ycombinator.com/companies/trellis"]
    if len(linked) != 1 or linked[0]["Company Website"].rstrip("/") != "https://usetrellis.co":
        fail("historical spreadsheet does not establish the trellis slug/domain bridge")
    return rm


def verify_t001_documents_chain_and_round():
    """Step 1b: the API-derived facts come only from the committed T001.md
    text, not from a re-request. Assert the facts this script relies on are
    actually present in that committed file, so they are not invented here."""
    step("1b. Verifying coordination/results/T001.md documents the same chain and round")
    text = io.open(T001, encoding="utf-8").read()
    required = [
        "runtrellis.com", "trellis-ai", "COMPANY_FOUND_NO_EVENT_RETURNED",
        "500000", "ycombinator.com/deal", "RM-trellis",
        "HTTP 200",
    ]
    missing = [s for s in required if s not in text]
    if missing:
        fail("T001.md does not document expected evidence: %r" % missing)
    print("   T001.md confirms: single undated $500,000 YC-deal round, "
          "recommended status COMPANY_FOUND_NO_EVENT_RETURNED")


def patch_identifiers():
    step("2. Adding verified alias domain to RM-trellis query candidates only")
    rows = read_csv(IDENT)
    cols = list(rows[0].keys())
    changed = 0
    for r in rows:
        if r["company_id"] != COMPANY_ID:
            continue
        domains = [d for d in r["query_domains"].split("|") if d]
        if VERIFIED_ALIAS_DOMAIN not in domains:
            domains.append(VERIFIED_ALIAS_DOMAIN)
            r["query_domains"] = "|".join(domains)
            changed += 1
        # cohort-identity fields are explicitly left untouched:
        # name_at_decision, current_name, former_names, domain_at_decision,
        # current_domain, renamed, in_yc_directory, sample_group
    write_csv(IDENT, rows, cols)
    print("   query_domains for RM-trellis -> %s (%d field changed)"
          % (next(r["query_domains"] for r in rows if r["company_id"] == COMPANY_ID), changed))


def patch_matches():
    step("3. Updating RM-trellis match status only (AMBIGUOUS_MATCH -> COMPANY_FOUND_NO_EVENT_RETURNED)")
    rows = read_csv(MATCHES)
    cols = list(rows[0].keys())
    if sum(r["company_id"] == COMPANY_ID for r in rows) != 1:
        fail("expected exactly one RM-trellis match row")
    for r in rows:
        if r["company_id"] != COMPANY_ID:
            continue
        if r["match_status"] not in ("AMBIGUOUS_MATCH", "COMPANY_FOUND_NO_EVENT_RETURNED"):
            fail("refusing unexpected RM-trellis status %r" % r["match_status"])
        r["match_status"] = "COMPANY_FOUND_NO_EVENT_RETURNED"
        r["matched_slug"] = VERIFIED_ALIAS_SLUG
        r["matched_website"] = "https://" + VERIFIED_ALIAS_DOMAIN
        r["match_note"] = ("identity verified via yc2024_monthly.csv panel "
                            "(slug trellis -> trellis-ai, runtrellis.com); "
                            "T001 one-call evidence: 1 round, no announced_at, "
                            "$500000 ycombinator.com/deal (YC batch deal, not "
                            "follow-on; excluded from window). See T001.md.")
        r["events_in_window"] = "0"
        r["first_event_date"] = ""
        r["cumulative_usd_in_window"] = ""
        r["events_with_amount"] = "0"
        r["events_with_evidence_url"] = "0"
        r["events_post_cutoff"] = "0"
        r["events_pre_decision_or_undated"] = "1"
    write_csv(MATCHES, rows, cols)
    print("   RM-trellis -> COMPANY_FOUND_NO_EVENT_RETURNED, 0 in-window events, "
          "1 undated/pre-decision round recorded")


def append_event_row():
    step("4. Recording the one undated round in recentfunding_events_raw.csv (NO_DATE, excluded from window)")
    rows = read_csv(EVENTS)
    cols = list(rows[0].keys())
    if any(r["company_id"] == COMPANY_ID for r in rows):
        print("   RM-trellis already has an event row; leaving as-is (no duplicate added)")
        return
    rows.append({
        "company_id": COMPANY_ID,
        "source": "recent_funding",
        "matched_slug": VERIFIED_ALIAS_SLUG,
        "matched_name": "Trellis AI",
        "event_date": "",
        "amount_usd": "500000.00",
        "valuation_usd": "",
        "round_type": "unknown",
        "investors": "",
        "evidence_url": "https://www.ycombinator.com/deal",
        "evidence_publisher": "",
        "in_window": "NO_DATE",
    })
    write_csv(EVENTS, rows, cols)
    print("   appended 1 row for RM-trellis, in_window=NO_DATE (never counted as an in-window event)")


def regenerate_downstream():
    step("5. Regenerating funding_source_coverage.csv / funding_source_overlap.csv / "
         "funding_events_deduplicated.csv offline (no API calls; local CSVs only)")
    sys.argv = ["analyze_funding_benchmark.py", "--repo", REPO]
    runpy.run_path(os.path.join(REPO, "src", "funding", "analyze_funding_benchmark.py"),
                    run_name="__main__")


def verify_only_trellis_changed(before, after, label, key="company_id"):
    by_id_before = {r[key]: r for r in before}
    by_id_after = {r[key]: r for r in after}
    if len(by_id_before) != len(before) or len(by_id_after) != len(after):
        fail("%s: duplicate company identifiers" % label)
    if set(by_id_before) != set(by_id_after):
        fail("%s: company membership changed" % label)
    changed = [cid for cid in by_id_before
               if by_id_before[cid] != by_id_after.get(cid)]
    if changed not in ([], [COMPANY_ID]):
        fail("%s: expected only %s to change, but changed rows = %r"
             % (label, COMPANY_ID, changed))
    print("   %s: changed=%r; all other company row values identical" % (label, changed))


def verify_lantern_collision_still_refused(after_ident, after_matches):
    step("6a. Collision regression: Lantern (lantern.dev vs lanternhq.com) must remain refused")
    ident_row = next(r for r in after_ident if r["company_id"] == "lantern-2")
    match_row = next(r for r in after_matches if r["company_id"] == "lantern-2")
    if ident_row["query_domains"] != "lantern.dev":
        fail("lantern-2 query_domains changed unexpectedly: %r" % ident_row["query_domains"])
    if match_row["match_status"] != "AMBIGUOUS_MATCH":
        fail("lantern-2 collision regressed: match_status is now %r, expected AMBIGUOUS_MATCH"
             % match_row["match_status"])
    if "lanternhq.com is not lantern.dev" not in match_row["match_note"]:
        fail("lantern-2 refusal note changed unexpectedly: %r" % match_row["match_note"])
    print("   lantern-2 still AMBIGUOUS_MATCH, domain collision still refused: %r"
          % match_row["match_note"])


def verify_frozen_v1_untouched(before_hashes):
    step("6b. Verifying frozen Funding Y v1 is byte-for-byte unchanged")
    after_hashes = hash_tree(FROZEN_DIR)
    if before_hashes != after_hashes:
        fail("frozen funding_y_v1 changed: before=%r after=%r" % (before_hashes, after_hashes))
    print("   results/verified/funding_y_v1/* unchanged: %r" % before_hashes)


def verify_totals(expected_positive=53, expected_events=67):
    step("6c. Validating cohort union totals (53 confirmed-positive / 67 dedup events) unless evidence says otherwise")
    overlap = read_csv(os.path.join(D, "funding_source_overlap.csv"))
    dedup = read_csv(os.path.join(D, "funding_events_deduplicated.csv"))
    either = sum(1 for r in overlap if r["either_source_found"] == "YES")
    n_events = len(dedup)
    print("   either-source-found companies: %d (expected %d)" % (either, expected_positive))
    print("   deduplicated events: %d (expected %d)" % (n_events, expected_events))
    if either != expected_positive or n_events != expected_events:
        fail("union totals changed unexpectedly: %d companies / %d events" % (either, n_events))
    else:
        print("   totals unchanged, as expected: Trellis gained no in-window event.")
    return either, n_events


def main():
    global REPO, D, IDENT, MATCHES, EVENTS, YC_MONTHLY, T001, FROZEN_DIR
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=REPO)
    args = p.parse_args()
    REPO = os.path.abspath(args.repo)
    D = os.path.join(REPO, "data", "interim", "funding_source_benchmark")
    IDENT = os.path.join(D, "company_identifiers.csv")
    MATCHES = os.path.join(D, "recentfunding_company_matches.csv")
    EVENTS = os.path.join(D, "recentfunding_events_raw.csv")
    YC_MONTHLY = os.path.join(REPO, "data", "processed", "yc2024_monthly.csv")
    T001 = os.path.join(REPO, "coordination", "results", "T001.md")
    FROZEN_DIR = os.path.join(REPO, "results", "verified", "funding_y_v1")
    if not os.path.isdir(FROZEN_DIR):
        fail("frozen funding_y_v1 directory missing: %s" % FROZEN_DIR)
    before_frozen_hashes = hash_tree(FROZEN_DIR)

    ident_before = read_csv(IDENT)
    matches_before = read_csv(MATCHES)
    protected_paths = [EVENTS, os.path.join(D, "funding_source_overlap.csv"),
                       os.path.join(D, "funding_events_deduplicated.csv")]
    protected_before = {path: read_csv(path) for path in protected_paths}
    output_paths = [os.path.join(D, name) for name in
                    ("funding_source_coverage.csv", "funding_source_overlap.csv",
                     "funding_events_deduplicated.csv")]
    output_bytes = {path: open(path, "rb").read() for path in output_paths}

    verify_chain_from_panel()
    verify_t001_documents_chain_and_round()

    patch_identifiers()
    patch_matches()
    append_event_row()
    regenerate_downstream()
    # Preserve each output's existing UTF-8 BOM convention; restore exact bytes
    # for semantically unchanged outputs (e.g. the deduplicated event table).
    for path, old_bytes in output_bytes.items():
        new_bytes = open(path, "rb").read()
        if new_bytes.decode("utf-8-sig") == old_bytes.decode("utf-8-sig"):
            with open(path, "wb") as fh:
                fh.write(old_bytes)
        elif not old_bytes.startswith(b"\xef\xbb\xbf") and new_bytes.startswith(b"\xef\xbb\xbf"):
            with open(path, "wb") as fh:
                fh.write(new_bytes[3:])
    for path, old_rows in protected_before.items():
        old_other = [r for r in old_rows if r["company_id"] != COMPANY_ID]
        new_other = [r for r in read_csv(path) if r["company_id"] != COMPANY_ID]
        if old_other != new_other:
            fail("non-Trellis rows changed in %s" % path)

    ident_after = read_csv(IDENT)
    matches_after = read_csv(MATCHES)

    verify_only_trellis_changed(ident_before, ident_after, "company_identifiers.csv")
    verify_only_trellis_changed(matches_before, matches_after, "recentfunding_company_matches.csv")
    verify_lantern_collision_still_refused(ident_after, matches_after)
    verify_frozen_v1_untouched(before_frozen_hashes)
    verify_totals()

    step("DONE. RM-trellis repaired in isolation. API calls made by this script: 0.")


if __name__ == "__main__":
    main()
