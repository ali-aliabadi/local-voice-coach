"""Real job postings from Himalayas. The network is never touched: its answer is recorded."""

import warnings
from urllib.error import URLError

import pytest
from starlette.applications import Starlette

warnings.filterwarnings("ignore", message="Using `httpx`")  # starlette's own transition
from starlette.testclient import TestClient  # noqa: E402

from coach import jobs, profile  # noqa: E402
from coach.server import api  # noqa: E402

# One posting, as Himalayas sent it on 2026-10-06, trimmed.
POSTING = {
    "title": "Software Engineer - Backend",
    "excerpt": "Build the payments API.",
    "companyName": "micro1",
    "employmentType": "Contractor",
    "minSalary": 30,
    "maxSalary": 100,
    "salaryPeriod": "hourly",
    "currency": "USD",
    "seniority": ["Mid-level"],
    "locationRestrictions": [],
    "description": "<p>We use <b>Go</b> &amp; Postgres.</p><ul><li>On call</li></ul>",
    "pubDate": "1791289606",
    "applicationLink": "https://himalayas.app/companies/micro1/jobs/software-engineer-backend",
}


@pytest.fixture
def himalayas(monkeypatch):
    """Answers every search with POSTING, and keeps the URLs it was asked for."""
    asked: list[str] = []

    def fetch(url):
        asked.append(url)
        return {"jobs": [POSTING], "totalCount": 1}

    jobs._cache.clear()
    monkeypatch.setattr(jobs, "_fetch", fetch)
    return asked


@pytest.mark.usefixtures("himalayas")
def test_a_posting_reads_the_way_the_page_and_the_interviewer_need_it():
    [job] = jobs.search("backend")["jobs"]
    assert job["location"] == "Worldwide"
    assert job["salary"] == "30-100 USD an hour"
    assert job["posted"] == "2026-10-06"
    assert job["description"] == "We use Go & Postgres.\nOn call"


@pytest.mark.parametrize(
    ("changed", "location", "salary", "url"),
    [
        ({"locationRestrictions": ["Germany", "Netherlands"]}, "Germany, Netherlands", None, None),
        ({"minSalary": None, "maxSalary": None}, "Worldwide", None, None),
        ({"minSalary": 65000, "maxSalary": 65000, "salaryPeriod": "annual", "currency": "EUR"},
         "Worldwide", "65,000 EUR a year", None),
        ({"applicationLink": "javascript:alert(1)"}, "Worldwide", None, jobs.SOURCE),
    ],
)  # fmt: skip
def test_postings_with_less_or_different_detail(changed, location, salary, url):
    job = jobs._job({**POSTING, **changed})
    assert job["location"] == location
    if salary or "minSalary" in changed:
        assert job["salary"] == salary
    if url:
        assert job["url"] == url, "only an https link reaches the page"


def test_every_level_in_the_profile_has_a_search_level():
    assert set(jobs.LEVELS) == set(profile.SENIORITY) - {""}


def test_a_search_is_asked_once_an_hour_and_says_what_it_filters(himalayas):
    jobs.search("go", "Senior", "DE", worldwide=True, page=2)
    jobs.search("go", "Senior", "DE", worldwide=True, page=2)
    [url] = himalayas
    assert url.startswith(jobs.SEARCH + "?q=go&sort=recent&page=2")
    assert "seniority=Senior" in url
    assert "country=DE" in url
    assert "worldwide=true" in url


@pytest.mark.usefixtures("himalayas")
def test_the_jobs_page_searches_the_profile_unless_told_otherwise():
    # One client for the whole test: the database belongs to the thread that opened it.
    with TestClient(Starlette(routes=api.ROUTES)) as client:
        client.post("/api/profile", json={"role": "Backend engineer", "seniority": "staff"})
        found = client.get("/api/jobs").json()
        assert (found["q"], found["seniority"], found["total"]) == ("Backend engineer", "Senior", 1)
        assert client.get("/api/jobs?q=rust&seniority=").json()["seniority"] == ""


def test_no_internet_is_said_not_crashed_on(monkeypatch):
    def offline(_url):
        raise URLError("no route to host")

    jobs._cache.clear()
    monkeypatch.setattr(jobs, "_fetch", offline)
    response = TestClient(Starlette(routes=api.ROUTES)).get("/api/jobs?q=go")
    assert response.status_code == 502
    assert "Could not reach Himalayas" in response.json()["error"]


@pytest.mark.usefixtures("himalayas")
def test_postings_in_another_language_are_left_out(monkeypatch):
    """An English interview cannot be practised against a posting in Portuguese."""
    portuguese = (
        "<p>Somos um grupo que desenvolve e incorpora soluções SaaS como motor de crescimento "
        "e habilitador de novas linhas de negócio para as verticais em que atuamos: Indústria "
        "da Construção, Inteligência Legal, Eficiência Operacional e Governança.</p>"
    )
    english = (
        "<p>We are looking for a backend engineer to join our payments team. You will own "
        "the services that move money for our customers, and work with the product team on "
        "what we build next.</p>"
    )
    monkeypatch.setattr(
        jobs,
        "_fetch",
        lambda _url: {"jobs": [{**POSTING, "description": d} for d in (portuguese, english)]},
    )
    [kept] = jobs.search("backend")["jobs"]
    assert kept["description"].startswith("We are looking")
    assert jobs.english("Short posting, Go and Postgres."), "too short to judge: kept"
