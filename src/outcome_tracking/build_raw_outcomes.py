# -*- coding: utf-8 -*-
"""Build the raw 24-month outcome dataset for the 240-company W24 cohort.

PURPOSE
    Record Y for each company in the dated 2024-03-25 cohort, keeping the raw
    outcome dimensions SEPARATE. This script deliberately produces no
    success/failure label and no weighted composite score.

    Decision point t = 2024-04-03/04. Primary outcome cutoff = 2026-04-04.

INPUTS
    data/processed/w24_spreadsheet_2024-03-25.csv   the 240-company cohort
    data/processed/w24_crosswalk.csv                cohort -> current records
    data/processed/yc2024_monthly.csv               monthly panel
    data/metadata/manual_outcome_evidence.csv       hand-verified items
    --form-d DIR  SEC Form D quarterly extracts (fetch_sec_form_d.py)
    live yc-oss batches/winter-2024.json            former_names

OUTPUT
    data/processed/w24_raw_outcomes_24m.csv  240 rows, one per cohort company,
    with survival / follow-on funding / acquisition / team growth / evidence
    quality recorded as independent dimensions.

TWO STRUCTURAL LIMITS, BOTH LOAD-BEARING
    1. AN 86-DAY BLIND WINDOW STRADDLES THE CUTOFF.
       yc-oss stopped updating between 2026-02-08 and 2026-05-04 because YC
       rotated the Algolia key its scraper depended on (upstream commit
       "Fix YC API fetcher by reading current Algolia key"). The 2026-04-04
       cutoff falls in the middle of that gap, so NO observation exists at the
       cutoff. Status changes inside the window cannot be dated relative to it;
       those companies are flagged  and
       must be treated as uncertain, not resolved by assumption.

    2. SLUG, DOMAIN AND NAME ARE ALL UNSTABLE.
       Adagy Robotics moved adagy-robotics -> tuesday-lab -> tuesday-labs and
       adagyrobotics.com -> tuesdaylab.com. No single key tracks a company
       across snapshots, so panel records are linked into entity chains with a
       union-find over all three keys. Keying on the current slug alone loses
       ~18 companies silently.

INTERPRETATION RULES ENFORCED HERE
    Active is not success. Acquired is not a successful exit. Inactive is not
    total loss. No Form D match is ABSENCE OF EVIDENCE, never confirmed zero
    funding: Form D covers US exempt offerings only, and most early YC rounds
    rely on Section 4(a)(2) instead, so recall on this cohort is about 5%.
    Removal from the YC directory is not failure.

USAGE
    python src/outcome_tracking/build_raw_outcomes.py --form-d data/raw/form_d
"""
import csv, io, json, os, re, sys, time, urllib.request, datetime

import argparse

_p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
_p.add_argument("--repo", default=".", help="repository root (default: cwd)")
_p.add_argument("--form-d", default=os.path.join("data", "raw", "form_d"),
                help="directory holding the SEC Form D quarterly extracts")
_args = _p.parse_args()
REPO = _args.repo
FD = _args.form_d
sys.path.insert(0, os.path.join(REPO, "src"))
from entity_resolution.normalize import norm_name, norm_domain, yc_slug  # noqa

DEMO_DAY = "2024-04-04"
CUTOFF = "2026-04-04"
FIRST_SNAP = "2024-10-01"          # earliest post-Demo-Day observation available
LAST_PRE_CUTOFF_SNAP = "2026-02-08"  # last observation <= cutoff (upstream gap after)
FIRST_POST_GAP_SNAP = "2026-06-01"   # first observation in our panel after the gap

def say(*a):
    print(*a); sys.stdout.flush()

def jget(u, timeout=120, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(u, headers={"User-Agent": "columbia-ieor4511-research"})
            return json.loads(urllib.request.urlopen(r, timeout=timeout).read().decode())
        except Exception:
            if i == tries - 1: return None
            time.sleep(5 * (i + 1))

# ---------------------------------------------------------------- 1. cohort
say("1. building cohort from the dated 2024-03-25 spreadsheet ...")
sheet = list(csv.DictReader(io.open(os.path.join(REPO, "data/processed/w24_spreadsheet_2024-03-25.csv"),
                                    encoding="utf-8-sig")))
cross = {r["sheet_name"]: r for r in csv.DictReader(
    io.open(os.path.join(REPO, "data/processed/w24_crosswalk.csv"), encoding="utf-8-sig"))}

w24 = jget("https://yc-oss.github.io/api/batches/winter-2024.json") or []
meta = {c.get("slug"): c for c in w24}
say("   sheet %d / crosswalk %d / live W24 %d" % (len(sheet), len(cross), len(w24)))

# ------------------------------------------------------- 2. panel: survival + team
say("2. reading panel for survival and team size ...")
# slug, domain AND name are all unstable over time. Adagy Robotics went
# adagy-robotics -> tuesday-lab -> tuesday-labs and adagyrobotics.com ->
# tuesdaylab.com, so no single key tracks a company across snapshots. Records
# are therefore linked into entity chains with a union-find over all three keys.
prows = [r for r in csv.DictReader(io.open(os.path.join(REPO, "data/processed/yc2024_monthly.csv"),
                                           encoding="utf-8-sig")) if r["batch"] == "winter-2024"]

parent = {}
def find(x):
    parent.setdefault(x, x)
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: parent[ra] = rb

def keys_of(slug, website, name):
    ks = []
    if slug: ks.append("slug:" + slug)
    d = norm_domain(website)
    if d: ks.append("dom:" + d)
    n = norm_name(name)
    if n: ks.append("nm:" + n)
    return ks

for r in prows:
    ks = keys_of(r["slug"], r.get("website"), r.get("name"))
    for k in ks[1:]: union(ks[0], k)

chain = {}   # component root -> {snapshot: [rows]}
for r in prows:
    ks = keys_of(r["slug"], r.get("website"), r.get("name"))
    if not ks: continue
    chain.setdefault(find(ks[0]), {}).setdefault(r["snapshot"], []).append(r)

over_merged = {root: mx for root, h in chain.items()
               if (mx := max(len(v) for v in h.values())) > 1}
say("   %d panel rows -> %d entity chains (%d chains hold >1 record in some "
    "snapshot and are flagged)" % (len(prows), len(chain), len(over_merged)))

def chain_for(cands):
    """cands: (slug, website, name) in DESCENDING key strength. Returns (history, roots, skipped).

    Every candidate key is tried and the chains they hit are merged, because a
    rename can change slug, domain and name at once. No single panel row then
    carries a key from both identities, so the union-find cannot bridge the
    rename by itself: Adagy Robotics went
    adagy-robotics / adagyrobotics.com / "Adagy Robotics" ->
    tuesday-labs / tuesdaylab.com / "Tuesday Labs" with no overlap at all.
    Returning on the first hit found only the post-rename fragment and silently
    lost every pre-cutoff observation for 15 companies.

    The bridge is yc-oss `former_names`, passed in as a weak candidate - but a
    former name can collide with a DIFFERENT company's current name, which
    merged Ecliptor with Hatchet, Forge Rewards with Forge, and Lumona with
    Scout. A chain is therefore only merged in if it does not put two records
    in the same snapshot; a collision means two companies, so the weaker
    candidate is REFUSED and reported rather than silently joined.
    """
    merged, roots, skipped = {}, [], []
    for slug, web, nm in cands:
        for k in keys_of(slug, web, nm):
            if k not in parent:
                continue
            root = find(k)
            if root not in chain or root in roots:
                continue
            clash = sorted(sn for sn, rs in chain[root].items()
                           if sn in merged and (len(merged[sn]) + len(rs)) > 1)
            if clash and roots:
                skipped.append("%s via %s (snapshot clash %s)" % (root, k, clash[0]))
                continue
            for sn, rs in chain[root].items():
                merged.setdefault(sn, []).extend(rs)
            roots.append(root)
    return merged, roots, skipped


def team_of(row):
    """team_size as int, or None. Missing stays None and is never imputed as 0."""
    if not row:
        return None
    v = (row.get("team_size") or "").strip()
    if v in ("", "None", "null"):
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


# ------------------------------------------------------------- 3. SEC Form D
say("3. indexing SEC Form D filings ...")
# quarters covering filings strictly after Demo Day and up to/just past the cutoff
QUARTERS = ["2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2",
            "2025Q3", "2025Q4", "2026Q1", "2026Q2"]

def read_tsv(path):
    with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
        rdr = csv.DictReader(fh, delimiter="\t")
        for row in rdr:
            yield row

filings = {}        # accession -> {filing_date, submission_type}
offerings = {}      # accession -> offering row
fd_by_name = {}     # normalised issuer name -> [accession, ...]
fd_issuer = {}      # accession -> issuer row
n_sub = 0
for q in QUARTERS:
    d = os.path.join(FD, q + "_d")
    if not os.path.isdir(d):
        say("   MISSING quarter %s - skipped" % q); continue
    for row in read_tsv(os.path.join(d, "FORMDSUBMISSION.tsv")):
        acc = row.get("ACCESSIONNUMBER")
        if not acc: continue
        filings[acc] = {"filing_date": (row.get("FILING_DATE") or "").strip(),
                        "submission_type": (row.get("SUBMISSIONTYPE") or "").strip()}
        n_sub += 1
    for row in read_tsv(os.path.join(d, "OFFERING.tsv")):
        acc = row.get("ACCESSIONNUMBER")
        if acc: offerings[acc] = row
    for row in read_tsv(os.path.join(d, "ISSUERS.tsv")):
        acc = row.get("ACCESSIONNUMBER")
        if not acc: continue
        if (row.get("IS_PRIMARYISSUER_FLAG") or "").strip().upper() not in ("Y", "TRUE", "1", ""):
            pass  # keep non-primary issuers too; a company can be a co-issuer
        fd_issuer[acc] = row
        names = [row.get("ENTITYNAME")]
        for k in ("ISSUER_PREVIOUSNAME_1", "ISSUER_PREVIOUSNAME_2", "ISSUER_PREVIOUSNAME_3",
                  "EDGAR_PREVIOUSNAME_1", "EDGAR_PREVIOUSNAME_2", "EDGAR_PREVIOUSNAME_3"):
            names.append(row.get(k))
        for nm in names:
            key = norm_name(nm)
            if key:
                fd_by_name.setdefault(key, []).append(acc)
say("   %d submissions, %d offerings, %d distinct normalised issuer names"
    % (n_sub, len(offerings), len(fd_by_name)))


def fd_date(acc):
    raw = filings.get(acc, {}).get("filing_date", "")
    # SEC uses DD-MON-YYYY in these datasets
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try: return datetime.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except Exception: continue
    return ""


def money(v):
    v = (v or "").strip()
    if v in ("", "0") or not v.replace(".", "").isdigit():
        return v if v and v != "0" else ""
    return v


def offering_type(acc):
    o = offerings.get(acc, {})
    flags = []
    for key, label in (("ISEQUITYTYPE", "equity"), ("ISDEBTTYPE", "debt"),
                       ("ISOPTIONTOACQUIRETYPE", "option"), ("ISOTHERTYPE", "other"),
                       ("ISPOOLEDINVESTMENTFUNDTYPE", "pooled_fund")):
        if (o.get(key) or "").strip().lower() in ("true", "y", "1"):
            flags.append(label)
    return "|".join(flags)


GENERIC = set("""sample tower polished raindrop whip ryse abel spark pax verse triply
mathos panelytic downlink""".split())


def match_form_d(names, location):
    """Return (matched_accessions, method, ambiguity_note).

    Exact normalised-name match only. No fuzzy matching. A generic single-word
    name is flagged because Form D has no domain to disambiguate on.
    """
    for which, nm in names:
        key = norm_name(nm)
        if not key:
            continue
        accs = fd_by_name.get(key)
        if not accs:
            continue
        note = ""
        if len(key.split()) == 1 and key in GENERIC:
            note = "generic single-word name; Form D has no domain to verify on"
        # location plausibility: US state/country code vs the 2024-03-25 location
        st = {(fd_issuer.get(a, {}).get("STATEORCOUNTRY") or "").strip() for a in accs}
        loc = (location or "").upper()
        m = re.search(r",\s*([A-Z]{2}),", loc)
        if m and st and m.group(1) not in st:
            note = (note + "; " if note else "") + \
                   "issuer state %s differs from cohort location %s" % ("/".join(sorted(st)), m.group(1))
        return accs, which, note
    return [], "", ""


# ------------------------------------------------------------- 4. build rows
say("4. assembling company-level raw outcomes ...")
COLS = [
    # identity
    "entity_id", "name_at_decision", "current_name", "former_names",
    "domain_at_decision", "current_domain", "renamed_since_decision",
    "in_yc_directory_at_cutoff",
    # survival
    "survival_at_cutoff_2026_04_04", "endpoint_status",
    "survival_last_pre_cutoff_status", "survival_last_pre_cutoff_date",
    "survival_first_post_cutoff_status", "survival_first_post_cutoff_date",
    "survival_evidence_source", "survival_blind_window", "missingness_reason",
    # follow-on funding
    "funding_dimension_status", "funding_role_in_primary_Y",
    "followon_funding_evidence", "funding_first_date", "funding_type",
    "funding_amount_sold", "funding_amount_offered", "funding_filings_count",
    "funding_source", "funding_match_name_used", "funding_match_caveat",
    "funding_post_cutoff_evidence",
    # acquisition
    "acquired_by_cutoff", "acquisition_detected_between", "acquisition_detected_at",
    "acquirer", "acquisition_amount", "acquisition_source",
    "acquisition_post_cutoff",
    # team growth
    "team_size_first_obs", "team_size_first_obs_date",
    "team_size_last_obs_pre_cutoff", "team_size_last_obs_date",
    "team_growth_abs", "team_growth_pct", "team_obs_note",
    # evidence quality
    "outcome_evidence_confidence", "outcome_sources", "outcome_notes_conflicts",
]

rows = []
for s in sheet:
    sheet_name = s.get("Company Name", "")
    xw = cross.get(sheet_name, {})
    slug = xw.get("matched_slug") or ""
    m = meta.get(slug, {})
    # strongest keys first: identifiers we can verify, then names, then the
    # weak former-name bridge which is the one that can collide across companies
    cands = [(slug, m.get("website"), ""),
             (yc_slug(s.get("YC Link", "")), s.get("Company Website"), ""),
             ("", "", (m.get("name") or xw.get("matched_name") or "")),
             ("", "", sheet_name)]
    for f in (m.get("former_names") or []):
        cands.append(("", "", f))
    hist_rows, chain_roots, chain_skipped = chain_for(cands)
    hist = {snap: rs[0] for snap, rs in hist_rows.items()}
    # more than one record in a snapshot after merging means the candidate keys
    # pulled in two different companies; surfaced rather than silently resolved
    multi_snap = sorted(snap for snap, rs in hist_rows.items() if len(rs) > 1)

    former = "|".join(m.get("former_names") or [])
    cur_name = m.get("name") or xw.get("matched_name") or ""
    in_dir = "TRUE" if slug else "FALSE"

    # ---- survival
    # The 2026-04-04 endpoint is NOT observable: yc-oss stopped updating from
    # 2026-02-08 to 2026-05-04. Both the last pre-cutoff and the first
    # post-cutoff observation are therefore preserved with their own dates, and
    # neither is substituted for the endpoint. Where they disagree the company
    # is ENDPOINT_UNCERTAIN and the transition is deliberately NOT placed on
    # either side of the cutoff.
    pre_snaps = sorted(sn for sn in hist if sn <= CUTOFF)
    post_snaps = sorted(sn for sn in hist if sn > CUTOFF)
    r_pre = hist.get(pre_snaps[-1]) if pre_snaps else None
    r_post = hist.get(post_snaps[0]) if post_snaps else None
    sources, notes = [], []

    pre_status = (r_pre or {}).get("status", "") or ""
    pre_date = pre_snaps[-1] if (pre_snaps and pre_status) else ""
    post_status = (r_post or {}).get("status", "") or ""
    post_date = post_snaps[0] if (post_snaps and post_status) else ""
    if pre_status:
        sources.append("yc-oss panel")

    missingness = ""
    if not pre_status:
        if not slug:
            missingness = "PRE_YCOSS_DIRECTORY_DISAPPEARANCE"
            notes.append("absent from the YC directory before the panel begins (%s); no "
                         "yc-oss observation exists. Missingness is structural and may be "
                         "non-random. NOT to be read as failure." % FIRST_SNAP)
        else:
            missingness = "NO_PRE_CUTOFF_PANEL_RECORD"
            notes.append("matched to a current record but no panel observation at or "
                         "before the cutoff")

    # endpoint resolution
    if not pre_status:
        endpoint_status = "NO_OBSERVATION"
        surv_at_cutoff = "UNKNOWN"
    elif post_status and post_status != pre_status:
        endpoint_status = "ENDPOINT_UNCERTAIN"
        surv_at_cutoff = "UNCERTAIN"
        notes.append("status differs across the blind window: %s @%s -> %s @%s. The "
                     "transition is NOT dated relative to %s; it may fall on either side."
                     % (pre_status, pre_date, post_status, post_date, CUTOFF))
    else:
        endpoint_status = "OK"
        surv_at_cutoff = pre_status

    # kept for continuity with the earlier table
    surv = pre_status or "Unknown"
    surv_date = pre_date
    surv_src = ("yc-oss batches/winter-2024.json @ commit of %s" % pre_date) if pre_date else ""
    changed = {"ENDPOINT_UNCERTAIN": "TRUE", "OK": "FALSE"}.get(endpoint_status, "UNKNOWN")
    if endpoint_status == "OK" and not post_status:
        changed = "UNKNOWN"

    # ---- team growth
    r_first = hist.get(pre_snaps[0]) if pre_snaps else None
    t0, t1 = team_of(r_first), team_of(r_pre)
    t0_date = pre_snaps[0] if (pre_snaps and t0 is not None) else ""
    t1_date = pre_snaps[-1] if (pre_snaps and t1 is not None) else ""
    g_abs = g_pct = ""
    tnote = []
    if t0 is None or t1 is None:
        tnote.append("missing team-size observation; left blank, NOT imputed as zero")
    else:
        g_abs = t1 - t0
        if t0 > 0:
            g_pct = round(100.0 * (t1 - t0) / t0, 1)
        else:
            tnote.append("baseline team size is 0; percentage growth undefined")
    if t0_date:
        tnote.append("window %s..%s; first observation is AFTER Demo Day, so this is "
                     "not the full 24 months" % (t0_date, t1_date or "-"))

    # ---- acquisition (from the panel's dated status history)
    acq, acq_between, acq_at, acq_post = "NO_EVIDENCE", "", "", ""
    snaps = sorted(hist.keys())
    for a, b in zip(snaps, snaps[1:]):
        if hist[a].get("status") != "Acquired" and hist[b].get("status") == "Acquired":
            if b <= CUTOFF:
                acq, acq_between, acq_at = "YES", a, b
            else:
                acq_post = "detected between %s and %s, AFTER cutoff" % (a, b)
            break
    if acq == "YES":
        sources.append("yc-oss status transition")
    if not pre_status:
        acq = "UNKNOWN"
    # Acquisition stays a RAW EVENT INDICATOR. With 0 named acquirers and 0
    # disclosed amounts anywhere in this cohort there is no return information,
    # so it must not be read as a successful exit.

    # ---- follow-on funding (SEC Form D)
    name_candidates = [("current_name", cur_name), ("name_at_decision", sheet_name)]
    for f in (m.get("former_names") or []):
        name_candidates.append(("former_name", f))
    accs, method, caveat = match_form_d(name_candidates, s.get("Location", ""))

    in_window, post_window = [], []
    for a in accs:
        d = fd_date(a)
        if not d:
            continue
        if DEMO_DAY < d <= CUTOFF:
            in_window.append((d, a))
        elif d > CUTOFF:
            post_window.append((d, a))
    in_window.sort(); post_window.sort()

    if in_window:
        d0, a0 = in_window[0]
        fund_ev = "FOUND"
        fund_date, fund_type = d0, offering_type(a0)
        fund_sold = money(offerings.get(a0, {}).get("TOTALAMOUNTSOLD"))
        fund_off = money(offerings.get(a0, {}).get("TOTALOFFERINGAMOUNT"))
        fund_n = len(in_window)
        fund_src = "SEC Form D accession %s" % a0
        sources.append("SEC Form D")
    else:
        fund_ev = "NO_EVIDENCE_FOUND"
        fund_date = fund_type = fund_sold = fund_off = fund_src = ""
        fund_n = 0
        notes.append("no Form D filing matched. Form D covers US exempt offerings only "
                     "and most early YC rounds are SAFEs under Section 4(a)(2), which "
                     "requires no filing, so recall is ~5%: this is ABSENCE OF EVIDENCE, "
                     "NOT confirmed zero funding. The funding dimension is "
                     "PENDING_BETTER_DATA_SOURCE and must not enter primary Y.")

    # ---- cross-dimension consistency checks
    if chain_skipped:
        notes.append("refused to merge %d chain(s) that would have put two companies in "
                     "one snapshot: %s" % (len(chain_skipped), "; ".join(chain_skipped[:2])))
    if multi_snap:
        notes.append("entity chain STILL holds >1 panel record in snapshot(s) %s after the "
                     "collision guard - verify manually" % ",".join(multi_snap[:3]))
    if fund_ev == "FOUND" and surv == "Inactive":
        # a company observed Inactive cannot plausibly file a new offering later
        inactive_from = ""
        sn = sorted(hist.keys())
        for a, b in zip(sn, sn[1:]):
            if hist[a].get("status") != "Inactive" and hist[b].get("status") == "Inactive":
                inactive_from = b; break
        if inactive_from and fund_date and fund_date > inactive_from:
            caveat = (caveat + "; " if caveat else "") +                      ("CONFLICT: observed Inactive by %s but a matched Form D filing is "
                      "dated %s - most likely a different company with the same name"
                      % (inactive_from, fund_date))
            notes.append("funding match conflicts with survival status; treat funding as UNVERIFIED")

    # ---- evidence quality
    distinct = len(set(sources))
    if surv == "Unknown":
        conf = "Low"
    elif distinct >= 2 and changed == "FALSE":
        conf = "High"
    elif changed == "TRUE" or caveat:
        conf = "Low"
    else:
        conf = "Medium"

    rows.append({
        "entity_id": slug or ("RM-" + yc_slug(s.get("YC Link", ""))),
        "name_at_decision": sheet_name,
        "current_name": cur_name,
        "former_names": former,
        "domain_at_decision": norm_domain(s.get("Company Website")),
        "current_domain": norm_domain(m.get("website")),
        "renamed_since_decision": xw.get("renamed", ""),
        "in_yc_directory_at_cutoff": in_dir,
        "survival_at_cutoff_2026_04_04": surv_at_cutoff,
        "endpoint_status": endpoint_status,
        "survival_last_pre_cutoff_status": pre_status,
        "survival_last_pre_cutoff_date": pre_date,
        "survival_first_post_cutoff_status": post_status,
        "survival_first_post_cutoff_date": post_date,
        "survival_evidence_source": surv_src,
        "missingness_reason": missingness,
        "survival_blind_window": "2026-02-08..2026-05-04 (86d, upstream scraper broken)",
        "funding_dimension_status": "PENDING_BETTER_DATA_SOURCE",
        "funding_role_in_primary_Y": "SUPPLEMENTARY_VALIDATION_ONLY",
        "followon_funding_evidence": fund_ev,
        "funding_first_date": fund_date,
        "funding_type": fund_type,
        "funding_amount_sold": fund_sold,
        "funding_amount_offered": fund_off,
        "funding_filings_count": fund_n,
        "funding_source": fund_src,
        "funding_match_name_used": method,
        "funding_match_caveat": caveat,
        "funding_post_cutoff_evidence": ("%d filing(s) after cutoff, earliest %s"
                                         % (len(post_window), post_window[0][0])) if post_window else "",
        "acquired_by_cutoff": acq,
        "acquisition_detected_between": acq_between,
        "acquisition_detected_at": acq_at,
        "acquirer": "",
        "acquisition_amount": "",
        "acquisition_source": "yc-oss status transition" if acq == "YES" else "",
        "acquisition_post_cutoff": acq_post,
        "team_size_first_obs": "" if t0 is None else t0,
        "team_size_first_obs_date": t0_date,
        "team_size_last_obs_pre_cutoff": "" if t1 is None else t1,
        "team_size_last_obs_date": t1_date,
        "team_growth_abs": g_abs,
        "team_growth_pct": g_pct,
        "team_obs_note": " / ".join(tnote),
        "outcome_evidence_confidence": conf,
        "outcome_sources": "; ".join(sorted(set(sources))),
        "outcome_notes_conflicts": " / ".join(notes),
    })

# ---- apply hand-verified evidence from a reproducible side file -------------
man_path = os.path.join(REPO, "data/metadata/manual_outcome_evidence.csv")
if os.path.exists(man_path):
    man = {}
    for mr in csv.DictReader(io.open(man_path, encoding="utf-8-sig")):
        man.setdefault(norm_name(mr["match_name"]), []).append(mr)
    applied = 0
    for r in rows:
        for nm in (r["name_at_decision"], r["current_name"]):
            for mr in man.get(norm_name(nm), []):
                fld = mr["field"]
                if fld in r:
                    r[fld] = mr["value"]
                else:
                    r["outcome_notes_conflicts"] = (
                        (r["outcome_notes_conflicts"] + " / ") if r["outcome_notes_conflicts"] else ""
                    ) + "%s=%s [%s; %s] %s" % (fld, mr["value"], mr["source"],
                                               mr["confidence"], mr["note"])
                src = r["outcome_sources"]
                if "manual verification" not in src:
                    r["outcome_sources"] = (src + "; " if src else "") + "manual verification"
                applied += 1
            if man.get(norm_name(nm)): break
    say("   applied %d hand-verified evidence items" % applied)

out = os.path.join(REPO, "data/processed/w24_raw_outcomes_24m.csv")
with io.open(out, "w", newline="", encoding="utf-8-sig") as fh:
    w = csv.DictWriter(fh, fieldnames=COLS); w.writeheader(); w.writerows(rows)
say("\nwrote %s  (%d rows)" % (out, len(rows)))

# ------------------------------------------- 4b. uncertainty-set exports
def dump(path, subset, cols, note):
    with io.open(os.path.join(REPO, path), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in subset:
            w.writerow({c: r.get(c, "") for c in cols})
    say("   wrote %s  (%d rows) - %s" % (path, len(subset), note))

ID = ["entity_id", "name_at_decision", "current_name", "former_names",
      "domain_at_decision", "current_domain", "renamed_since_decision"]

miss19 = [r for r in rows if r["missingness_reason"] == "PRE_YCOSS_DIRECTORY_DISAPPEARANCE"]
dump("data/processed/w24_pre_panel_missing.csv", miss19,
     ID + ["missingness_reason", "in_yc_directory_at_cutoff", "outcome_notes_conflicts"],
     "for external/manual outcome research; NOT to be read as failures")

# Absent from the CURRENT directory is a different, larger set than never
# observed: 15 of these were observed while still listed and only disappeared
# later, so their last observed status is real data. Exported separately so the
# survivorship question can be examined without conflating the two.
gone = [r for r in rows if r["in_yc_directory_at_cutoff"] == "FALSE"]
dump("data/processed/w24_directory_disappearance.csv", gone,
     ID + ["missingness_reason", "survival_at_cutoff_2026_04_04", "endpoint_status",
           "survival_last_pre_cutoff_status", "survival_last_pre_cutoff_date",
           "team_size_first_obs", "team_size_last_obs_pre_cutoff"],
     "absent from the current YC directory; disappearance is NOT failure")

unc8 = [r for r in rows if r["endpoint_status"] == "ENDPOINT_UNCERTAIN"]
dump("data/processed/w24_endpoint_uncertain.csv", unc8,
     ID + ["survival_last_pre_cutoff_status", "survival_last_pre_cutoff_date",
           "survival_first_post_cutoff_status", "survival_first_post_cutoff_date",
           "survival_blind_window", "acquisition_post_cutoff"],
     "transition undatable against the 2026-04-04 cutoff")

# --------------------------------------------------------- 5. coverage summary
def pct(n): return "%.1f%%" % (100.0 * n / len(rows))
say("\n==================== COVERAGE ====================")
say("cohort: %d companies (2024-03-25 dated spreadsheet)" % len(rows))
say("\n-- survival --")
for k in ("Active", "Inactive", "Acquired", "UNCERTAIN", "UNKNOWN"):
    n = sum(1 for r in rows if r["survival_at_cutoff_2026_04_04"] == k)
    if n: say("   %-10s %4d  %s" % (k, n, pct(n)))
known = sum(1 for r in rows if r["survival_at_cutoff_2026_04_04"]
            not in ("UNKNOWN", "UNCERTAIN"))
ch = sum(1 for r in rows if r["endpoint_status"] == "ENDPOINT_UNCERTAIN")
say("   resolved at the 2026-04-04 endpoint: %d/%d  %s" % (known, len(rows), pct(known)))
say("   ENDPOINT_UNCERTAIN (differ across the 86-day blind window): %d" % ch)
say("   PRE_YCOSS_DIRECTORY_DISAPPEARANCE: %d"
    % sum(1 for r in rows if r["missingness_reason"] == "PRE_YCOSS_DIRECTORY_DISAPPEARANCE"))
say("\n-- follow-on funding (SEC Form D) --")
f = sum(1 for r in rows if r["followon_funding_evidence"] == "FOUND")
say("   evidence found: %d/%d  %s" % (f, len(rows), pct(f)))
say("   no evidence found: %d  (= absence of evidence, NOT zero funding)" % (len(rows) - f))
cav = sum(1 for r in rows if r["funding_match_caveat"])
say("   matched but with a caveat: %d" % cav)
amt = sum(1 for r in rows if r["funding_amount_sold"])
say("   with a disclosed amount sold: %d" % amt)
say("\n-- acquisition --")
for k in ("YES", "NO_EVIDENCE", "UNKNOWN"):
    n = sum(1 for r in rows if r["acquired_by_cutoff"] == k)
    if n: say("   %-12s %4d  %s" % (k, n, pct(n)))
named = sum(1 for r in rows if r["acquirer"] and r["acquirer"] != "NOT_DISCLOSED")
nd = sum(1 for r in rows if r["acquirer"] == "NOT_DISCLOSED")
say("   acquirer NAMED: %d / checked and NOT_DISCLOSED: %d / not looked up: %d"
    % (named, nd, sum(1 for r in rows if r["acquired_by_cutoff"] == "YES") - named - nd))
namt = sum(1 for r in rows if r["acquisition_amount"] and r["acquisition_amount"] != "NOT_DISCLOSED")
say("   transaction amount DISCLOSED: %d" % namt)
pa = sum(1 for r in rows if r["acquisition_post_cutoff"])
say("   acquired AFTER cutoff (held separately): %d" % pa)
say("\n-- team size --")
b = sum(1 for r in rows if r["team_size_first_obs"] != "" and r["team_size_last_obs_pre_cutoff"] != "")
say("   both observations present: %d/%d  %s" % (b, len(rows), pct(b)))
say("   first obs only: %d / last obs only: %d / neither: %d"
    % (sum(1 for r in rows if r["team_size_first_obs"] != "" and r["team_size_last_obs_pre_cutoff"] == ""),
       sum(1 for r in rows if r["team_size_first_obs"] == "" and r["team_size_last_obs_pre_cutoff"] != ""),
       sum(1 for r in rows if r["team_size_first_obs"] == "" and r["team_size_last_obs_pre_cutoff"] == "")))
say("   percentage growth computable: %d" % sum(1 for r in rows if r["team_growth_pct"] != ""))
say("\n-- evidence quality --")
for k in ("High", "Medium", "Low"):
    n = sum(1 for r in rows if r["outcome_evidence_confidence"] == k)
    say("   %-7s %4d  %s" % (k, n, pct(n)))
say("\n-- conflicts / uncertain --")
say("   ENDPOINT_UNCERTAIN: %d" % ch)
say("   funding match caveat: %d" % cav)
say("   renamed since decision: %d" % sum(1 for r in rows if r["renamed_since_decision"] == "YES"))
say("   absent from current YC directory: %d"
    % sum(1 for r in rows if r["in_yc_directory_at_cutoff"] == "FALSE"))
