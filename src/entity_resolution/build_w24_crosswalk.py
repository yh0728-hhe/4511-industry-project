"""Crosswalk the dated 2024-03-25 W24 spreadsheet to the current yc-oss universe.

PURPOSE
    Link each company in the dated pre-Demo-Day spreadsheet to its record in
    the current yc-oss W24 batch, so that outcome data (which only exists for
    current records) can be attached to a point-in-time cohort.

INPUTS
    --sheet       2024-03-25 historical W24 spreadsheet
                  columns: Company Name, Company Website, YC Link,
                  Short Description, Tags, Location, Date Launched
    --timeseries  data/processed/yc2024_monthly.csv
    live yc-oss:  batches/winter-2024.json and companies/all.json

OUTPUTS
    data/processed/w24_crosswalk.csv
        sheet_name, sheet_domain, sheet_slug, matched_slug, matched_name,
        method, renamed
    data/processed/w24_uncertain_matches.csv   (only if any exist)
        multi-candidate matches, left UNRESOLVED for human review

MATCH ORDER
    1. YC slug from the spreadsheet's YC Link (exact, strongest)
    2. domain, only if exactly one current company has that domain
    3. name or former_name, only if exactly one current company has that name

    A match is accepted only when the candidates agree on a single slug.
    Multi-candidate cases are written to the uncertain file and never merged.
    There is no fuzzy matching anywhere in this pipeline.

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
    1. It does not emit a single `demo_day_eligible` boolean. An earlier draft
       hardcoded `demo_day_eligible=TRUE` for every company with the evidence
       string "W24 batch membership (yc-oss)". That was wrong: current yc-oss
       batch membership is a 2026 fact and is not dated evidence that a company
       was a visible W24 investment opportunity in April 2024. Membership is
       instead recorded per source with that source's date.
    2. It does not collect founder LinkedIn URLs. An earlier draft wrote a
       `founder_links` column, which would publish several hundred named
       individuals' personal profile URLs into a shared repository. Founder
       data, if needed, belongs in a local file that is not committed.

USAGE
    python src/entity_resolution/build_w24_crosswalk.py --sheet path/to/w24_2024-03-25.csv
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from entity_resolution.normalize import (  # noqa: E402
    build_indexes, norm_domain, norm_name, yc_slug)

USER_AGENT = "columbia-ieor4511-research"


def jget(url, timeout=60, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())
        except Exception:
            if i == tries - 1:
                return None
            time.sleep(5 * (i + 1))


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sheet", required=True,
                   help="2024-03-25 historical W24 spreadsheet CSV")
    p.add_argument("--timeseries", default=os.path.join("data", "processed",
                                                        "yc2024_monthly.csv"))
    p.add_argument("--out", default=os.path.join("data", "processed"))
    p.add_argument("--current-snapshot", default="2026-10-01",
                   help="snapshot in the time series treated as 'current'")
    args = p.parse_args()

    sheet = list(csv.DictReader(open(args.sheet, encoding="utf-8-sig")))
    ts = list(csv.DictReader(open(args.timeseries, encoding="utf-8-sig")))
    current = {r["slug"]: r for r in ts
               if r["batch"] == "winter-2024" and r["snapshot"] == args.current_snapshot}

    all_companies = jget("https://yc-oss.github.io/api/companies/all.json", 120) or []
    by_domain, by_name = build_indexes(all_companies)
    print("sheet rows %d / current W24 %d / all yc-oss %d"
          % (len(sheet), len(current), len(all_companies)))

    rows, uncertain = [], []
    for r in sheet:
        s_slug = yc_slug(r.get("YC Link"))
        s_dom = norm_domain(r.get("Company Website"))
        s_name = norm_name(r.get("Company Name"))

        matched, method = None, ""
        if s_slug in current:
            matched, method = s_slug, "slug"
        else:
            candidates = []
            if len(by_domain.get(s_dom, [])) == 1:
                candidates.append((by_domain[s_dom][0], "domain"))
            if len(by_name.get(s_name, [])) == 1:
                candidates.append((by_name[s_name][0], "former_name"))
            unique = {c[0].get("slug") for c in candidates}
            if len(unique) == 1 and candidates:
                hit, method = candidates[0]
                if hit.get("slug") in current:
                    matched = hit["slug"]
            elif len(unique) > 1:
                uncertain.append({
                    "sheet_name": r.get("Company Name", ""),
                    "sheet_slug": s_slug,
                    "sheet_domain": s_dom,
                    "candidates": "|".join(sorted(unique)),
                    "reason": "multiple candidates, NOT merged - needs human review",
                })

        cur_name = current.get(matched, {}).get("name", "") if matched else ""
        rows.append({
            "sheet_name": r.get("Company Name", ""),
            "sheet_domain": s_dom,
            "sheet_slug": s_slug,
            "matched_slug": matched or "",
            "matched_name": cur_name,
            "method": method,
            # blank when unmatched: we cannot tell whether an unmatched company
            # was renamed or simply removed from the directory
            "renamed": ("YES" if norm_name(cur_name) != s_name else "")
                       if matched else "",
        })

    os.makedirs(args.out, exist_ok=True)
    out_main = os.path.join(args.out, "w24_crosswalk.csv")
    with open(out_main, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n_matched = sum(1 for r in rows if r["matched_slug"])
    n_renamed = sum(1 for r in rows if r["renamed"] == "YES")
    print("wrote %s" % out_main)
    print("matched %d/%d (%.1f%%), renamed %d (%.1f%% of matched)"
          % (n_matched, len(rows), 100.0 * n_matched / len(rows),
             n_renamed, 100.0 * n_renamed / max(n_matched, 1)))
    print("unmatched %d - these are NOT 'not in W24'; they are companies the "
          "current directory no longer lists" % (len(rows) - n_matched))

    if uncertain:
        out_unc = os.path.join(args.out, "w24_uncertain_matches.csv")
        with open(out_unc, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=list(uncertain[0].keys()))
            w.writeheader()
            w.writerows(uncertain)
        print("uncertain matches %d -> %s (left unresolved by design)"
              % (len(uncertain), out_unc))
    else:
        print("no uncertain matches")


if __name__ == "__main__":
    main()
