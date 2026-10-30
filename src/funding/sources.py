# -*- coding: utf-8 -*-
"""Clients for the candidate funding sources, with explicit match statuses.

THE STATUS TAXONOMY IS THE POINT OF THIS FILE
    "No funding event returned" and "no funding occurred" are different claims,
    and a benchmark that collapses them manufactures negative labels out of
    missing data. Every lookup therefore returns one of:

        FUNDING_EVENT_FOUND           events inside the window were returned
        COMPANY_FOUND_NO_EVENT_RETURNED   the company resolved, no events
        COMPANY_NOT_FOUND             no candidate identifier resolved
        AMBIGUOUS_MATCH               several companies matched; NOT resolved
        SOURCE_QUERY_FAILED           the request failed; we know nothing

    SOURCE_QUERY_FAILED must never be reported as absence of funding.

CREDENTIALS
    Keys are read from the environment (RECENTFUNDING_API_KEY, MIDU_API_KEY)
    or a local .env that is gitignored. No key is ever committed.

ATTRIBUTION
    Recent Funding asks callers to identify who they fetch for. We send
    X-On-Behalf-Of and a named User-Agent on every request, as its docs
    require.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

ON_BEHALF_OF = os.environ.get("FUNDING_ON_BEHALF_OF", "Columbia IEOR 4511E (columbia.edu)")
USER_AGENT = "columbia-ieor4511-funding-benchmark/1.0"

FOUND = "FUNDING_EVENT_FOUND"
NO_EVENT = "COMPANY_FOUND_NO_EVENT_RETURNED"
NOT_FOUND = "COMPANY_NOT_FOUND"
AMBIGUOUS = "AMBIGUOUS_MATCH"
FAILED = "SOURCE_QUERY_FAILED"

WINDOW_START = "2024-04-04"   # exclusive: events ON the decision date are X
WINDOW_END = "2026-04-04"     # inclusive


def load_env(path=".env"):
    """Read KEY=value lines from a local .env. Never committed."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class RateLimiter:
    """Simple spacing plus a hard daily budget, so a run cannot blow a quota."""

    def __init__(self, per_minute, daily_budget):
        self.gap = 60.0 / max(per_minute, 1)
        self.remaining = daily_budget
        self._last = 0.0

    def take(self):
        if self.remaining <= 0:
            raise RuntimeError("daily request budget exhausted")
        wait = self.gap - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.remaining -= 1


class Client:
    """Shared GET + JSON plumbing. Subclasses define base, auth and parsing."""

    name = "base"
    base = ""

    def __init__(self, key, per_minute=30, daily_budget=100):
        self.key = key
        self.limiter = RateLimiter(per_minute, daily_budget)
        self.calls = 0

    def headers(self):
        return {"Authorization": "Bearer %s" % self.key,
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "X-On-Behalf-Of": ON_BEHALF_OF}

    def get(self, path, params=None, tries=3):
        """Returns (json, None) or (None, error_string)."""
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        last = None
        for i in range(tries):
            try:
                self.limiter.take()
                self.calls += 1
                req = urllib.request.Request(url, headers=self.headers())
                with urllib.request.urlopen(req, timeout=45) as resp:
                    return json.loads(resp.read().decode("utf-8")), None
            except urllib.error.HTTPError as e:
                body = ""
                try:
                    body = e.read().decode("utf-8", "replace")[:200]
                except Exception:
                    pass
                last = "HTTP %s %s" % (e.code, body)
                if e.code in (401, 403, 404):
                    return None, last            # not retryable
                if e.code == 429:
                    time.sleep(20 * (i + 1))
                    continue
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, e)
            time.sleep(4 * (i + 1))
        return None, last


def in_window(date_str):
    """True only for a usable date strictly after the decision date and on or
    before the cutoff. An unparseable date is not silently accepted."""
    if not date_str or len(str(date_str)) < 10:
        return False
    d = str(date_str)[:10]
    return WINDOW_START < d <= WINDOW_END


class RecentFunding(Client):
    """recentfunding.com. Free key by email; 100 requests/day."""

    name = "recent_funding"
    base = "https://recentfunding.com/api/v1"

    def __init__(self, key):
        Client.__init__(self, key, per_minute=20, daily_budget=95)

    def lookup(self, domains, names):
        """Try domains first, then names. Returns (status, events, note)."""
        for q in list(domains) + list(names):
            data, err = self.get("/companies", {"q": q, "limit": 10})
            if err:
                if "401" in err or "403" in err:
                    return FAILED, [], "auth: " + err
                continue
            items = (data or {}).get("data") or (data or {}).get("companies") or []
            if not items:
                continue
            if len(items) > 1 and q in names:
                return AMBIGUOUS, [], "%d candidates for name %r" % (len(items), q)
            comp = items[0]
            slug = comp.get("slug") or comp.get("key") or comp.get("id")
            detail, err2 = self.get("/companies/%s" % slug) if slug else (None, "no slug")
            if err2:
                return FAILED, [], "detail: " + err2
            rounds = (detail or {}).get("rounds") or (detail or {}).get("data", {}).get("rounds") or []
            events = [self._event(r, comp) for r in rounds if in_window(r.get("date") or r.get("announced_on"))]
            return (FOUND if events else NO_EVENT), events, "matched on %r" % q
        return NOT_FOUND, [], "no identifier resolved"

    @staticmethod
    def _event(r, comp):
        return {"source": "recent_funding",
                "matched_company": comp.get("name", ""),
                "event_date": str(r.get("date") or r.get("announced_on") or "")[:10],
                "amount_usd": r.get("amount") or r.get("amount_usd") or "",
                "round_type": r.get("stage") or r.get("round") or "",
                "investors": "|".join(i.get("name", "") for i in (r.get("investors") or []) if isinstance(i, dict)),
                "lead_investor": (r.get("lead") or {}).get("name", "") if isinstance(r.get("lead"), dict) else (r.get("lead") or ""),
                "evidence_url": r.get("source_url") or r.get("url") or ""}


class Midu(Client):
    """midu.si. Free key by email; 1,000 requests/day, 60/minute."""

    name = "midu"
    base = "https://midu.si/api/v1"

    def __init__(self, key):
        Client.__init__(self, key, per_minute=45, daily_budget=950)

    def lookup(self, domains, names):
        for q in list(domains) + list(names):
            data, err = self.get("/companies", {"q": q})
            if err:
                if "401" in err or "403" in err:
                    return FAILED, [], "auth: " + err
                continue
            items = (data or {}).get("data") or []
            if not items:
                continue
            if len(items) > 1 and q in names:
                return AMBIGUOUS, [], "%d candidates for name %r" % (len(items), q)
            key_ = items[0].get("key") or items[0].get("slug")
            detail, err2 = self.get("/companies/%s" % key_) if key_ else (None, "no key")
            if err2:
                return FAILED, [], "detail: " + err2
            d = (detail or {}).get("data") or detail or {}
            rounds = d.get("timeline") or d.get("rounds") or []
            events = [self._event(r, items[0]) for r in rounds if in_window(r.get("date"))]
            return (FOUND if events else NO_EVENT), events, "matched on %r" % q
        return NOT_FOUND, [], "no identifier resolved"

    @staticmethod
    def _event(r, comp):
        return {"source": "midu",
                "matched_company": comp.get("company") or comp.get("name", ""),
                "event_date": str(r.get("date") or "")[:10],
                "amount_usd": r.get("amount_usd") or r.get("amount") or "",
                "round_type": r.get("round") or r.get("type") or "",
                "investors": "|".join(r.get("investors") or []) if isinstance(r.get("investors"), list) else (r.get("investors") or ""),
                "lead_investor": r.get("lead") or "",
                "evidence_url": r.get("url") or ""}


REGISTRY = {
    "recent_funding": (RecentFunding, "RECENTFUNDING_API_KEY"),
    "midu": (Midu, "MIDU_API_KEY"),
}


def build(name):
    """Instantiate a source by name, or raise with the exact missing variable."""
    cls, env = REGISTRY[name]
    load_env()
    key = os.environ.get(env)
    if not key:
        raise RuntimeError(
            "%s is not set. Put it in a local .env (gitignored) as %s=..." % (env, env))
    return cls(key)
