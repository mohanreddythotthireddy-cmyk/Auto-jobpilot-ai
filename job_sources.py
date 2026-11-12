from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
import requests

from config import (
    ADZUNA_APP_ID,
    ADZUNA_APP_KEY,
    ASHBY_BOARDS,
    BENGALURU_LOCATIONS,
    GREENHOUSE_BOARDS,
    INCLUDE_OTHER_INDIAN_CITIES,
    LEVER_BOARDS,
    MAJOR_INDIAN_CITIES,
    SOURCE_REFRESH_MINUTES,
    TARGET_ROLES,
    USAJOBS_API_KEY,
    USAJOBS_EMAIL,
)
from work_mode import is_bengaluru, is_india_listing

TIMEOUT = 15
RETRIES = 2
MAX_PAGES = 10
ADZUNA_BENGALURU_BATCH_SIZE = 8
ADZUNA_MAJOR_CITY_BATCH_SIZE = 4
ADZUNA_REMOTE_BATCH_SIZE = 2
ADZUNA_RESULTS_PER_PAGE = 50
ADZUNA_MAX_PAGES = 3
_REQUEST_TIMES: dict[str, float] = {}
_REQUEST_LOCK = threading.Lock()


@dataclass
class SourceReport:
    name: str
    configured: bool
    status: str
    connection_ok: bool = False
    http_status: int | None = None
    returned: int = 0
    pages: int = 0
    error: str = ""
    jobs: list[dict] = field(default_factory=list)
    after_filtering: int = 0
    rejected_by_location: int = 0
    rejected_by_role: int = 0
    rejected_by_experience: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)
    filter_errors: int = 0
    saved: int = 0
    updated: int = 0
    duplicates: int = 0
    database_error: str = ""
    india_listings: int = 0
    bengaluru_listings: int = 0
    fresh_listings: int = 0
    freshness_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class SourceSpec:
    name: str
    configured: bool
    config_error: str
    fetch: Callable[[], tuple[list[dict], int | None, int]]


class SourceHTTPError(requests.HTTPError):
    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def make_id(source, url, title, company):
    raw = f"{source}|{url}|{title}|{company}".lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _job(source, title, company, location, url, description, posted="",
         source_updated_at="", source_job_id="", remote=False, workplace_type="",
         job_type=""):
    title = str(title or "").strip()
    company = str(company or "Unknown").strip()
    location = str(location or "").strip()
    url = str(url or "").strip()
    if isinstance(job_type, (list, tuple)):
        job_type = ", ".join(str(value) for value in job_type if value)
    return {
        "id": make_id(source, url, title, company),
        "title": title,
        "company": company or "Unknown",
        "location": location,
        "url": url,
        "description": str(description or ""),
        "source": source,
        "posted": str(posted or ""),
        "source_updated_at": str(source_updated_at or ""),
        "source_job_id": str(source_job_id or ""),
        "remote": bool(remote),
        "workplaceType": str(workplace_type or ""),
        "job_type": str(job_type or ""),
    }


def _safe_error(exc):
    if isinstance(exc, requests.Timeout):
        return f"Request timed out after {TIMEOUT} seconds"
    if isinstance(exc, SourceHTTPError):
        return f"HTTP {exc.status_code}"
    if isinstance(exc, requests.ConnectionError):
        return "Network connection failed"
    return re.sub(r"https?://\S+", "[request URL]", str(exc))[:300]


def _get_json(source, url, params=None, headers=None, session=requests,
              timeout=TIMEOUT, min_interval=0.25, retries=RETRIES):
    last_response = None
    for attempt in range(retries + 1):
        with _REQUEST_LOCK:
            elapsed = time.monotonic() - _REQUEST_TIMES.get(source, 0)
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            _REQUEST_TIMES[source] = time.monotonic()
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
            last_response = response
        except requests.RequestException:
            if attempt < retries:
                time.sleep(0.25 * (2 ** attempt))
                continue
            raise
        if response.status_code == 429 or 500 <= response.status_code <= 599:
            if attempt < retries:
                retry_after = response.headers.get("Retry-After", "")
                try:
                    delay = min(float(retry_after), 10)
                except (TypeError, ValueError):
                    delay = 0.25 * (2 ** attempt)
                time.sleep(max(0, delay))
                continue
        if not 200 <= response.status_code < 300:
            raise SourceHTTPError(response.status_code)
        try:
            return response.json(), response.status_code
        except ValueError as exc:
            raise ValueError(f"Invalid JSON response from {source}") from exc
    if last_response is not None:
        raise SourceHTTPError(last_response.status_code)
    raise RuntimeError(f"{source} request did not produce a response")


def _api_error(exc):
    if isinstance(exc, requests.Timeout):
        return "network_error", _safe_error(exc)
    if isinstance(exc, requests.ConnectionError):
        return "network_error", _safe_error(exc)
    if isinstance(exc, SourceHTTPError):
        return "http_error", _safe_error(exc)
    if isinstance(exc, requests.RequestException):
        return "network_error", _safe_error(exc)
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return "response_error", _safe_error(exc)
    return "source_error", _safe_error(exc)


def _pages(data, key):
    value = data.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Expected a list in response field {key!r}")
    return value


def _adzuna_search_plan(cycle, roles=None, include_other_cities=None):
    roles = list(roles or TARGET_ROLES)
    if not roles:
        return []
    include_other = (
        INCLUDE_OTHER_INDIAN_CITIES
        if include_other_cities is None else include_other_cities
    )
    role_start = (cycle * ADZUNA_BENGALURU_BATCH_SIZE) % len(roles)
    plan = []
    local_count = min(ADZUNA_BENGALURU_BATCH_SIZE, len(roles))
    for offset in range(local_count):
        area = BENGALURU_LOCATIONS[(cycle * local_count + offset) % len(BENGALURU_LOCATIONS)]
        role = roles[(role_start + offset) % len(roles)]
        query_role = role
        if cycle % 3 == 1:
            query_role = f"{role} fresher"
        elif cycle % 3 == 2:
            query_role = f"{role} entry level"
        plan.append({"what": query_role, "where": area, "location_group": "Bengaluru"})

    next_role = (role_start + local_count) % len(roles)
    if include_other:
        for offset in range(min(ADZUNA_MAJOR_CITY_BATCH_SIZE, len(MAJOR_INDIAN_CITIES))):
            city = MAJOR_INDIAN_CITIES[(cycle * ADZUNA_MAJOR_CITY_BATCH_SIZE + offset) % len(MAJOR_INDIAN_CITIES)]
            role = roles[(next_role + offset) % len(roles)]
            plan.append({"what": role, "where": city, "location_group": "Indian city"})
        next_role = (next_role + ADZUNA_MAJOR_CITY_BATCH_SIZE) % len(roles)

    remote_count = (
        ADZUNA_REMOTE_BATCH_SIZE
        if include_other else ADZUNA_MAJOR_CITY_BATCH_SIZE + ADZUNA_REMOTE_BATCH_SIZE
    )
    for offset in range(remote_count):
        role = roles[(next_role + offset) % len(roles)]
        plan.append({
            "what": f"{role} remote",
            "where": "India",
            "location_group": "Remote India",
        })
    return plan


def _adzuna(terms, include_other_cities=None):
    jobs, status, pages = [], None, 0
    base = "https://api.adzuna.com/v1/api/jobs/in/search"
    interval = max(1, SOURCE_REFRESH_MINUTES.get("Adzuna", 15)) * 60
    cycle = int(time.time() // interval)
    roles = [role for role in TARGET_ROLES if any(
        str(term).lower().startswith(role.lower()) for term in terms
    )] or list(TARGET_ROLES)
    plan = _adzuna_search_plan(cycle, roles, include_other_cities)
    errors = []
    exceptions = []
    seen_queries = set()
    for query in plan:
        term, where = query["what"], query["where"]
        if (term.casefold(), where.casefold()) in seen_queries:
            continue
        seen_queries.add((term.casefold(), where.casefold()))
        try:
            for page in range(1, ADZUNA_MAX_PAGES + 1):
                data, status = _get_json(
                    "Adzuna", f"{base}/{page}",
                    params={
                        "app_id": ADZUNA_APP_ID, "app_key": ADZUNA_APP_KEY,
                        "what": term, "where": where,
                        "results_per_page": ADZUNA_RESULTS_PER_PAGE,
                        "content-type": "application/json",
                    },
                    min_interval=0.25,
                )
                pages += 1
                results = _pages(data, "results")
                for item in results:
                    loc = (item.get("location") or {}).get("display_name", "")
                    company = (item.get("company") or {}).get("display_name", "Unknown")
                    jobs.append(_job(
                        "Adzuna", item.get("title"), company, loc, item.get("redirect_url"),
                        item.get("description"), item.get("created"),
                        source_job_id=item.get("id"),
                        job_type=item.get("contract_type") or item.get("contract_time"),
                    ))
                if len(results) < ADZUNA_RESULTS_PER_PAGE:
                    break
        except Exception as exc:
            errors.append(f"query {term!r}: {_safe_error(exc)}")
            exceptions.append(exc)
    if errors and not pages:
        raise exceptions[0]
    if errors:
        return jobs, status, pages, "; ".join(errors[:3])
    return jobs, status, pages


def _arbeitnow():
    jobs, status, pages = [], None, 0
    for page in range(1, MAX_PAGES + 1):
        data, status = _get_json(
            "Arbeitnow", "https://www.arbeitnow.com/api/job-board-api",
            params={"page": page}, min_interval=0.5,
        )
        pages += 1
        results = _pages(data, "data")
        for item in results:
            jobs.append(_job(
                "Arbeitnow", item.get("title"), item.get("company_name"),
                item.get("location"), item.get("url"), item.get("description"),
                item.get("created_at"), source_job_id=item.get("slug"),
                remote=item.get("remote") is True,
                job_type=item.get("job_type") or item.get("job_types"),
            ))
        pagination = data.get("meta") or {}
        try:
            last_page = int(pagination.get("last_page") or pagination.get("lastPage") or 0)
        except (TypeError, ValueError):
            last_page = 0
        if (last_page and page >= last_page) or not results or (not last_page and len(results) < 10):
            break
    return jobs, status, pages


def _greenhouse():
    jobs, status, pages = [], None, 0
    for board in GREENHOUSE_BOARDS:
        data, status = _get_json(
            "Greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            params={"content": "true"}, min_interval=0.2,
        )
        pages += 1
        for item in _pages(data, "jobs"):
            jobs.append(_job(
                "Greenhouse", item.get("title"), board,
                (item.get("location") or {}).get("name"), item.get("absolute_url"),
                item.get("content"), item.get("first_published"),
                item.get("updated_at"), item.get("id"),
                job_type=item.get("employment_type"),
            ))
    return jobs, status, pages


def _lever():
    jobs, status, pages = [], None, 0
    for board in LEVER_BOARDS:
        for skip in range(0, MAX_PAGES * 100, 100):
            data, status = _get_json(
                "Lever", f"https://api.lever.co/v0/postings/{board}",
                params={"mode": "json", "skip": skip, "limit": 100},
                headers={"Accept": "application/json"}, min_interval=0.2,
            )
            pages += 1
            if not isinstance(data, list):
                raise ValueError("Lever response must be a JSON list")
            for item in data:
                categories = item.get("categories") or {}
                jobs.append(_job(
                    "Lever", item.get("text"), board, categories.get("location"),
                    item.get("hostedUrl"), item.get("descriptionPlain") or item.get("description"),
                    item.get("createdAt"), item.get("updatedAt"), item.get("id"),
                    workplace_type=item.get("workplaceType", ""),
                    job_type=categories.get("commitment"),
                ))
            if len(data) < 100:
                break
    return jobs, status, pages


def _ashby():
    jobs, status, pages = [], None, 0
    for board in ASHBY_BOARDS:
        data, status = _get_json(
            "Ashby", f"https://api.ashbyhq.com/posting-api/job-board/{board}",
            params={"includeCompensation": "false"}, min_interval=0.2,
        )
        pages += 1
        for item in _pages(data, "jobs"):
            if item.get("isListed") is False:
                continue
            jobs.append(_job(
                "Ashby", item.get("title"), board,
                item.get("location"), item.get("jobUrl"),
                item.get("descriptionPlain") or item.get("descriptionHtml"),
                item.get("publishedAt"), source_job_id=item.get("id"),
                remote=item.get("isRemote") is True,
                workplace_type=item.get("workplaceType", ""),
                job_type=item.get("employmentType"),
            ))
    return jobs, status, pages


def _usajobs(terms):
    jobs, status, pages = [], None, 0
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": USAJOBS_EMAIL,
        "Authorization-Key": USAJOBS_API_KEY,
    }
    for term in terms[:8]:
        for page in range(1, MAX_PAGES + 1):
            data, status = _get_json(
                "USAJOBS", "https://data.usajobs.gov/api/search",
                params={"Keyword": term, "LocationName": "India",
                        "ResultsPerPage": 25, "Page": page},
                headers=headers, min_interval=0.5,
            )
            pages += 1
            search = data.get("SearchResult") or {}
            results = search.get("SearchResultItems") or []
            for entry in results:
                item = entry.get("MatchedObjectDescriptor") or {}
                locations = item.get("PositionLocation") or []
                location = ", ".join(x.get("LocationName", "") for x in locations)
                jobs.append(_job(
                    "USAJOBS", item.get("PositionTitle"), item.get("OrganizationName"),
                    location, item.get("PositionURI"),
                    item.get("UserArea", {}).get("Details", {}).get("JobSummary", ""),
                    item.get("PublicationStartDate"),
                    source_job_id=item.get("PositionID"),
                    job_type=", ".join(
                        schedule.get("Name", "")
                        for schedule in item.get("PositionSchedule") or []
                    ),
                ))
            if len(results) < 25:
                break
    return jobs, status, pages


def source_specs(terms, include_other_cities=None):
    missing_usa = []
    if not USAJOBS_API_KEY:
        missing_usa.append("USAJOBS_API_KEY")
    if not USAJOBS_EMAIL:
        missing_usa.append("USAJOBS_EMAIL")
    elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", USAJOBS_EMAIL):
        missing_usa.append("USAJOBS_EMAIL (must be a valid email address)")
    return [
        SourceSpec("Adzuna", bool(ADZUNA_APP_ID and ADZUNA_APP_KEY),
                   "ADZUNA_APP_ID and ADZUNA_APP_KEY are required",
                   lambda: _adzuna(terms, include_other_cities)),
        SourceSpec("Arbeitnow", True, "", _arbeitnow),
        SourceSpec("Greenhouse", bool(GREENHOUSE_BOARDS),
                   "Set GREENHOUSE_BOARDS to one or more published board tokens",
                   _greenhouse),
        SourceSpec("Lever", bool(LEVER_BOARDS),
                   "Set LEVER_BOARDS to one or more published site names", _lever),
        SourceSpec("Ashby", bool(ASHBY_BOARDS),
                   "Set ASHBY_BOARDS to one or more published job-board names", _ashby),
        SourceSpec("USAJOBS", not missing_usa,
                   f"Missing required setting(s): {', '.join(missing_usa)}" if missing_usa else "",
                   lambda: _usajobs(terms)),
    ]


def fetch_sources(terms, only_sources=None, include_other_cities=None):
    reports = []
    selected = set(only_sources) if only_sources is not None else None
    specs = (
        source_specs(terms)
        if include_other_cities is None
        else source_specs(terms, include_other_cities)
    )
    for spec in specs:
        if selected is not None and spec.name not in selected:
            continue
        if not spec.configured:
            reports.append(SourceReport(
                spec.name, False, "not_configured", error=spec.config_error,
            ))
            continue
        try:
            result = spec.fetch()
            jobs, status, pages = result[:3]
            partial_error = result[3] if len(result) > 3 else ""
            reports.append(SourceReport(
                spec.name, True,
                "partial" if partial_error else "searched" if jobs else "empty_results",
                connection_ok=True, http_status=status, returned=len(jobs),
                pages=pages, error=partial_error, jobs=jobs,
            ))
        except Exception as exc:
            kind, message = _api_error(exc)
            status = getattr(exc, "status_code", None)
            reports.append(SourceReport(
                spec.name, True, kind, http_status=status, error=message,
            ))
    return reports


MANUAL_SEARCH_LINKS = {
    "Indeed": "https://www.indeed.com/jobs?q=entry+level+software&l=India",
    "LinkedIn": "https://www.linkedin.com/jobs/search/?keywords=entry%20level%20software&location=India",
    "Monster": "https://www.monster.com/jobs/search/?q=entry-level-software&where=India",
    "SimplyHired": "https://www.simplyhired.com/search?q=entry+level+software&l=India",
    "Glassdoor": "https://www.glassdoor.com/Job/india-entry-level-software-jobs-SRCH_IL.0,5_IN115_KO6,26.htm",
    "Dice": "https://www.dice.com/jobs?q=entry%20level%20software&location=India",
    "Craigslist": "https://geo.craigslist.org/iso/in",
    "Snagajob": "https://www.snagajob.com/search?q=entry%20level%20software",
    "Unstop": "https://unstop.com/jobs",
    "Naukri": "https://www.naukri.com/entry-level-jobs-in-india",
    "Hirist": "https://www.hirist.tech/",
    "Instahyre": "https://www.instahyre.com/",
    "Cutshort": "https://cutshort.io/jobs",
    "Foundit": "https://www.foundit.in/search/entry-level-jobs",
    "TimesJobs": "https://www.timesjobs.com/candidate/job-search.html",
    "Internshala": "https://internshala.com/jobs/",
    "Upwork (freelance)": "https://www.upwork.com/nx/search/jobs/?q=python",
    "Toptal (freelance)": "https://www.toptal.com/talent/apply",
}


def manual_search_links():
    return dict(MANUAL_SEARCH_LINKS)
