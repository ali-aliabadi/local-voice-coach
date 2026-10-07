"""Real job postings to practise the interview for, from Himalayas' public API.

Himalayas lists remote jobs and needs no key (https://himalayas.app/docs/remote-jobs-api).
Its terms ask anything that shows its jobs to link back to it and name it as the source;
the jobs page does both. Only the search - words, a level, a country - leaves this
machine, and only when you search. Remotive was the other candidate: its jobs arrive a
day late and it allows four calls a day.
"""

import datetime as dt
import json
import re
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import documents

SEARCH = "https://himalayas.app/jobs/api/search"
SOURCE = "https://himalayas.app"
FRESH = 3600  # seconds a search is kept; Himalayas rebuilds its listings once a day
# The profile's levels, in Himalayas' words.
PER = {"annual": "a year", "monthly": "a month", "weekly": "a week", "hourly": "an hour"}

# Words every English posting is full of and other languages' postings are not. Six of
# the first 19 for "backend engineer" were in Portuguese, Spanish or Ukrainian: no use here.
# ponytail: a word count, not a language detector; use one if it misjudges postings.
ENGLISH = frozenset(
    ("the", "and", "to", "of", "in", "for", "you", "we", "with", "is", "are", "our", "will",
     "on", "be", "this", "your"),
)  # fmt: skip

# ponytail: in memory, per run; the app is started for a session and stopped after anyway
_cache: dict[str, tuple[float, dict]] = {}


def _fetch(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "local-voice-coach"})  # noqa: S310 - SEARCH
    with urlopen(request, timeout=15) as response:  # noqa: S310 - always SEARCH, https
        return json.load(response)


def _salary(job: dict) -> str | None:
    low, high = job.get("minSalary"), job.get("maxSalary")
    if not low and not high:
        return None
    span = f"{low:,.0f}-{high:,.0f}" if low and high and low != high else f"{low or high:,.0f}"
    period = job.get("salaryPeriod") or ""
    return " ".join(part for part in (span, job.get("currency"), PER.get(period, period)) if part)


def english(text: str) -> bool:
    words = re.findall(r"[a-z']+", text.lower())
    return len(words) < 20 or sum(w in ENGLISH for w in words) / len(words) > 0.08


def _job(job: dict) -> dict:
    """One posting, as the page shows it and the interviewer reads it."""
    url = job.get("applicationLink") or job.get("guid") or ""
    posted = str(job.get("pubDate") or "")
    return {
        "title": job.get("title") or "",
        "company": job.get("companyName") or "",
        "url": url if url.startswith("https://") else SOURCE,  # never a javascript: link
        "location": ", ".join(job.get("locationRestrictions") or []) or "Worldwide",
        "salary": _salary(job),
        "posted": dt.datetime.fromtimestamp(int(posted), dt.UTC).date().isoformat()
        if posted.isdigit()
        else None,
        "type": job.get("employmentType") or "",
        "excerpt": job.get("excerpt") or "",
        "description": documents.plain(job.get("description") or ""),
    }


def search(
    words: str, seniority: str = "", country: str = "", worldwide: bool = False, page: int = 1
) -> dict:
    """Postings matching a search, most recent first, about 20 a page."""
    query: dict[str, str | int] = {"q": words, "sort": "recent", "page": page}
    if seniority:
        query["seniority"] = seniority
    if country:
        query["country"] = country
    if worldwide:
        query["worldwide"] = "true"
    url = f"{SEARCH}?{urlencode(query)}"
    kept = _cache.get(url)
    if kept is None or time.time() - kept[0] > FRESH:
        try:
            kept = (time.time(), _fetch(url))
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Could not reach Himalayas: {exc}") from exc
        _cache[url] = kept
    found = kept[1]
    postings = [_job(j) for j in found.get("jobs") or []]
    return {
        "jobs": [p for p in postings if english(p["description"])],
        "total": found.get("totalCount", 0),
    }
