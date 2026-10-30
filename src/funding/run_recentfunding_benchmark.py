# -*- coding: utf-8 -*-
"""Resolve every cohort company against Recent Funding and pull its rounds.

TWO-PASS MATCHING, CHEAPEST AND STRONGEST FIRST
    Pass 1  the YC W24 roster already fetched by fetch_recentfunding_yc.py.
            A YC slug is an exact identifier, so this costs no extra request
            and resolves most of the cohort.
    Pass 2  for whatever is left, /companies?q= with each candidate
            identifier, domains before names, because a domain disambiguates
            and a name does not.

    Only then is the per-company detail fetched for its rounds.

STATUSES, AND WHY THEY MATTER
    FUNDING_EVENT_FOUND             rounds inside the window were returned
    COMPANY_FOUND_NO_EVENT_RETURNED the company resolved, no rounds in window
    COMPANY_NOT_FOUND               no identifier resolved
    AMBIGUOUS_MATCH                 several candidates; deliberately unresolved
    SOURCE_QUERY_FAILED             the request failed; we know nothing

    COMPANY_FOUND_NO_EVENT_RETURNED and SOURCE_QUERY_FAILED are NOT evidence
    that a company raised nothing. Only the source's own coverage could support
    that, and this benchmark exists to measure whether it can.

WINDOW
    An event counts only when 2024-04-04 < announced_at <= 2026-04-04.
    Rounds on or before the decision date are prior funding, i.e. X, not Y.
    Rounds after the cutoff are kept in a separate column, never in the
    primary window figures.

OUTPUTS (data/interim/funding_source_benchmark/)
    recentfunding_company_matches.csv   one row per cohort company
    recentfunding_events_raw.csv        one row per round, any date
    raw_recentfunding/*.json            cached responses, so a re-run is free
"""

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain, norm_name  # noqa: E402
from funding.sources import (ON_BEHALF_OF, USER_AGENT, AMBIGUOUS, FAILED,  # noqa: E402
                             FOUND, NO_EVENT, NOT_FOUND, load_env)

BASE = "https://recentfunding.com/api/v1"
WINDOW_START = "2024-04-04"   # exclusive
WINDOW_END = "2026-04-04"     # inclusive


class Api(object):
    def __init__(self, key, cache_dir, budget=900):
        self.key = key
        self.cache_dir = cache_dir
        self.budget = budget
        self.spent = 0
        self.cached = 0
        os.makedirs(cache_dir, exist_ok=True)

    def get(self, path, params, tag, tries=3):
        """Returns (data, error). Cached responses never spend budget."""
        cache = os.path.join(self.cache_dir, "rf_%s.json" % tag)
        if os.path.exists(cache):
            self.cached += 1
            try:
                return json.load(io.open(cache, encoding="utf-8")), None
            except ValueError:
                os.remove(cache)
        if self.spent >= self.budget:
            return None, "local budget exhausted"
        url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
        last = None
        for i in range(tries):
            try:
                self.spent += 1
                req = urllib.request.Request(url, headers={
                    "Authorization": "Bearer " + self.key,
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                    "X-On-Behalf-Of": ON_BEHALF_OF})
                with urllib.request.urlopen(req, timeout=45) as r:
                    data = json.loads(r.read().decode("utf-8"))
                io.open(cache, "w", encoding="utf-8").write(
                    json.dumps(data, ensure_ascii=False))
                time.sleep(0.8)
                return data, None
            except urllib.error.HTTPError as e:
                last = "HTTP %s" % e.code
                if e.code == 404:
                    return None, last
                if e.code in (401, 403):
                    return None, "auth:" + last
                if e.code == 429:
                    time.sleep(25 * (i + 1))
                    continue
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, e)
            time.sleep(3 * (i + 1))
        return None, last


def day(ts):
    return str(ts or "")[:10]


def in_window(d):
    return bool(d) and len(d) == 10 and WINDOW_START < d <= WINDOW_END


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--repo", default=".")
    p.add_argument("--limit", type=int, default=0, help="only first N companies")
    p.add_argument("--only-sample", action="store_true",
                   help="run the 22-company validation sample instead of all 240")
    args = p.parse_args()

    load_env(os.path.join(args.repo, ".env"))
    key = os.environ.get("RECENTFUNDING_API_KEY")
    if not key:
        raise SystemExit("RECENTFUNDING_API_KEY not set")

    d = os.path.join(args.repo, "data", "interim", "funding_source_benchmark")
    api = Api(key, os.path.join(d, "raw_recentfunding"))

    src = "validation_sample.csv" if args.only_sample else "company_identifiers.csv"
    cohort = list(csv.DictReader(io.open(os.path.join(d, src), encoding="utf-8-sig")))
    if args.limit:
        cohort = cohort[:args.limit]

    roster = list(csv.DictReader(io.open(
        os.path.join(d, "recentfunding_yc_roster.csv"), encoding="utf-8-sig")))
    by_slug = {r["slug"]: r for r in roster}
    by_name = {}
    for r in roster:
        by_name.setdefault(norm_name(r["name"]), []).append(r)

    mrows, erows = [], []
    for i, c in enumerate(cohort, 1):
        domains = [x for x in c["query_domains"].split("|") if x]
        names = [x for x in c["query_names"].split("|") if x]
        slug = note = ""
        status = NOT_FOUND

        # pass 1: the YC roster, free
        if c["company_id"] in by_slug:
            slug, note = c["company_id"], "yc roster slug"
        else:
            for n in names:
                cand = by_name.get(norm_name(n))
                if cand and len(cand) == 1:
                    slug, note = cand[0]["slug"], "yc roster name %r" % n
                    break
                if cand and len(cand) > 1:
                    status, note = AMBIGUOUS, "%d roster rows for %r" % (len(cand), n)

        # pass 2: name search, then disambiguate on the candidate's own website.
        # The source's q matches names only - a domain query returns nothing,
        # even "momentic.ai" when "momentic" resolves - so domains are not sent
        # as queries. They are used to pick the right candidate instead, which
        # is what makes a generic name like "Abel" or "Lantern" resolvable.
        if not slug:
            status = NOT_FOUND
            for q in names:
                data, err = api.get("/companies", {"q": q, "limit": 10},
                                    "q_" + norm_name(q).replace(" ", "_"))
                if err:
                    if err.startswith("auth"):
                        raise SystemExit("authentication failed: " + err)
                    status, note = FAILED, "search %r: %s" % (q, err)
                    break
                items = data.get("companies") or []
                if not items:
                    continue
                exact = [it for it in items
                         if norm_name(it.get("name")) == norm_name(q)]
                pool = exact or items
                bydom = [it for it in pool
                         if norm_domain(it.get("website")) in domains]
                if len(bydom) == 1:
                    slug, note = bydom[0].get("slug"), "search %r, domain match" % q
                    break
                if len(bydom) > 1:
                    status, note = AMBIGUOUS, "%d candidates share a cohort domain for %r" % (len(bydom), q)
                    break
                if len(pool) == 1:
                    cand_dom = norm_domain(pool[0].get("website"))
                    # A lone candidate is NOT automatically the right company.
                    # Our Lantern is lantern.dev; the source's only "Lantern" is
                    # lanternhq.com, a different company - the same same-name
                    # collision that already produced a false Form D match. When
                    # we hold a domain and the candidate publishes a different
                    # one, refuse rather than accept on the strength of a name.
                    if domains and cand_dom and cand_dom not in domains:
                        status, note = AMBIGUOUS, (
                            "single candidate for %r rejected: its domain %s is not %s"
                            % (q, cand_dom, ",".join(domains)))
                        break
                    slug, note = pool[0].get("slug"), "search %r, single candidate" % q
                    break
                status, note = AMBIGUOUS, ("%d candidates for %r, none matching domains %s"
                                           % (len(pool), q, ",".join(domains) or "-"))

        rounds_in, rounds_post, rounds_pre = [], [], []
        website = ""
        if slug:
            data, err = api.get("/companies/%s" % slug, None, "c_" + slug)
            if err:
                status, note = FAILED, "detail %s: %s" % (slug, err)
            else:
                comp = data.get("company") or {}
                website = comp.get("website") or ""
                for r in (data.get("rounds") or []):
                    dt = day(r.get("announced_at"))
                    ev = {
                        "company_id": c["company_id"],
                        "source": "recent_funding",
                        "matched_slug": slug,
                        "matched_name": comp.get("name", ""),
                        "event_date": dt,
                        "amount_usd": r.get("amount_usd") or "",
                        "valuation_usd": r.get("valuation_usd") or "",
                        "round_type": r.get("stage") or "",
                        "investors": "|".join(
                            x.get("name", "") if isinstance(x, dict) else str(x)
                            for x in (r.get("investors") or [])),
                        "evidence_url": r.get("source_url") or "",
                        "evidence_publisher": r.get("source_publisher") or "",
                        "in_window": "",
                    }
                    if not dt:
                        ev["in_window"] = "NO_DATE"
                        rounds_pre.append(ev)
                    elif in_window(dt):
                        ev["in_window"] = "IN_WINDOW"
                        rounds_in.append(ev)
                    elif dt > WINDOW_END:
                        ev["in_window"] = "POST_CUTOFF"
                        rounds_post.append(ev)
                    else:
                        ev["in_window"] = "PRE_DECISION"
                        rounds_pre.append(ev)
                    erows.append(ev)
                if status not in (FAILED, AMBIGUOUS):
                    status = FOUND if rounds_in else NO_EVENT

        amounts = [float(e["amount_usd"]) for e in rounds_in
                   if str(e["amount_usd"]).replace(".", "").isdigit()]
        mrows.append({
            "company_id": c["company_id"],
            "name_at_decision": c["name_at_decision"],
            "current_name": c["current_name"],
            "sample_group": c["sample_group"],
            "source": "recent_funding",
            "match_status": status,
            "matched_slug": slug,
            "matched_website": website,
            "match_note": note,
            "events_in_window": len(rounds_in),
            "first_event_date": min([e["event_date"] for e in rounds_in]) if rounds_in else "",
            "cumulative_usd_in_window": ("%.0f" % sum(amounts)) if amounts else "",
            "events_with_amount": sum(1 for e in rounds_in if e["amount_usd"]),
            "events_with_evidence_url": sum(1 for e in rounds_in if e["evidence_url"]),
            "events_post_cutoff": len(rounds_post),
            "events_pre_decision_or_undated": len(rounds_pre),
        })
        if i % 20 == 0 or i == len(cohort):
            print("  %3d/%d  spent=%d cached=%d" % (i, len(cohort), api.spent, api.cached),
                  flush=True)

    mcols = list(mrows[0].keys())
    with io.open(os.path.join(d, "recentfunding_company_matches.csv"), "w",
                 newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=mcols); w.writeheader(); w.writerows(mrows)
    if erows:
        ecols = list(erows[0].keys())
        with io.open(os.path.join(d, "recentfunding_events_raw.csv"), "w",
                     newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=ecols); w.writeheader(); w.writerows(erows)

    from collections import Counter
    print("\nrequests: %d new, %d from cache" % (api.spent, api.cached))
    print("\nmatch status:")
    for k, n in Counter(r["match_status"] for r in mrows).most_common():
        print("   %-32s %3d  %.1f%%" % (k, n, 100.0 * n / len(mrows)))
    ev = [e for e in erows if e["in_window"] == "IN_WINDOW"]
    print("\nevents in window: %d across %d companies"
          % (len(ev), sum(1 for r in mrows if r["events_in_window"])))
    print("   with a date      : %d" % sum(1 for e in ev if e["event_date"]))
    print("   with an amount   : %d" % sum(1 for e in ev if e["amount_usd"]))
    print("   with evidence URL: %d" % sum(1 for e in ev if e["evidence_url"]))
    print("   post-cutoff events held separately: %d"
          % sum(1 for e in erows if e["in_window"] == "POST_CUTOFF"))
    print("   pre-decision or undated: %d"
          % sum(1 for e in erows if e["in_window"] in ("PRE_DECISION", "NO_DATE")))


if __name__ == "__main__":
    main()
