"""Shared normalisation helpers for matching companies across sources.

WHY THIS FILE EXISTS
    ~27% of current W24 companies have been renamed since 2024-03. Matching on
    raw company names silently fails for all of them, which is what initially
    understated spreadsheet coverage of the current W24 universe as 67.7% when
    the correct figure, after following `former_names`, is 89.1%.

    The opposite error is worse. An earlier version stripped generic tokens as
    well as legal suffixes, which turned "Pax Labs" into "pax" and matched YC's
    unrelated "Pax" to Pax Labs / JUUL Labs at a filing value of about $1.98B.
    One normalisation bug was enough to corrupt any funding-based outcome.

    Hence: strip LEGAL SUFFIXES ONLY. Never strip descriptive words such as
    Labs, AI, Technologies, Health, Robotics.

NO FUZZY MATCHING
    These helpers produce exact keys for exact comparison. Do not add edit
    distance or token-overlap matching here. Uncertain matches must stay
    separate and be reviewed by a human, not resolved by a threshold.
"""

import re
import urllib.parse

# Legal-entity suffixes only.
_LEGAL = (r"[ ,.]*\b("
          r"inc|incorporated|llc|l\.?l\.?c|corp|corporation|ltd|limited|co|"
          r"lp|llp|plc|gmbh|ab|oy|pte|pty"
          r")\b\.?")


def norm_name(s):
    """Lowercase, strip legal suffixes, collapse to single-spaced alphanumerics.

    >>> norm_name("Abel, Inc.")
    'abel'
    >>> norm_name("Pax Labs")       # 'Labs' is descriptive and must survive
    'pax labs'
    """
    s = (s or "").lower().strip()
    for _ in range(3):  # handles stacked suffixes, e.g. "Foo Co., Ltd."
        s = re.sub(_LEGAL, " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_domain(url):
    """Registrable host of a URL, lowercased, without a leading 'www.'.

    >>> norm_domain("https://www.TryAbel.com/pricing")
    'tryabel.com'
    """
    url = (url or "").strip()
    if not url:
        return ""
    if "//" not in url:
        url = "http://" + url
    host = urllib.parse.urlparse(url).netloc.lower()
    return re.sub(r"^www\.", "", host)


def yc_slug(url):
    """YC company slug from a ycombinator.com/companies/<slug> URL.

    >>> yc_slug("https://www.ycombinator.com/companies/adagy-robotics")
    'adagy-robotics'
    """
    m = re.search(r"/companies/([^/?#]+)", url or "")
    return m.group(1).lower() if m else ""


def build_indexes(companies):
    """Index a yc-oss company list by domain and by every known name.

    `former_names` are indexed alongside the current name, which is what makes
    renamed companies findable at all.

    Returns (by_domain, by_name) where each value is a LIST of candidates.
    Callers must require len(list) == 1 before accepting an automatic match.
    """
    by_domain, by_name = {}, {}
    for c in companies:
        d = norm_domain(c.get("website"))
        if d:
            by_domain.setdefault(d, []).append(c)
        by_name.setdefault(norm_name(c.get("name")), []).append(c)
        for former in (c.get("former_names") or []):
            by_name.setdefault(norm_name(former), []).append(c)
    return by_domain, by_name


if __name__ == "__main__":
    import doctest
    print(doctest.testmod())
