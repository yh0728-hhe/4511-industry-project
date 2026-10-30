# -*- coding: utf-8 -*-
"""Compare the funding sources, measure overlap, and deduplicate events.

WHAT IT COMPARES
    SEC Form D   the existing baseline, read from the committed outcome
                 dataset (funding fields only; that file is never modified)
    Recent Funding  this benchmark's run

WHY THE STATUSES ARE CARRIED THROUGH
    "no event returned" is not "no funding". Coverage is therefore reported as
    three separate quantities - company resolved, event found, and neither -
    rather than one number that silently merges them.

DEDUPLICATION
    Two events are the same round when they belong to the same company and
    their dates are within a tolerance window, or their disclosed amounts
    agree within 5%. Sources announce the same round on different days (an
    SEC filing follows the press announcement), so exact-date matching alone
    would double count. Provenance is preserved: every merged event keeps the
    list of sources that reported it.

OUTPUTS (data/interim/funding_source_benchmark/)
    funding_source_coverage.csv     per-source coverage
    funding_source_overlap.csv      per-company, which sources found funding
    funding_events_deduplicated.csv merged events with provenance
"""

import argparse
import csv
import io
import os
from collections import defaultdict

WINDOW_START = "2024-04-04"
WINDOW_END = "2026-04-04"
DATE_TOLERANCE_DAYS = 75
AMOUNT_MERGE_MAX_DAYS = 120   # amount agreement alone must still be near in time


def to_ord(d):
    try:
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
        return y * 372 + m * 31 + dd
    except Exception:
        return None


def amount(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v > 0 else None
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--repo", default=".")
    args = p.parse_args()
    d = os.path.join(args.repo, "data", "interim", "funding_source_benchmark")

    rf_m = list(csv.DictReader(io.open(os.path.join(d, "recentfunding_company_matches.csv"),
                                       encoding="utf-8-sig")))
    rf_e = list(csv.DictReader(io.open(os.path.join(d, "recentfunding_events_raw.csv"),
                                       encoding="utf-8-sig")))
    y = list(csv.DictReader(io.open(os.path.join(args.repo, "data", "processed",
                                                 "w24_raw_outcomes_24m.csv"),
                                    encoding="utf-8-sig")))
    N = len(y)

    # ---- Form D baseline, read only ------------------------------------
    fd = {}
    for r in y:
        fd[r["entity_id"]] = {
            "found": r["followon_funding_evidence"] == "FOUND",
            "date": r["funding_first_date"],
            "amount": r["funding_amount_sold"],
            "caveat": r["funding_match_caveat"],
            "count": r["funding_filings_count"],
        }

    rf = {r["company_id"]: r for r in rf_m}
    events_rf = defaultdict(list)
    for e in rf_e:
        if e["in_window"] == "IN_WINDOW":
            events_rf[e["company_id"]].append(e)

    # ---- coverage -------------------------------------------------------
    def pct(n):
        return "%.1f%%" % (100.0 * n / N)

    rows = []
    fd_found = sum(1 for v in fd.values() if v["found"])
    fd_clean = sum(1 for v in fd.values() if v["found"] and not v["caveat"])
    rows.append({
        "source": "SEC Form D",
        "access": "free, bulk download",
        "companies_resolved": "",
        "companies_resolved_pct": "",
        "funding_positive_companies": fd_found,
        "funding_positive_pct": pct(fd_found),
        "funding_positive_without_caveat": fd_clean,
        "events_in_window": sum(int(v["count"] or 0) for v in fd.values() if v["found"]),
        "events_with_date": sum(1 for v in fd.values() if v["found"] and v["date"]),
        "events_with_amount": sum(1 for v in fd.values() if v["found"] and v["amount"]),
        "events_with_evidence_url": 0,
        "note": "filing-based; no announcement URL; US exempt offerings only",
    })

    resolved = sum(1 for r in rf_m if r["match_status"] in
                   ("FUNDING_EVENT_FOUND", "COMPANY_FOUND_NO_EVENT_RETURNED"))
    rf_found = sum(1 for r in rf_m if r["match_status"] == "FUNDING_EVENT_FOUND")
    allev = [e for v in events_rf.values() for e in v]
    rows.append({
        "source": "Recent Funding",
        "access": "free API key by email; 24h trial plan on this key",
        "companies_resolved": resolved,
        "companies_resolved_pct": pct(resolved),
        "funding_positive_companies": rf_found,
        "funding_positive_pct": pct(rf_found),
        "funding_positive_without_caveat": rf_found,
        "events_in_window": len(allev),
        "events_with_date": sum(1 for e in allev if e["event_date"]),
        "events_with_amount": sum(1 for e in allev if amount(e["amount_usd"])),
        "events_with_evidence_url": sum(1 for e in allev if e["evidence_url"]),
        "note": "news/announcement based; every event carries a source URL",
    })

    with io.open(os.path.join(d, "funding_source_coverage.csv"), "w",
                 newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    # ---- per-company overlap -------------------------------------------
    ov = []
    for r in y:
        cid = r["entity_id"]
        f = fd[cid]
        m = rf.get(cid, {})
        rf_pos = m.get("match_status") == "FUNDING_EVENT_FOUND"
        both = f["found"] and rf_pos
        ov.append({
            "company_id": cid,
            "name_at_decision": r["name_at_decision"],
            "form_d": "FOUND" if f["found"] else "NO_EVENT",
            "form_d_caveat": f["caveat"][:60],
            "recent_funding_status": m.get("match_status", "NOT_RUN"),
            "recent_funding_events": m.get("events_in_window", ""),
            "either_source_found": "YES" if (f["found"] or rf_pos) else "NO",
            "both_sources_found": "YES" if both else "NO",
            "only_form_d": "YES" if (f["found"] and not rf_pos) else "",
            "only_recent_funding": "YES" if (rf_pos and not f["found"]) else "",
        })
    with io.open(os.path.join(d, "funding_source_overlap.csv"), "w",
                 newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(ov[0].keys()))
        w.writeheader(); w.writerows(ov)

    # ---- deduplicate events --------------------------------------------
    merged = []
    for cid, evs in events_rf.items():
        f = fd.get(cid, {})
        pool = [dict(e, _src="recent_funding") for e in evs]
        if f.get("found") and f.get("date") and WINDOW_START < f["date"] <= WINDOW_END:
            pool.append({"company_id": cid, "event_date": f["date"],
                         "amount_usd": f.get("amount") or "", "round_type": "",
                         "investors": "", "evidence_url": "",
                         "evidence_publisher": "SEC", "_src": "sec_form_d"})
        used = [False] * len(pool)
        for i, a in enumerate(pool):
            if used[i]:
                continue
            group = [a]
            used[i] = True
            for j in range(i + 1, len(pool)):
                if used[j]:
                    continue
                b = pool[j]
                oa, ob = to_ord(a["event_date"]), to_ord(b["event_date"])
                close_date = oa is not None and ob is not None and abs(oa - ob) <= DATE_TOLERANCE_DAYS
                aa, ab = amount(a["amount_usd"]), amount(b["amount_usd"])
                gap = abs(oa - ob) if (oa is not None and ob is not None) else None
                # A matching amount is only evidence of the same round when the
                # two reports are also close in time. Merging on amount alone
                # joined a 2024-06 filing to a 2025-12 announcement for Guide
                # Labs and two reports nine months apart for Tamarind Bio -
                # far more likely to be separate rounds of similar size than
                # one round reported a year later.
                close_amt = (aa and ab and abs(aa - ab) <= 0.05 * max(aa, ab)
                             and gap is not None and gap <= AMOUNT_MERGE_MAX_DAYS)
                if close_date or close_amt:
                    group.append(b)
                    used[j] = True
            srcs = sorted({g["_src"] for g in group})
            dates = sorted({g["event_date"] for g in group if g["event_date"]})
            amts = sorted({"%.0f" % amount(g["amount_usd"]) for g in group
                           if amount(g["amount_usd"])})
            merged.append({
                "company_id": cid,
                "event_date": dates[0] if dates else "",
                "date_variants": "|".join(dates),
                "amount_usd": amts[0] if amts else "",
                "amount_variants": "|".join(amts),
                "round_type": next((g["round_type"] for g in group if g["round_type"]), ""),
                "investors": next((g["investors"] for g in group if g["investors"]), ""),
                "evidence_url": next((g["evidence_url"] for g in group if g["evidence_url"]), ""),
                "sources": "|".join(srcs),
                "source_count": len(srcs),
                "date_disagreement": "YES" if len(dates) > 1 else "",
                "amount_disagreement": "YES" if len(amts) > 1 else "",
            })
    # Form D companies that Recent Funding never found at all
    for cid, f in fd.items():
        if f["found"] and cid not in events_rf and f["date"]:
            merged.append({
                "company_id": cid, "event_date": f["date"], "date_variants": f["date"],
                "amount_usd": f["amount"] or "", "amount_variants": f["amount"] or "",
                "round_type": "", "investors": "", "evidence_url": "",
                "sources": "sec_form_d", "source_count": 1,
                "date_disagreement": "", "amount_disagreement": "",
            })
    merged.sort(key=lambda r: (r["company_id"], r["event_date"]))
    with io.open(os.path.join(d, "funding_events_deduplicated.csv"), "w",
                 newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(merged[0].keys()))
        w.writeheader(); w.writerows(merged)

    # ---- report ---------------------------------------------------------
    print("cohort: %d companies\n" % N)
    print("%-16s %-22s %-22s" % ("", "SEC Form D", "Recent Funding"))
    print("%-16s %-22s %-22s" % ("companies resolved", "n/a (filing match)",
                                 "%d  %s" % (resolved, pct(resolved))))
    print("%-16s %-22s %-22s" % ("funding-positive",
                                 "%d  %s" % (fd_found, pct(fd_found)),
                                 "%d  %s" % (rf_found, pct(rf_found))))
    print("%-16s %-22s %-22s" % ("events in window",
                                 rows[0]["events_in_window"], rows[1]["events_in_window"]))
    print("%-16s %-22s %-22s" % ("with amount",
                                 rows[0]["events_with_amount"], rows[1]["events_with_amount"]))
    print("%-16s %-22s %-22s" % ("with evidence URL", 0, rows[1]["events_with_evidence_url"]))

    either = sum(1 for r in ov if r["either_source_found"] == "YES")
    both = sum(1 for r in ov if r["both_sources_found"] == "YES")
    only_fd = sum(1 for r in ov if r["only_form_d"] == "YES")
    only_rf = sum(1 for r in ov if r["only_recent_funding"] == "YES")
    print("\nUNION  (Form D or Recent Funding)")
    print("   companies with at least one funding event : %d  %s" % (either, pct(either)))
    print("   corroborated by both sources              : %d" % both)
    print("   only Form D                               : %d" % only_fd)
    print("   only Recent Funding                       : %d" % only_rf)
    print("\nDEDUPLICATED EVENTS: %d" % len(merged))
    print("   reported by 2+ sources   : %d" % sum(1 for m in merged if m["source_count"] > 1))
    print("   single-source            : %d" % sum(1 for m in merged if m["source_count"] == 1))
    print("   date disagreements       : %d" % sum(1 for m in merged if m["date_disagreement"]))
    print("   amount disagreements     : %d" % sum(1 for m in merged if m["amount_disagreement"]))
    print("   with a traceable URL     : %d" % sum(1 for m in merged if m["evidence_url"]))


if __name__ == "__main__":
    main()
