"""Build a monthly time series of YC 2024 batch companies from the yc-oss mirror.

WHAT IT DOES
    Walks the git history of the `yc-oss/api` repository, takes one commit per
    month, and reads the batch JSON files as they stood at that commit. The
    result is a panel of company records over time, which is what makes dated
    status changes observable at all (the live API only shows "now").

INPUTS
    GitHub public API + raw.githubusercontent.com. No credentials required.
    Rate limits apply to unauthenticated requests (60/hour on the REST API),
    so this script is deliberately slow and resumable by re-running.

OUTPUT
    data/processed/yc2024_monthly.csv
        snapshot, batch, slug, name, status, team_size, one_liner, website,
        locations, industry
    One row per (snapshot month, company). Produced 13,577 rows across 23
    monthly snapshots (2024-10-01 .. 2026-10-01) for the W24/S24/F24 batches.

DOWNSTREAM
    extract_status_transitions.py  reads this file
    build_w24_crosswalk.py         reads this file

IMPORTANT CAVEATS
    1. The earliest usable snapshot is 2024-10-01, which is ~6 months AFTER
       W24 Demo Day (2024-04-03/04). Nothing in this file is point-in-time
       evidence for a Demo Day decision. It is outcome-side data.
    2. yc-oss serves BOTH `batches/winter-2024.json` (live) and a stale frozen
       `batches/w24.json`. They disagree: the stale file reported 7 Inactive /
       2 Acquired where the live file reported 25 Inactive / 14 Acquired.
       Reading the wrong one produces ~18 months of plausible-looking but wrong
       status history and raises NO error. The candidate order below puts the
       long-form filename first for exactly this reason. Do not "optimise" it
       by trying the short name first to avoid 404s.
    3. `launched_at` in yc-oss is the Launch YC POSTING date. It is not the
       founding date, YC entry date, or Demo Day date. Not collected here, but
       do not reintroduce it as a date feature without reading the research log.

USAGE
    python src/data_collection/build_yc_timeseries.py
    python src/data_collection/build_yc_timeseries.py --out some/dir --start 2024-10-01
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date

# Long-form filename FIRST. See caveat 2 in the module docstring.
BATCH_PATHS = {
    "winter-2024": ["batches/winter-2024.json", "batches/w24.json"],
    "summer-2024": ["batches/summer-2024.json", "batches/s24.json"],
    "fall-2024": ["batches/fall-2024.json", "batches/f24.json"],
}

COLS = ["snapshot", "batch", "slug", "name", "status", "team_size",
        "one_liner", "website", "locations", "industry"]

USER_AGENT = "columbia-ieor4511-research"


def say(*a):
    print(*a)
    sys.stdout.flush()


def req(url, raw=False, retry_on_404=False, tries=3):
    """Fetch a URL. Returns None on failure.

    404 is not retried by default: a missing path in an old commit is a normal,
    expected outcome when probing candidate filenames, and retrying it turns a
    fast probe into a multi-minute stall.
    """
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json"})
            body = urllib.request.urlopen(r, timeout=45).read().decode()
            return body if raw else json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code == 404 and not retry_on_404:
                return None
            if i == tries - 1:
                return None
            time.sleep(2)
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(2)
    return None


def month_starts(start, end):
    out = []
    for y in range(start.year, end.year + 1):
        for m in range(1, 13):
            d = date(y, m, 1)
            if start <= d <= end:
                out.append(d.isoformat())
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default=os.path.join("data", "processed"),
                   help="output directory (default: data/processed)")
    p.add_argument("--start", default="2024-10-01",
                   help="first month to snapshot, YYYY-MM-DD (default 2024-10-01)")
    p.add_argument("--end", default="2026-10-01",
                   help="last month to snapshot, YYYY-MM-DD (default 2026-10-01)")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    out_csv = os.path.join(args.out, "yc2024_monthly.csv")

    months = month_starts(date.fromisoformat(args.start), date.fromisoformat(args.end))
    say("target monthly snapshots: %d" % len(months))

    fh = open(out_csv, "w", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(fh, fieldnames=COLS)
    writer.writeheader()

    total = 0
    seen_shas = set()
    for mth in months:
        commits = req("https://api.github.com/repos/yc-oss/api/commits"
                      "?until=%sT23:59:59Z&per_page=1" % mth)
        if not commits:
            say("  %s  no commit or API limited, skipped" % mth)
            continue
        sha = commits[0]["sha"]
        real = commits[0]["commit"]["author"]["date"][:10]
        if sha in seen_shas:
            say("  %s  same commit as previous snapshot, skipped" % real)
            continue
        seen_shas.add(sha)

        batches_got, rows_added = 0, 0
        for batch, candidates in BATCH_PATHS.items():
            arr = None
            used_path = None
            for path in candidates:
                txt = req("https://raw.githubusercontent.com/yc-oss/api/%s/%s" % (sha, path),
                          raw=True)
                if txt:
                    try:
                        arr = json.loads(txt)
                        used_path = path
                        break
                    except Exception:
                        pass
            if arr is None:
                continue
            if used_path != candidates[0]:
                # Loud warning: we fell back to the possibly-stale short filename.
                say("    WARNING %s %s read from fallback path %s - may be a frozen "
                    "stale copy, verify status counts" % (real, batch, used_path))
            batches_got += 1
            for c in arr:
                writer.writerow({
                    "snapshot": real,
                    "batch": batch,
                    "slug": c.get("slug", ""),
                    "name": c.get("name", ""),
                    "status": c.get("status", ""),
                    "team_size": c.get("team_size"),
                    "one_liner": (c.get("one_liner") or "").replace("\n", " ")[:200],
                    "website": c.get("website", ""),
                    "locations": c.get("all_locations", ""),
                    "industry": c.get("industry", ""),
                })
                rows_added += 1

        fh.flush()
        total += rows_added
        say("  %s  batches %d/3  +%d rows  total %d" % (real, batches_got, rows_added, total))
        time.sleep(0.3)

    fh.close()
    say("\ndone -> %s" % out_csv)
    say("total rows %d" % total)


if __name__ == "__main__":
    main()
