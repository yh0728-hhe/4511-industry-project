"""Collect dated evidence that a company was a publicly visible W24 company by t.

PURPOSE
    For each company, look for POSITIVE DATED EVIDENCE existing on or before the
    Demo Day cutoff (2024-04-04 23:59:59). Used to audit the 27 companies that
    appear in the current yc-oss W24 universe but not in the dated 2024-03-25
    spreadsheet.

INPUTS
    --companies  CSV with columns: slug, name [, website]
                 If `website` is absent it is looked up from the yc time series.
    --timeseries data/processed/yc2024_monthly.csv  (for website lookup)

OUTPUT
    outputs/<name>_audit.csv with columns:
        company_id, company_name, classification, evidence_found,
        earliest_verified_date, evidence_source, evidence_url_or_archive,
        explicitly_mentions_W24, publicly_visible_by_demo_day, confidence,
        query_status, notes

EVIDENCE SOURCES, AND WHAT EACH CAN AND CANNOT PROVE
    1. Archived YC company detail page (ycombinator.com/companies/<slug>)
       The ONLY source that can prove batch membership, because the archived
       HTML of a company page contains the literal "W24" / "Winter 2024".
       NOTE: the batch LISTING page (companies?batch=W24) does NOT work. It has
       pre-Demo-Day captures (2024-02-18, 2024-03-24, 2024-03-30) but the
       directory is an Algolia-driven front end, so no company name ever
       appears in the archived HTML. Tested; do not retry it.
    2. Company website captures.
       Can show the company was publicly in existence before t. Cannot show
       batch membership unless the page itself says so.
       Uses the LATEST pre-cutoff capture, not the earliest, and verifies the
       page actually names the company. The earliest capture of a domain is
       often a previous owner's site: copperhealth.com has a 2017 capture and
       furtherai.com a 2018 one, years before these companies existed. Domain
       age is not company age.
    3. Hacker News (Algolia API, exact timestamps).
       Accepted only when a record binds the name directly to the batch, i.e.
       matches `<name> (YC W24)`. A loose substring test produced a false
       positive: the company "Sample" matched the word "sample" inside
       "Launch HN: Soundry AI (YC W24) - Music sample generator".

CLASSIFICATION
    CONFIRMED   explicit W24/Winter 2024 attribution in a source dated <= cutoff
    PROBABLE    dated, content-verified public presence by cutoff, no W24 attribution
    UNRESOLVED  no qualifying dated source found

    There is deliberately NO "NOT ELIGIBLE" class. Absence of an archive is not
    evidence of non-membership, and no company was found with positive evidence
    of joining W24 after Demo Day. UNRESOLVED describes OUR evidence, not the
    company. See docs/research_log/2026-10-29_w24_backtest_design.md section 3.

USAGE
    python src/data_collection/collect_pre_demoday_evidence.py \
        --companies data/processed/w24_late_published_27.csv \
        --out outputs/w24_27_audit.csv
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_collection.wayback import (  # noqa: E402
    OK, FetchFailed, cdx_captures, fetch, snapshot_text, ts_to_date)
from entity_resolution.normalize import norm_domain  # noqa: E402

CUTOFF_TS = "20240404235959"          # end of W24 Demo Day
CUTOFF_EPOCH = 1712275200             # 2024-04-05 00:00:00 UTC
CUTOFF_DATE = "2024-04-04"

W24_PATTERN = re.compile(r"\bW24\b|Winter\s*2024", re.I)

COLS = ["company_id", "company_name", "classification", "evidence_found",
        "earliest_verified_date", "evidence_source", "evidence_url_or_archive",
        "explicitly_mentions_W24", "publicly_visible_by_demo_day",
        "confidence", "query_status", "notes"]


def earliest(*dates):
    vals = [d for d in dates if d]
    return min(vals) if vals else None


def hn_strict(name):
    """Hacker News records before the cutoff that bind `name` to YC W24.

    Returns ((date, item_id, snippet) or None, status). The regex requires the
    company name immediately followed by "(YC W24)" so that a generic company
    name cannot match an unrelated post. See source note 3 above.
    """
    q = urllib.parse.urlencode({
        "query": '"%s" "YC W24"' % name,
        "numericFilters": "created_at_i<%d" % CUTOFF_EPOCH,
        "hitsPerPage": "50"})
    try:
        txt = fetch("https://hn.algolia.com/api/v1/search?" + q, tries=3, timeout=45)
    except FetchFailed as e:
        return None, "QUERY_FAILED(%s)" % e
    try:
        hits = json.loads(txt).get("hits", [])
    except ValueError:
        return None, "QUERY_FAILED(bad json)"
    bound = re.compile(re.escape(name) + r"\s*\(\s*YC\s*W24\s*\)", re.I)
    for h in hits:
        for field in ("title", "story_text", "comment_text"):
            val = h.get(field) or ""
            if bound.search(val):
                return (h.get("created_at", "")[:10], h.get("objectID"), val[:120]), OK
    return None, OK


def audit_company(slug, name, website):
    """Gather evidence for one company. Returns a dict matching COLS."""
    sources, urls, notes, issues = [], [], [], []
    mentions_w24, date_w24, date_visible = "NO", None, None

    # --- 1. archived YC company detail page -------------------------------
    caps = []
    for pattern in ("ycombinator.com/companies/" + slug,
                    "www.ycombinator.com/companies/" + slug):
        found, status = cdx_captures(pattern, CUTOFF_TS)
        caps += found
        if status != OK:
            issues.append("yc_cdx:" + status)
        time.sleep(1.2)

    if caps:
        caps.sort(key=lambda c: c[0])
        ts0 = caps[0][0]
        d0 = ts_to_date(ts0)
        sources.append("YC company page (Wayback)")
        urls.append("https://web.archive.org/web/%s/https://www.ycombinator.com/companies/%s"
                    % (ts0, slug))
        notes.append("YC page: %d capture(s) by cutoff, earliest %s" % (len(caps), d0))
        body, status = snapshot_text(ts0, "https://www.ycombinator.com/companies/" + slug)
        if status != OK:
            issues.append("yc_body:" + status)
            notes.append("YC page archived but content fetch FAILED - not checked")
        elif W24_PATTERN.search(body):
            mentions_w24, date_w24, date_visible = "YES", d0, d0
            notes.append("archived YC page HTML contains W24/Winter 2024")
        else:
            notes.append("YC page archived but HTML has no W24 string")
        time.sleep(1.2)
    elif not issues:
        notes.append("YC page: 0 captures by cutoff (query succeeded)")

    # --- 2. company website, latest pre-cutoff capture, content-verified ---
    if website:
        dom = norm_domain(website)
        caps_w, status = cdx_captures(dom, CUTOFF_TS, match_type="prefix")
        if status != OK:
            issues.append("web_cdx:" + status)
            notes.append("website CDX for %s FAILED - UNKNOWN, not zero" % dom)
        elif caps_w:
            caps_w.sort(key=lambda c: c[0])
            ts_last = caps_w[-1][0]
            d_last = ts_to_date(ts_last)
            notes.append("website %s: %d capture(s) by cutoff, latest %s (earliest %s)"
                         % (dom, len(caps_w), d_last, ts_to_date(caps_w[0][0])))
            body, bstatus = snapshot_text(ts_last, website)
            if bstatus != OK:
                issues.append("web_body:" + bstatus)
                notes.append("website snapshot content fetch FAILED - not counted")
            else:
                text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
                names_company = re.search(
                    r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text, re.I)
                if names_company:
                    sources.append("company website (Wayback, content-verified)")
                    urls.append("https://web.archive.org/web/%s/%s" % (ts_last, website))
                    date_visible = earliest(date_visible, d_last)
                    notes.append("latest pre-cutoff website snapshot names the company")
                    if W24_PATTERN.search(text):
                        mentions_w24 = "YES"
                        date_w24 = earliest(date_w24, d_last)
                        notes.append("website snapshot itself states W24")
                    elif re.search(r"Y\s*Combinator", text, re.I):
                        notes.append("website mentions Y Combinator but not the batch")
                else:
                    notes.append("latest pre-cutoff snapshot does NOT name the company "
                                 "- domain likely held by someone else; NOT counted")
            time.sleep(1.2)
        else:
            notes.append("website %s: 0 captures by cutoff (query succeeded)" % dom)
    else:
        notes.append("no website on record")

    # --- 3. Hacker News, strict binding -----------------------------------
    hit, status = hn_strict(name)
    if status != OK:
        issues.append("hn:" + status)
    elif hit:
        d_hn, item_id, snippet = hit
        mentions_w24 = "YES"
        date_w24 = earliest(date_w24, d_hn)
        date_visible = earliest(date_visible, d_hn)
        sources.append("Hacker News (strict name + YC W24)")
        urls.append("https://news.ycombinator.com/item?id=%s" % item_id)
        notes.append('HN %s: "%s"' % (d_hn, snippet))
    time.sleep(0.6)

    # --- classify ---------------------------------------------------------
    if mentions_w24 == "YES":
        classification, confidence = "CONFIRMED", "high"
    elif date_visible:
        classification, confidence = "PROBABLE", "medium"
        notes.append("dated, content-verified public presence by cutoff, "
                     "but no contemporaneous W24 attribution")
    else:
        classification, confidence = "UNRESOLVED", "none"
        notes.append("no qualifying dated source; absence of archive is NOT "
                     "evidence of non-membership")
    if issues:
        notes.append("QUERY ISSUES: " + "; ".join(issues))

    return {
        "company_id": slug,
        "company_name": name,
        "classification": classification,
        "evidence_found": "YES" if date_visible else "NO",
        "earliest_verified_date": date_w24 or date_visible or "",
        "evidence_source": "; ".join(dict.fromkeys(sources)),
        "evidence_url_or_archive": " | ".join(dict.fromkeys(urls))[:600],
        "explicitly_mentions_W24": mentions_w24,
        "publicly_visible_by_demo_day": "YES" if date_visible else "UNKNOWN",
        "confidence": confidence,
        "query_status": "; ".join(issues) if issues else OK,
        "notes": " / ".join(notes)[:900],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--companies", required=True,
                   help="CSV with slug,name[,website]")
    p.add_argument("--timeseries", default=os.path.join("data", "processed",
                                                        "yc2024_monthly.csv"),
                   help="yc monthly time series, used to look up missing websites")
    p.add_argument("--out", default=os.path.join("outputs", "pre_demoday_audit.csv"))
    args = p.parse_args()

    targets = list(csv.DictReader(open(args.companies, encoding="utf-8-sig")))

    websites = {}
    if os.path.exists(args.timeseries):
        for r in csv.DictReader(open(args.timeseries, encoding="utf-8-sig")):
            if r["slug"] not in websites and r.get("website"):
                websites[r["slug"]] = r["website"]

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    fh = open(args.out, "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(fh, fieldnames=COLS)
    writer.writeheader()

    for i, t in enumerate(targets, 1):
        slug, name = t["slug"], t["name"]
        website = t.get("website") or websites.get(slug, "")
        row = audit_company(slug, name, website)
        writer.writerow(row)
        fh.flush()
        print("[%2d/%d] %-18s %-10s w24=%-3s q=%s"
              % (i, len(targets), name, row["classification"],
                 row["explicitly_mentions_W24"],
                 "OK" if row["query_status"] == OK else "ISSUES"), flush=True)

    fh.close()
    print("\nwrote " + args.out)


if __name__ == "__main__":
    main()
