# -*- coding: utf-8 -*-
"""Pull Recent Funding's Y Combinator roster and keep the W24 cohort.

WHY THIS SHAPE
    /accelerators/yc lists every YC company the source knows with its cohort
    label, and its `batches` summary reports 194 companies for "YC W24". Paging
    that roster once and filtering locally costs ~42 requests, where looking up
    240 companies one at a time would cost far more and would depend on name
    search resolving correctly for each one.

    The roster rows carry no website, so a second pass fetches each matched
    company's detail for its domain and its funding rounds.

OUTPUT
    data/interim/funding_source_benchmark/recentfunding_yc_roster.csv
        slug, name, cohort, year, first_seen, total_raised
    Raw JSON pages are cached under the same directory so the run is auditable
    and re-runnable without spending quota again.

NOTE ON QUOTA
    The key issued for this benchmark is a 24-hour "taste" plan with 1,000
    requests/day. The cache exists so that a re-run costs nothing.
"""

import argparse
import csv
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from funding.sources import load_env, USER_AGENT, ON_BEHALF_OF  # noqa: E402

import urllib.error
import urllib.parse
import urllib.request

BASE = "https://recentfunding.com/api/v1"


def get(path, params, key, cache_dir, tag, tries=3):
    """GET with an on-disk cache, so re-runs do not spend quota."""
    cache = os.path.join(cache_dir, "rf_%s.json" % tag)
    if os.path.exists(cache):
        return json.load(io.open(cache, encoding="utf-8")), True
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": "Bearer " + key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "X-On-Behalf-Of": ON_BEHALF_OF})
            with urllib.request.urlopen(req, timeout=45) as r:
                data = json.loads(r.read().decode("utf-8"))
            io.open(cache, "w", encoding="utf-8").write(
                json.dumps(data, ensure_ascii=False))
            return data, False
        except urllib.error.HTTPError as e:
            last = "HTTP %s" % e.code
            if e.code in (401, 403):
                raise RuntimeError("auth failed: %s" % last)
            if e.code == 429:
                time.sleep(25 * (i + 1))
                continue
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
        time.sleep(4 * (i + 1))
    raise RuntimeError("request failed: %s (%s)" % (url, last))


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--repo", default=".")
    p.add_argument("--cohort", default="YC W24")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--max-pages", type=int, default=60)
    args = p.parse_args()

    load_env(os.path.join(args.repo, ".env"))
    key = os.environ.get("RECENTFUNDING_API_KEY")
    if not key:
        raise SystemExit("RECENTFUNDING_API_KEY not set (expected in .env)")

    out_dir = os.path.join(args.repo, "data", "interim", "funding_source_benchmark")
    cache_dir = os.path.join(out_dir, "raw_recentfunding")
    os.makedirs(cache_dir, exist_ok=True)

    rows, offset, fetched, cached = [], 0, 0, 0
    batches = None
    for page in range(args.max_pages):
        data, from_cache = get("/accelerators/yc",
                               {"limit": args.page_size, "offset": offset},
                               key, cache_dir, "yc_%06d" % offset)
        cached += 1 if from_cache else 0
        fetched += 0 if from_cache else 1
        if batches is None:
            batches = data.get("batches") or []
        comps = data.get("companies") or []
        if not comps:
            break
        rows.extend(comps)
        nxt = data.get("next_offset")
        if not nxt or nxt <= offset:
            break
        offset = nxt
        if not from_cache:
            time.sleep(1.2)          # stay well inside the rate limit

    print("roster rows: %d  (requests: %d new, %d from cache)"
          % (len(rows), fetched, cached))
    w24_declared = next((b.get("companies") for b in (batches or [])
                         if b.get("cohort") == args.cohort), None)
    print("source reports %s = %s companies" % (args.cohort, w24_declared))

    sel = [c for c in rows if c.get("cohort") == args.cohort]
    print("rows matching cohort locally: %d" % len(sel))

    out = os.path.join(out_dir, "recentfunding_yc_roster.csv")
    cols = ["slug", "name", "cohort", "year", "first_seen", "total_raised"]
    with io.open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for c in sel:
            w.writerow({k: c.get(k, "") for k in cols})
    print("wrote %s" % out)

    with_raise = sum(1 for c in sel if c.get("total_raised"))
    print("of those, with a non-zero total_raised: %d" % with_raise)
    print("\nNOTE: total_raised is lifetime, not window-bounded. It is a "
          "triage signal only; the 24-month figure comes from the per-company "
          "rounds, filtered by announced_at.")


if __name__ == "__main__":
    main()
