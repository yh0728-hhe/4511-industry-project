"""Download SEC Form D quarterly datasets (reproduction script).

WHY A SCRIPT INSTEAD OF COMMITTED DATA
    The extracted quarterly datasets are about 100 MB (plus ~37 MB of zips) for
    2024Q1-2026Q3. That is third-party bulk data, reproducible from a stable
    public URL, so this repository stores the fetch script and not the files.

OUTPUT
    <dest>/<QUARTER>.zip and <dest>/<QUARTER>_d/  (extracted tables)
    Default dest is data/raw/form_d/, which is gitignored.

WHAT FORM D IS, AND WHAT IT IS NOT
    Form D is a notice of an exempt securities offering filed with the SEC.
    It is dated, which is what makes it usable as follow-on financing evidence
    on a timeline.

    It is NOT a complete record of venture funding:
      - US exempt offerings only;
      - some rounds are never filed, or are filed late;
      - the amount fields are offering amounts, not necessarily amounts raised;
      - a missing filing means NO EVIDENCE, never zero funding.

    See docs/research_log/2026-10-29_w24_backtest_design.md section 9.

ENTITY RESOLUTION WARNING
    Matching Form D filers to YC companies by name is the hard part and the
    main source of error. Use src/entity_resolution/normalize.py, which strips
    LEGAL SUFFIXES ONLY. An earlier version stripped generic tokens too, turning
    "Pax Labs" into "pax" and matching YC's unrelated "Pax" to Pax Labs /
    JUUL Labs at a filing value of about $1.98B. Require a single candidate and
    leave ambiguous matches unresolved.

USAGE
    python src/outcome_tracking/fetch_sec_form_d.py
    python src/outcome_tracking/fetch_sec_form_d.py --quarters 2024q1 2024q2
"""

import argparse
import os
import time
import urllib.request
import zipfile

# The SEC requires a descriptive User-Agent with contact information on
# automated requests. Replace with your own before running.
USER_AGENT = "Columbia IEOR4511 research (contact: your-email@columbia.edu)"

BASE = "https://www.sec.gov/files/dera/data/form-d-data-sets/%s_d.zip"

DEFAULT_QUARTERS = ["2024q1", "2024q2", "2024q3", "2024q4",
                    "2025q1", "2025q2", "2025q3", "2025q4",
                    "2026q1", "2026q2", "2026q3"]


def download(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest_path, "wb") as fh:
        fh.write(resp.read())
    return os.path.getsize(dest_path)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--dest", default=os.path.join("data", "raw", "form_d"))
    p.add_argument("--quarters", nargs="*", default=DEFAULT_QUARTERS)
    p.add_argument("--no-extract", action="store_true")
    args = p.parse_args()

    os.makedirs(args.dest, exist_ok=True)
    for q in args.quarters:
        url = BASE % q.upper()
        zip_path = os.path.join(args.dest, "%s.zip" % q)
        if os.path.exists(zip_path):
            print("%s  already present, skipped" % q)
        else:
            try:
                size = download(url, zip_path)
                print("%s  %.1f MB" % (q, size / 1e6))
            except Exception as e:
                # A quarter that has not been published yet returns 403/404.
                print("%s  FAILED (%s) - quarter may not be published yet" % (q, e))
                continue
            time.sleep(1.0)  # be polite to sec.gov

        if not args.no_extract:
            out_dir = os.path.join(args.dest, "%s_d" % q)
            if not os.path.isdir(out_dir):
                try:
                    with zipfile.ZipFile(zip_path) as z:
                        z.extractall(out_dir)
                    print("      extracted -> %s" % out_dir)
                except Exception as e:
                    print("      extract FAILED (%s)" % e)

    print("\nNOTE: a company absent from these filings has NO FUNDING EVIDENCE "
          "here. That is not the same as zero funding.")


if __name__ == "__main__":
    main()
