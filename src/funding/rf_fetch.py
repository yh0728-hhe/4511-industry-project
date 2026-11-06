# -*- coding: utf-8 -*-
"""Minimal cached RecentFunding fetcher. One call per NEW path, never a repeat.

WHY A SEPARATE SMALL TOOL
    The free key now allows only 10 calls a day (cut from 100 on 2026-10-30),
    so every call has to count. This caches to the same directory and with the
    same key scheme the original benchmark used, so a cached response is never
    re-fetched and the two runs share one cache.

    `/usage` is exempt: the API documents it as not counting against limits.

The key is read from the gitignored .env and is never printed or logged.
"""

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://recentfunding.com/api/v1"
CACHE = os.path.join("data", "interim", "funding_source_benchmark", "raw_recentfunding")
UA = "columbia-ieor4511-academic-research"


def read_key(repo):
    path = os.path.join(repo, ".env")
    if not os.path.exists(path):
        raise SystemExit(".env not found; the key must live there (gitignored)")
    for line in io.open(path, encoding="utf-8"):
        if line.startswith("RECENTFUNDING_API_KEY="):
            k = line.split("=", 1)[1].strip()
            if k:
                return k
    raise SystemExit("RECENTFUNDING_API_KEY not set in .env")


def fetch(repo, path, params=None, tag=None, force=False):
    """Returns (data, spent_a_call). Cached responses spend nothing."""
    cache_dir = os.path.join(repo, CACHE)
    os.makedirs(cache_dir, exist_ok=True)
    cpath = os.path.join(cache_dir, "rf_%s.json" % tag) if tag else None
    if cpath and os.path.exists(cpath) and not force:
        return json.load(io.open(cpath, encoding="utf-8")), False

    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + read_key(repo),
        "Accept": "application/json",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            body, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        body, code = e.read(), e.code
    if code != 200:
        txt = body.decode("utf-8", "replace")[:300]
        raise SystemExit("HTTP %s for %s\n%s" % (code, path, txt))
    data = json.loads(body.decode("utf-8"))
    if cpath:
        io.open(cpath, "w", encoding="utf-8").write(
            json.dumps(data, ensure_ascii=False, indent=1))
    return data, True


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--path", required=True, help="e.g. /usage or /companies")
    ap.add_argument("--param", action="append", default=[], help="k=v, repeatable")
    ap.add_argument("--tag", default="", help="cache tag; omit to skip caching")
    ap.add_argument("--show", default="", help="top-level key to pretty-print")
    args = ap.parse_args()

    params = {}
    for p in args.param:
        k, _, v = p.partition("=")
        params[k] = v
    data, spent = fetch(os.path.abspath(args.repo), args.path, params or None,
                        args.tag or None)
    print("path=%s spent_a_call=%s top_keys=%s"
          % (args.path, spent, list(data.keys())))
    if args.show:
        print(json.dumps(data.get(args.show), ensure_ascii=False, indent=1)[:2500])
    else:
        print(json.dumps(data, ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
