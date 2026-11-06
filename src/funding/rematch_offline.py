# -*- coding: utf-8 -*-
"""Offline re-match of the repair-affected companies. ZERO new API calls.

WHAT THIS ANSWERS, AS TWO SEPARATE NUMBERS THAT MUST NEVER BE MERGED

    (A) ENTITY MATCHES RECOVERED
        How many companies now resolve to a source record that did not resolve
        before. This is an identity result. It says nothing about funding.

    (B) NEW IN-WINDOW FUNDING EVIDENCE
        How many companies gained at least one dated funding event inside
        2024-04-04 (exclusive) .. 2026-04-04 (inclusive).

    (A) can be greater than (B) and usually will be, because resolving an
    identity only tells you which record to read - the record still has to be
    in the local cache and still has to contain a dated round. Reporting one
    number for both would claim funding evidence we do not have.

WHY THIS CAN RUN WITHOUT SPENDING QUOTA
    The earlier benchmark cached every response under
    data/interim/funding_source_benchmark/raw_recentfunding/ (gitignored). This
    script only reads those files. It never imports a network module, and a
    test asserts that.

RESOLUTION METHODS, both exact
    ROSTER_W24_NAME
        Exact normalised-name match against the cached accelerator roster,
        restricted to cohort "YC W24". The roster carries no website, so a
        domain check is impossible here; the cohort restriction is what stands
        in for it, and it is a strong one - a same-name company in another
        cohort cannot collide. Recorded as such, not presented as a domain
        match. Requires exactly one roster hit.
    CACHED_SEARCH_DOMAIN
        Candidates from the cached `/companies?q=` responses for this company's
        query names, keeping only those whose website is one of OUR domains.
        Requires exactly one distinct slug across all of them.

REFUSALS
    * the two methods resolving to different slugs -> refused, AMBIGUOUS;
    * a slug already matched to a different cohort company in the original
      benchmark -> refused, never stolen;
    * more than one candidate surviving -> refused, never "best match".
    No fuzzy matching anywhere. No amount is written: Preqin amount semantics
    are unconfirmed and RecentFunding amounts are only read, never inferred.

IDENTITY CAVEAT: acquired companies and personal domains
    A matched domain is only as trustworthy as what it actually identifies.
    `arcane` recovers via CACHED_SEARCH_DOMAIN on `rohanmehta.com` - but our
    own outcome panel (`w24_raw_outcomes_24m.csv`) already records `arcane` as
    `acquired_by_cutoff=YES`, with the panel's own `website` field switching
    from `arcanelabs.ai` to the co-founder's personal site the month AFTER the
    acquisition was first observed. That domain is a placeholder left behind
    by a defunct company, not continuing corporate identity, so it is weaker
    evidence than an unreviewed "domain is ours" match implies, and if the
    detail-cache gap for this slug is ever closed, any round found there must
    be checked against the acquisition before being read as follow-on funding
    to a surviving independent company. This script cross-checks every
    target's `acquired_by_cutoff` against the panel and records the caveat on
    the row and as its own gap, rather than leaving it to be remembered only
    in prose.

READS (read-only)
    data/interim/identifier_repair/company_identifiers_repaired.csv
    data/interim/identifier_repair/identifier_repair_before_after.csv
    data/interim/funding_source_benchmark/recentfunding_company_matches.csv
    data/interim/funding_source_benchmark/raw_recentfunding/*.json  (cache)
    data/processed/w24_raw_outcomes_24m.csv  (acquired_by_cutoff cross-check only)

WRITES (new files only)
    data/interim/rematch_offline/rematch_entity_resolution.csv
    data/interim/rematch_offline/rematch_candidate_events.csv
    data/interim/rematch_offline/rematch_gaps.csv
    data/interim/rematch_offline/rematch_manifest.json

NEVER WRITES
    results/verified/funding_y_v1/**   the frozen Funding Y v1
    data/processed/**
    Nothing here changes a Funding Y label. Every output is a CANDIDATE.
"""

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain, norm_name  # noqa: E402

WINDOW_START = "2024-04-04"   # exclusive
WINDOW_END = "2026-04-04"     # inclusive
W24_COHORT = "YC W24"
OUT_DIR = os.path.join("data", "interim", "rematch_offline")
CACHE_DEFAULT = os.path.join("data", "interim", "funding_source_benchmark",
                             "raw_recentfunding")

RES_COLS = ["company_id", "name_at_decision", "old_match_status", "new_match_status",
            "resolution_method", "matched_slug", "matched_name", "matched_website",
            "evidence", "detail_cache_present", "events_in_window",
            "entity_recovered", "funding_evidence_added", "acquired_by_cutoff",
            "identity_caveat", "note"]

EV_COLS = ["company_id", "matched_slug", "event_date", "window_class", "round_type",
           "amount_usd_as_reported", "investors", "evidence_url", "evidence_publisher"]

GAP_COLS = ["company_id", "gap_kind", "detail", "how_to_close"]


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def read_csv(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def day(ts):
    return str(ts or "")[:10]


def in_window(d):
    """Identical semantics to run_recentfunding_benchmark.in_window."""
    return bool(d) and len(d) == 10 and WINDOW_START < d <= WINDOW_END


def classify(d):
    if not d:
        return "NO_DATE"
    if in_window(d):
        return "IN_WINDOW"
    if d > WINDOW_END:
        return "POST_CUTOFF"
    return "PRE_DECISION"


def query_tag(name):
    """The cache key the original fetcher used: q_<norm_name with _ for space>."""
    return "q_" + norm_name(name).replace(" ", "_")


def load_roster(cache):
    """Cached accelerator roster, indexed by normalised name within YC W24."""
    by_name, total, cohorts = {}, 0, set()
    for f in sorted(glob.glob(os.path.join(cache, "rf_yc_*.json"))):
        for c in json.load(io.open(f, encoding="utf-8")).get("companies") or []:
            total += 1
            if c.get("cohort"):
                cohorts.add(c["cohort"])
            if c.get("cohort") == W24_COHORT:
                by_name.setdefault(norm_name(c.get("name")), []).append(c)
    return by_name, total, len(cohorts)


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--cache", default=CACHE_DEFAULT)
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    cache = os.path.join(repo, args.cache)
    out_dir = os.path.join(repo, OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    rep = {r["company_id"]: r for r in read_csv(os.path.join(
        repo, "data/interim/identifier_repair/company_identifiers_repaired.csv"))}
    ba = {r["company_id"]: r for r in read_csv(os.path.join(
        repo, "data/interim/identifier_repair/identifier_repair_before_after.csv"))}
    old = {r["company_id"]: r for r in read_csv(os.path.join(
        repo, "data/interim/funding_source_benchmark/recentfunding_company_matches.csv"))}
    outcomes = {r["entity_id"]: r for r in read_csv(os.path.join(
        repo, "data/processed/w24_raw_outcomes_24m.csv"))}

    if not os.path.isdir(cache):
        raise SystemExit(
            "cache directory not found: %s\nThis script is offline-only and "
            "cannot fetch. Restore the gitignored cache first." % cache)

    # The target set: companies the repair gave a NEW query candidate AND that
    # the original benchmark failed to resolve. Derived, not hand-listed.
    def S(x):
        return {y for y in (x or "").split("|") if y}

    expanded = {cid for cid, r in ba.items()
                if (S(r["query_domains_after"]) - S(r["query_domains_before"]))
                or (S(r["query_names_after"]) - S(r["query_names_before"]))}
    targets = sorted(cid for cid, m in old.items()
                     if m["match_status"] in ("AMBIGUOUS_MATCH", "COMPANY_NOT_FOUND")
                     and cid in expanded)

    # slugs the original run already attached to some other company: off limits
    taken = {m["matched_slug"]: cid for cid, m in old.items() if m.get("matched_slug")}

    roster, roster_total, roster_cohorts = load_roster(cache)
    print("cache: %d roster companies, %d cohorts, %d search files, %d detail files"
          % (roster_total, roster_cohorts,
             len(glob.glob(os.path.join(cache, "rf_q_*.json"))),
             len(glob.glob(os.path.join(cache, "rf_c_*.json")))))
    print("targets: %d companies (repair-expanded and previously unresolved)"
          % len(targets))

    res_rows, ev_rows, gap_rows = [], [], []
    for cid in targets:
        r, o = rep[cid], old[cid]
        names = [n for n in r["query_names"].split("|") if n]
        doms = {norm_domain(d) for d in r["query_domains"].split("|") if d}

        # --- method 1: the W24-restricted roster, by exact name --------------
        roster_hits = {}
        for n in names:
            for c in roster.get(norm_name(n), []):
                roster_hits[c["slug"]] = c

        # --- method 2: cached searches, kept only on domain agreement --------
        search_hits, uncached = {}, []
        for n in names:
            f = os.path.join(cache, "rf_%s.json" % query_tag(n))
            if not os.path.exists(f):
                uncached.append(n)
                continue
            for c in json.load(io.open(f, encoding="utf-8")).get("companies") or []:
                if norm_domain(c.get("website")) in doms:
                    search_hits[c["slug"]] = c

        status = o["match_status"]
        method = slug = mname = mweb = evidence = note = ""
        cand = sorted(set(roster_hits) | set(search_hits))
        if not cand:
            note = "no roster hit and no cached candidate whose domain is ours"
        elif len(cand) > 1:
            status = "AMBIGUOUS_MATCH"
            note = ("refused: %d distinct slugs resolved (%s); a single company "
                    "cannot be two source records" % (len(cand), ",".join(cand)))
        else:
            slug = cand[0]
            if slug in taken and taken[slug] != cid:
                status = "AMBIGUOUS_MATCH"
                note = ("refused: slug %s is already matched to %s by the original "
                        "benchmark and is not reassigned" % (slug, taken[slug]))
                slug = ""
            else:
                c = search_hits.get(slug) or roster_hits[slug]
                mname = c.get("name", "")
                mweb = norm_domain(c.get("website"))
                if slug in search_hits and slug in roster_hits:
                    method = "ROSTER_W24_NAME+CACHED_SEARCH_DOMAIN"
                    evidence = "cohort %s and website %s is ours" % (W24_COHORT, mweb)
                elif slug in search_hits:
                    method = "CACHED_SEARCH_DOMAIN"
                    evidence = "cached search candidate whose website %s is ours" % mweb
                else:
                    method = "ROSTER_W24_NAME"
                    evidence = ("exact name %r inside cohort %s; roster carries no "
                                "website so no domain check was possible"
                                % (mname, W24_COHORT))

        detail_present = False
        n_in = 0
        if slug:
            dpath = os.path.join(cache, "rf_c_%s.json" % slug)
            detail_present = os.path.exists(dpath)
            if detail_present:
                data = json.load(io.open(dpath, encoding="utf-8"))
                comp = data.get("company") or {}
                mweb = mweb or norm_domain(comp.get("website"))
                for rd in (data.get("rounds") or []):
                    dt = day(rd.get("announced_at"))
                    cls = classify(dt)
                    ev_rows.append({
                        "company_id": cid, "matched_slug": slug, "event_date": dt,
                        "window_class": cls, "round_type": rd.get("stage") or "",
                        "amount_usd_as_reported": rd.get("amount_usd") or "",
                        "investors": "|".join(
                            x.get("name", "") if isinstance(x, dict) else str(x)
                            for x in (rd.get("investors") or [])),
                        "evidence_url": rd.get("source_url") or "",
                        "evidence_publisher": rd.get("source_publisher") or "",
                    })
                    n_in += 1 if cls == "IN_WINDOW" else 0
                status = ("FUNDING_EVENT_FOUND" if n_in
                          else "COMPANY_FOUND_NO_EVENT_RETURNED")
            else:
                status = "ENTITY_MATCHED_NO_DETAIL_CACHED"
                note = ("identity resolved but rf_c_%s.json is not in the local "
                        "cache, so no dated round can be read offline" % slug)
                gap_rows.append({
                    "company_id": cid, "gap_kind": "DETAIL_NOT_CACHED",
                    "detail": "rf_c_%s.json absent; identity resolved via %s"
                              % (slug, method),
                    "how_to_close": "one API call to /companies/%s" % slug})

        for n in uncached:
            gap_rows.append({
                "company_id": cid, "gap_kind": "SEARCH_NOT_CACHED",
                "detail": "no cached search for the repaired query name %r "
                          "(expected rf_%s.json)" % (n, query_tag(n)),
                "how_to_close": "one API call to /companies?q=%s" % n})

        recovered = bool(slug) and o["match_status"] in ("AMBIGUOUS_MATCH",
                                                         "COMPANY_NOT_FOUND")

        # Identity caveat: a matched domain is only as trustworthy as what it
        # identifies. acquired_by_cutoff comes from our own outcome panel, not
        # from this script's own matching - it is a cross-check, not a guess.
        acquired = (outcomes.get(cid) or {}).get("acquired_by_cutoff", "UNKNOWN")
        caveat = ""
        decision_doms = {norm_domain(d) for d in [r["domain_at_decision"]] if d}
        if recovered and acquired == "YES" and mweb and mweb not in decision_doms:
            caveat = ("matched domain %r was not this company's decision-date "
                      "domain and the panel records acquired_by_cutoff=YES; "
                      "this may be a founder/acquirer placeholder, not "
                      "continuing corporate identity - verify before reading "
                      "any future round under %r as follow-on funding to a "
                      "surviving independent company" % (mweb, slug))
            gap_rows.append({
                "company_id": cid, "gap_kind": "ACQUIRED_IDENTITY_CAVEAT",
                "detail": caveat,
                "how_to_close": "manually confirm, before trusting any round "
                                "under slug %r, whether it predates the "
                                "acquisition or belongs to the acquirer/"
                                "founder instead of %r" % (slug, cid)})

        res_rows.append({
            "company_id": cid, "name_at_decision": r["name_at_decision"],
            "old_match_status": o["match_status"], "new_match_status": status,
            "resolution_method": method, "matched_slug": slug,
            "matched_name": mname, "matched_website": mweb, "evidence": evidence,
            "detail_cache_present": "YES" if detail_present else "NO",
            "events_in_window": n_in,
            "entity_recovered": "YES" if recovered else "NO",
            "funding_evidence_added": "YES" if n_in else "NO",
            "acquired_by_cutoff": acquired,
            "identity_caveat": caveat,
            "note": note,
        })

    def dump(name, cols, rows_):
        path = os.path.join(out_dir, name)
        with io.open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_)
        print("wrote %s (%d rows)"
              % (os.path.relpath(path, repo).replace("\\", "/"), len(rows_)))

    dump("rematch_entity_resolution.csv", RES_COLS, res_rows)
    dump("rematch_candidate_events.csv", EV_COLS, ev_rows)
    dump("rematch_gaps.csv", GAP_COLS, gap_rows)

    n_entity = sum(1 for r in res_rows if r["entity_recovered"] == "YES")
    n_funding = sum(1 for r in res_rows if r["funding_evidence_added"] == "YES")
    n_caveat = sum(1 for r in res_rows if r["identity_caveat"])
    manifest = {
        "new_api_calls": 0,
        "amounts_inferred": 0,
        "targets": len(targets),
        "A_entity_matches_recovered": n_entity,
        "B_companies_with_new_in_window_funding_evidence": n_funding,
        "numbers_are_separate": "A is an identity result and B is a funding "
                                "result. A >= B. They must not be reported as "
                                "one number.",
        "in_window_events_found": sum(1 for e in ev_rows
                                      if e["window_class"] == "IN_WINDOW"),
        "entity_matched_but_detail_not_cached":
            sum(1 for r in res_rows
                if r["new_match_status"] == "ENTITY_MATCHED_NO_DETAIL_CACHED"),
        "entity_matches_with_identity_caveat": n_caveat,
        "gaps": len(gap_rows),
        "frozen_funding_y_v1_untouched": {p: lf_sha256(os.path.join(repo, p)) for p in [
            "results/verified/funding_y_v1/company_labels.csv",
            "results/verified/funding_y_v1/manifest.json",
        ]},
        "cache": {
            "path": args.cache.replace("\\", "/"),
            "committed": False,
            "roster_companies": roster_total,
            "search_files": len(glob.glob(os.path.join(cache, "rf_q_*.json"))),
            "detail_files": len(glob.glob(os.path.join(cache, "rf_c_*.json"))),
        },
    }
    mpath = os.path.join(out_dir, "rematch_manifest.json")
    io.open(mpath, "w", encoding="utf-8").write(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print("wrote %s" % os.path.relpath(mpath, repo).replace("\\", "/"))

    print("")
    print("(A) entity matches recovered                   : %d of %d"
          % (n_entity, len(targets)))
    print("(B) companies with NEW in-window funding evidence: %d of %d"
          % (n_funding, len(targets)))
    print("    in-window events found                     : %d"
          % manifest["in_window_events_found"])
    print("    entity matched but detail not cached       : %d"
          % manifest["entity_matched_but_detail_not_cached"])
    print("    entity matches with an identity caveat     : %d" % n_caveat)
    print("    gaps recorded                              : %d" % len(gap_rows))
    print("")
    for r in res_rows:
        if r["entity_recovered"] == "YES" or r["new_match_status"] != r["old_match_status"]:
            print("  %-14s %-18s -> %-32s %s"
                  % (r["company_id"], r["old_match_status"],
                     r["new_match_status"], r["resolution_method"] or r["note"][:40]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
