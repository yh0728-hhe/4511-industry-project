# -*- coding: utf-8 -*-
"""Build the candidate identifier set used to look each cohort company up.

WHY THIS EXISTS
    Funding databases are keyed on whatever a company is called in their
    records, which may be its 2024 name, its current name, or its domain. About
    26% of this cohort renamed between the decision date and today, and
    Adagy Robotics moved adagy-robotics / adagyrobotics.com / "Adagy Robotics"
    to tuesday-labs / tuesdaylab.com / "Tuesday Labs" with no overlap at all.
    Querying any source by one current name would silently miss those.

    So every company carries an ORDERED list of query candidates, strongest
    identifier first, and a lookup tries them in order until one resolves.

INPUT
    data/processed/w24_raw_outcomes_24m.csv   (already carries the resolved
    identity fields produced by the entity-chain work; nothing is re-derived)

OUTPUT
    data/interim/funding_source_benchmark/company_identifiers.csv
        company_id, name_at_decision, current_name, former_names,
        domain_at_decision, current_domain, renamed, in_yc_directory,
        query_domains, query_names, sample_group

SAMPLE GROUPS
    The benchmark validates on a deliberately mixed subset before scaling to
    240, so a broken matcher is caught on 25 companies rather than on 240:
        unchanged        same name and domain since the decision date
        renamed          identity changed since the decision date
        known_funded     a financing we have already verified independently
        no_evidence      no funding evidence found in any earlier work
        left_directory   absent from the current YC directory
"""

import argparse
import csv
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain, norm_name  # noqa: E402

# Financings verified by hand in earlier work; used as recall sanity checks.
KNOWN_FUNDED = {"leya", "legora", "momentic", "tamarind bio", "trieve",
                "guide labs", "haplotype labs", "argon ai", "driver ai",
                "veles", "malibou", "kiosk", "parallel"}

COLS = ["company_id", "name_at_decision", "current_name", "former_names",
        "domain_at_decision", "current_domain", "renamed", "in_yc_directory",
        "query_domains", "query_names", "sample_group"]


def main():
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("--repo", default=".")
    p.add_argument("--sample-size", type=int, default=25)
    args = p.parse_args()

    src = os.path.join(args.repo, "data", "processed", "w24_raw_outcomes_24m.csv")
    out_dir = os.path.join(args.repo, "data", "interim", "funding_source_benchmark")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for r in csv.DictReader(io.open(src, encoding="utf-8-sig")):
        formers = [f for f in (r["former_names"] or "").split("|") if f]

        # strongest first: domains resolve far more precisely than names
        domains, seen = [], set()
        for d in (r["current_domain"], r["domain_at_decision"]):
            d = norm_domain(d)
            if d and d not in seen:
                seen.add(d)
                domains.append(d)

        names, seen_n = [], set()
        for n in [r["current_name"], r["name_at_decision"]] + formers:
            n = (n or "").strip()
            k = norm_name(n)
            if n and k and k not in seen_n:
                seen_n.add(k)
                names.append(n)

        renamed = r["renamed_since_decision"] == "YES"
        in_dir = r["in_yc_directory_at_cutoff"] == "TRUE"
        funded = any(norm_name(n) in KNOWN_FUNDED for n in names)

        if funded:
            group = "known_funded"
        elif not in_dir:
            group = "left_directory"
        elif renamed:
            group = "renamed"
        elif r["followon_funding_evidence"] == "NO_EVIDENCE_FOUND":
            group = "no_evidence"
        else:
            group = "unchanged"

        rows.append({
            "company_id": r["entity_id"],
            "name_at_decision": r["name_at_decision"],
            "current_name": r["current_name"],
            "former_names": r["former_names"],
            "domain_at_decision": r["domain_at_decision"],
            "current_domain": r["current_domain"],
            "renamed": "YES" if renamed else "NO",
            "in_yc_directory": "YES" if in_dir else "NO",
            "query_domains": "|".join(domains),
            "query_names": "|".join(names),
            "sample_group": group,
        })

    out = os.path.join(out_dir, "company_identifiers.csv")
    with io.open(out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(rows)

    # a mixed validation subset, taken deterministically so reruns agree
    quota = {"known_funded": 7, "renamed": 6, "left_directory": 4,
             "no_evidence": 4, "unchanged": 4}
    picked, counts = [], {}
    for r in rows:
        g = r["sample_group"]
        if counts.get(g, 0) < quota.get(g, 0):
            counts[g] = counts.get(g, 0) + 1
            picked.append(r)
        if len(picked) >= args.sample_size:
            break

    out_s = os.path.join(out_dir, "validation_sample.csv")
    with io.open(out_s, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS)
        w.writeheader()
        w.writerows(picked)

    print("wrote %s  (%d companies)" % (out, len(rows)))
    print("wrote %s  (%d companies)" % (out_s, len(picked)))
    from collections import Counter
    print("\nfull cohort by group:")
    for g, n in Counter(r["sample_group"] for r in rows).most_common():
        print("   %-16s %3d" % (g, n))
    print("validation sample by group:")
    for g, n in Counter(r["sample_group"] for r in picked).most_common():
        print("   %-16s %3d" % (g, n))
    nd = sum(1 for r in rows if not r["query_domains"])
    print("\ncompanies with no usable domain: %d" % nd)
    print("companies with >1 query name: %d"
          % sum(1 for r in rows if len(r["query_names"].split("|")) > 1))


if __name__ == "__main__":
    main()
