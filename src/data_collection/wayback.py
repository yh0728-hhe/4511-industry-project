"""Wayback Machine CDX helpers with explicit failure reporting.

THE BUG THIS FILE EXISTS TO PREVENT
    A naive CDX wrapper returns [] both when a URL genuinely has no captures
    and when the query itself failed (rate limit, timeout, bad JSON). Those two
    cases mean opposite things:

        no captures  -> we looked, and the archive has nothing
        query failed -> we do not know anything

    Collapsing them writes "no historical evidence" into the dataset for
    companies we simply failed to query. In one run this turned PandasAI and
    Raindrop into "no evidence" rows even though a previous successful query
    had found 11 and 4 pre-cutoff captures respectively. It raises no error.

    Therefore every function here returns (result, status) and the caller must
    branch on status. `QUERY_FAILED` must never be recorded as absence.

AND THE RULE THAT GOVERNS THE OUTPUT
    Absence of an archived capture is NOT evidence that a company did not exist
    or was not in the batch. Wayback coverage is a property of the Internet
    Archive's crawl schedule, not of the company. See
    docs/research_log/2026-10-29_w24_backtest_design.md section 3.
"""

import gzip
import json
import time
import urllib.parse
import urllib.request

USER_AGENT = "columbia-ieor4511-research"

OK = "OK"


class FetchFailed(Exception):
    """Raised after all retries are exhausted. Never swallow into an empty result."""


def fetch(url, tries=5, timeout=70, backoff=6):
    """GET a URL as text, with exponential backoff. Raises FetchFailed.

    `Accept-Encoding: identity` is deliberate: Wayback will otherwise return
    gzip/brotli bodies that decode to mojibake if handled naively. gzip is
    still unwrapped defensively below because the header is advisory.
    """
    last = None
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "identity"})
            raw = urllib.request.urlopen(r, timeout=timeout).read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("latin-1")
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(backoff * (i + 1))
    raise FetchFailed("%s: %s" % (type(last).__name__, last))


def cdx_captures(url_pattern, to_timestamp, match_type=None, limit=500):
    """Captures of `url_pattern` at or before `to_timestamp` (YYYYMMDDhhmmss).

    Returns (captures, status). Each capture is [timestamp, original, statuscode].
    status is OK or "QUERY_FAILED(...)". An empty list with status OK means the
    archive really has nothing; an empty list with QUERY_FAILED means unknown.

    `match_type="prefix"` also matches sub-paths, which finds captures that an
    exact-URL query misses. Querying both the bare host and the "www." form is
    worth it: that alone surfaced three additional YC page archives.
    """
    q = {"url": url_pattern, "output": "json",
         "fl": "timestamp,original,statuscode",
         "to": to_timestamp, "collapse": "timestamp:8", "limit": str(limit)}
    if match_type:
        q["matchType"] = match_type
    try:
        txt = fetch("https://web.archive.org/cdx/search/cdx?" + urllib.parse.urlencode(q))
    except FetchFailed as e:
        return [], "QUERY_FAILED(%s)" % e
    if not txt.strip():
        return [], OK
    try:
        rows = json.loads(txt)
    except ValueError:
        return [], "QUERY_FAILED(bad json)"
    if rows and rows[0] and rows[0][0] == "timestamp":
        rows = rows[1:]
    return [r for r in rows if r and r[0] <= to_timestamp], OK


def snapshot_text(timestamp, url):
    """Raw archived body at a timestamp, via the `id_` (unrewritten) endpoint.

    Returns (text, status). `id_` is important: without it Wayback injects its
    own banner and rewrites links, which pollutes any string test run on the
    body (for example a test for the literal token "W24").
    """
    try:
        return fetch("https://web.archive.org/web/%sid_/%s" % (timestamp, url)), OK
    except FetchFailed as e:
        return None, "QUERY_FAILED(%s)" % e


def ts_to_date(ts):
    """'20240404123000' -> '2024-04-04'."""
    return "%s-%s-%s" % (ts[:4], ts[4:6], ts[6:8])
