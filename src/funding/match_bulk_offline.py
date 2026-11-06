# -*- coding: utf-8 -*-
"""Domain-only match of the 240 cohort companies against the local source pool.

ZERO API CALLS. Reads only the gitignored response cache.

WHY THIS REPLACES NAME-SEARCH MATCHING
    `/companies?accelerator=yc&limit=2000` returns `website` for every company,
    so three cached pages give the whole YC universe with domains. That makes
    DOMAIN matching possible for the entire cohort offline, instead of sending
    one name search per company and trying to disambiguate the results. Name
    search was the source of all 37 AMBIGUOUS_MATCH verdicts.

MATCHING RULE
    Domain only. A company matches a source record when one of its repaired
    query domains equals that record's website domain. A name is used ONLY to
    break a tie between two domain hits, never to create a match, and the
    accepted record is still put through `domain_contradicts`.

    One case needs its own status rather than a silent drop: a source record
    with NO website cannot be domain-verified either way. `tesseral` is such a
    record - the original benchmark matched it by name and found one in-window
    round, and discarding it for want of a website would lose real evidence.
    Those are reported `MATCHED_NAME_UNVERIFIED` and counted separately.

WHAT "NO IN-WINDOW ROUND" MEANS HERE
    That this source holds no dated round for the company inside
    2024-04-04 (exclusive) .. 2026-04-04 (inclusive). It does NOT mean the
    company did not raise. RecentFunding is announcement-driven, and the
    measured ceiling is in the log: Trieve, independently verified as raising
    $3.5M in-window, returns HTTP 404 from this source.

READS
    data/interim/identifier_repair/company_identifiers_repaired.csv
    data/interim/funding_source_benchmark/recentfunding_company_matches.csv
    data/interim/funding_source_benchmark/raw_recentfunding/
        rf_co_yc_*.json   bulk /companies?accelerator=yc pages (carry website)
        rf_c_*.json       cached /companies/{slug} details (carry rounds)
        rf_q_*.json       cached /companies?q= searches (carry website)

WRITES
    data/interim/bulk_match/bulk_match_companies.csv
    data/interim/bulk_match/bulk_match_events.csv
    data/interim/bulk_match/bulk_match_manifest.json

NEVER WRITES results/verified/** or data/processed/**. Creates no Y label.
"""

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entity_resolution.normalize import norm_domain, norm_name  # noqa: E402
from repair_company_identifiers import domain_contradicts  # noqa: E402

WIN_START, WIN_END = "2024-04-04", "2026-04-04"
CACHE = os.path.join("data", "interim", "funding_source_benchmark", "raw_recentfunding")
OUT_DIR = os.path.join("data", "interim", "bulk_match")

CO_COLS = ["company_id", "name_at_decision", "old_match_status", "new_status",
           "matched_slug", "matched_name", "matched_website", "match_basis",
           "events_in_window", "cumulative_usd_in_window", "latest_round_date",
           "detail_cached", "note"]
EV_COLS = ["company_id", "matched_slug", "event_date", "round_type",
           "amount_usd", "investors", "evidence_url", "evidence_publisher"]


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def rows(p):
    return list(csv.DictReader(io.open(p, encoding="utf-8-sig")))


def in_window(d):
    return bool(d) and len(d) == 10 and WIN_START < d <= WIN_END


def build_pool(cache):
    """Every source company record we hold locally, keyed by slug."""
    pool, src = {}, {}

    def add(c, tag):
        if not c or not c.get("slug"):
            return
        s = c["slug"]
        if s not in pool or (not pool[s].get("website") and c.get("website")):
            pool[s] = c
        src.setdefault(s, tag)

    for f in sorted(glob.glob(os.path.join(cache, "rf_co_yc_*.json"))):
        for c in json.load(io.open(f, encoding="utf-8")).get("companies") or []:
            add(c, "bulk")
    for f in sorted(glob.glob(os.path.join(cache, "rf_c_*.json"))):
        d = json.load(io.open(f, encoding="utf-8"))
        add(d.get("company"), "detail")
    for f in sorted(glob.glob(os.path.join(cache, "rf_q_*.json"))):
        for c in json.load(io.open(f, encoding="utf-8")).get("companies") or []:
            add(c, "search")
    return pool, src


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    cache = os.path.join(repo, CACHE)
    out_dir = os.path.join(repo, OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    if not os.path.isdir(cache):
        raise SystemExit("cache not found: %s (offline-only; restore it first)" % cache)

    rep = rows(os.path.join(repo, "data/interim/identifier_repair/"
                                  "company_identifiers_repaired.csv"))
    old = {r["company_id"]: r for r in rows(os.path.join(
        repo, "data/interim/funding_source_benchmark/recentfunding_company_matches.csv"))}

    pool, psrc = build_pool(cache)
    by_dom, no_site = {}, {}
    for s, c in pool.items():
        d = norm_domain(c.get("website"))
        if d:
            by_dom.setdefault(d, []).append(c)
        else:
            no_site[s] = c
    print("pooled source companies: %d  %s" % (len(pool), dict(Counter(psrc.values()))))
    print("distinct domains: %d | records with no website: %d"
          % (len(by_dom), len(no_site)))

    co_rows, ev_rows = [], []
    for r in rep:
        cid = r["company_id"]
        o = old.get(cid, {})
        doms = [norm_domain(d) for d in r["query_domains"].split("|") if d]
        names = {norm_name(n) for n in r["query_names"].split("|") if n}

        hits = {}
        for d in doms:
            for c in by_dom.get(d, []):
                hits[c["slug"]] = c
        basis, note, status = "", "", ""

        if len(hits) > 1:
            tie = {s: c for s, c in hits.items() if norm_name(c.get("name")) in names}
            if len(tie) != 1:
                co_rows.append({
                    "company_id": cid, "name_at_decision": r["name_at_decision"],
                    "old_match_status": o.get("match_status", ""),
                    "new_status": "REFUSED_AMBIGUOUS", "match_basis": "DOMAIN",
                    "note": "%d source records share our domains (%s); refused"
                            % (len(hits), ",".join(sorted(hits))),
                    "events_in_window": 0, "detail_cached": "",
                })
                continue
            hits, basis = tie, "DOMAIN+NAME_TIEBREAK"
        elif hits:
            basis = "DOMAIN"

        if not hits:
            # the source may hold the company with no website recorded; the
            # original benchmark's name match is then the only evidence and is
            # kept as explicitly UNVERIFIED rather than discarded
            slug = (o.get("matched_slug") or "").strip()
            if slug and slug in no_site:
                hits, basis = {slug: no_site[slug]}, "NAME_ONLY_NO_SITE_IN_SOURCE"
                note = ("source record has no website, so the domain rule can "
                        "neither confirm nor refuse it")
            else:
                co_rows.append({
                    "company_id": cid, "name_at_decision": r["name_at_decision"],
                    "old_match_status": o.get("match_status", ""),
                    "new_status": "UNMATCHED", "match_basis": "",
                    "note": "no source record publishes any of our domains (%s)"
                            % ",".join(doms),
                    "events_in_window": 0, "detail_cached": "",
                })
                continue

        c = list(hits.values())[0]
        site = norm_domain(c.get("website"))
        if site and domain_contradicts(doms, site):
            co_rows.append({
                "company_id": cid, "name_at_decision": r["name_at_decision"],
                "old_match_status": o.get("match_status", ""),
                "new_status": "REFUSED_DOMAIN", "match_basis": basis,
                "note": "%s publishes %s, which is not ours" % (c["slug"], site),
                "events_in_window": 0, "detail_cached": "",
            })
            continue

        dpath = os.path.join(cache, "rf_c_%s.json" % c["slug"])
        cached = os.path.exists(dpath)
        inw, total = [], 0.0
        if cached:
            d = json.load(io.open(dpath, encoding="utf-8"))
            for x in d.get("rounds") or []:
                dt = (x.get("announced_at") or "")[:10]
                if not in_window(dt):
                    continue
                inw.append(x)
                if x.get("amount_usd"):
                    total += float(x["amount_usd"])
                ev_rows.append({
                    "company_id": cid, "matched_slug": c["slug"], "event_date": dt,
                    "round_type": x.get("stage") or "",
                    "amount_usd": x.get("amount_usd") or "",
                    "investors": "|".join(
                        y.get("name", "") if isinstance(y, dict) else str(y)
                        for y in (x.get("investors") or [])),
                    "evidence_url": x.get("source_url") or "",
                    "evidence_publisher": x.get("source_publisher") or "",
                })
        latest = (c.get("announced_at") or "")[:10]
        if inw:
            status = ("FUNDING_EVENT_FOUND" if basis != "NAME_ONLY_NO_SITE_IN_SOURCE"
                      else "MATCHED_NAME_UNVERIFIED")
        elif cached:
            status = "COMPANY_FOUND_NO_IN_WINDOW_ROUND"
        elif latest and latest > WIN_START:
            status = "DETAIL_NOT_CACHED"
            note = note or "latest round %s is in window but rounds are unenumerated" % latest
        else:
            status = "COMPANY_FOUND_NO_DATED_ROUND"
        co_rows.append({
            "company_id": cid, "name_at_decision": r["name_at_decision"],
            "old_match_status": o.get("match_status", ""), "new_status": status,
            "matched_slug": c["slug"], "matched_name": c.get("name", ""),
            "matched_website": site, "match_basis": basis,
            "events_in_window": len(inw),
            "cumulative_usd_in_window": ("%.0f" % total) if total else "",
            "latest_round_date": latest, "detail_cached": "YES" if cached else "NO",
            "note": note,
        })

    def dump(name, cols, rs):
        p = os.path.join(out_dir, name)
        with io.open(p, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rs)
        print("wrote %s (%d rows)" % (os.path.relpath(p, repo).replace("\\", "/"), len(rs)))

    dump("bulk_match_companies.csv", CO_COLS, co_rows)
    dump("bulk_match_events.csv", EV_COLS, ev_rows)

    st = Counter(r["new_status"] for r in co_rows)
    pos = [r for r in co_rows if r["events_in_window"]]
    manifest = {
        "api_calls_made_by_this_script": 0,
        "window": {"start_exclusive": WIN_START, "end_inclusive": WIN_END},
        "cohort": len(co_rows),
        "companies_with_in_window_evidence": len(pos),
        "in_window_events": len(ev_rows),
        "status_counts": dict(st),
        "domain_verified_positives": sum(
            1 for r in pos if r["match_basis"] != "NAME_ONLY_NO_SITE_IN_SOURCE"),
        "name_only_unverified_positives": sum(
            1 for r in pos if r["match_basis"] == "NAME_ONLY_NO_SITE_IN_SOURCE"),
        "absence_is_not_evidence":
            "COMPANY_FOUND_NO_* means this source holds no dated in-window round, "
            "NOT that the company did not raise. Measured ceiling: Trieve, "
            "independently verified at $3.5M in-window, returns HTTP 404 here.",
        "frozen_funding_y_v1_untouched": {p: lf_sha256(os.path.join(repo, p)) for p in [
            "results/verified/funding_y_v1/company_labels.csv",
            "results/verified/funding_y_v1/manifest.json",
        ]},
    }
    mp = os.path.join(out_dir, "bulk_match_manifest.json")
    io.open(mp, "w", encoding="utf-8").write(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print("wrote %s" % os.path.relpath(mp, repo).replace("\\", "/"))

    print("")
    for k, v in st.most_common():
        print("   %-34s %3d" % (k, v))
    print("")
    print("companies with in-window evidence : %d  (%d domain-verified, %d name-only)"
          % (len(pos), manifest["domain_verified_positives"],
             manifest["name_only_unverified_positives"]))
    print("in-window events                  : %d" % len(ev_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
