"""Extract dated status changes from the monthly YC time series.

PURPOSE
    The live yc-oss API only shows a company's CURRENT status. Comparing
    consecutive monthly snapshots turns that into dated events, which is the
    only way to put a status change on a timeline at all.

INPUT
    data/processed/yc2024_monthly.csv  (from build_yc_timeseries.py)

OUTPUT
    data/processed/status_transitions.csv
        batch, slug, name, from_status, to_status, changed_between,
        detected_at, website, industry

    `changed_between` is the snapshot where the old status was last seen and
    `detected_at` is the snapshot where the new status first appeared. The real
    change happened somewhere in that interval; monthly sampling cannot narrow
    it further. Do not treat `detected_at` as the event date.

    Produced 55 dated transitions for the 2024 batches.

HOW THIS MUST NOT BE USED
    1. These 55 transitions are NOT the outcome sample. A company that is still
       Active at the outcome cutoff has an outcome too. Restricting Y to
       companies that changed status would condition the sample on the label.
    2. Active is not success, Inactive is not total loss, Acquired is not a
       successful exit, and disappearing from the YC directory is not failure.
       See docs/research_log/2026-10-29_w24_backtest_design.md section 9.
    3. The series begins 2024-10-01, about six months AFTER W24 Demo Day. Every
       field here is post-decision and may never be used as X.

USAGE
    python src/outcome_tracking/extract_status_transitions.py
    python src/outcome_tracking/extract_status_transitions.py --cutoff 2026-04-04
"""

import argparse
import csv
import os
from collections import defaultdict

COLS = ["batch", "slug", "name", "from_status", "to_status",
        "changed_between", "detected_at", "website", "industry"]


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--timeseries", default=os.path.join("data", "processed",
                                                        "yc2024_monthly.csv"))
    p.add_argument("--out", default=os.path.join("data", "processed",
                                                 "status_transitions.csv"))
    p.add_argument("--cutoff", default=None,
                   help="optional YYYY-MM-DD; transitions detected after this "
                        "are excluded from the output (use 2026-04-04 for the "
                        "primary 24-month outcome window)")
    args = p.parse_args()

    # slug -> [(snapshot, row), ...] in snapshot order
    history = defaultdict(list)
    for r in csv.DictReader(open(args.timeseries, encoding="utf-8-sig")):
        history[(r["batch"], r["slug"])].append(r)

    rows = []
    for (batch, slug), recs in history.items():
        recs.sort(key=lambda r: r["snapshot"])
        for prev, cur in zip(recs, recs[1:]):
            if not prev["status"] or not cur["status"]:
                continue
            if prev["status"] == cur["status"]:
                continue
            if args.cutoff and cur["snapshot"] > args.cutoff:
                continue
            rows.append({
                "batch": batch,
                "slug": slug,
                "name": cur["name"],
                "from_status": prev["status"],
                "to_status": cur["status"],
                "changed_between": prev["snapshot"],
                "detected_at": cur["snapshot"],
                "website": cur["website"],
                "industry": cur["industry"],
            })

    rows.sort(key=lambda r: r["detected_at"], reverse=True)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    print("wrote %s" % args.out)
    print("%d dated transitions across %d companies tracked"
          % (len(rows), len(history)))
    pairs = defaultdict(int)
    for r in rows:
        pairs[(r["from_status"], r["to_status"])] += 1
    for (a, b), n in sorted(pairs.items(), key=lambda kv: -kv[1]):
        print("  %-10s -> %-10s  %d" % (a, b, n))
    print("\nNOTE: companies with no transition still have an outcome. "
          "Do not use this file as the outcome sample.")


if __name__ == "__main__":
    main()
