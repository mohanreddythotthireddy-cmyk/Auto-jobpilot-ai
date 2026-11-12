from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
import requests

import db
import job_sources
import run_search
from job_sources import SourceSpec
from job_sources import SourceReport
from run_search import freshness_window
from resume_job_terms import generate_search_terms
from work_mode import classify_work_mode, location_filter_reason


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self.payload


def _job(job_id="id-1", source="Test", url="https://jobs.example/jobs/1"):
    return {
        "id": job_id, "source": source, "source_job_id": job_id,
        "title": "Graduate Engineer Trainee", "company": "Example",
        "location": "Bengaluru, Karnataka, India", "url": url,
        "description": "Entry-level role", "posted": "2026-11-11T12:00:00+00:00",
        "match_score": 50, "matched_skills": [], "work_mode": "Not specified",
    }


def test_missing_adzuna_credentials_report_not_configured(monkeypatch):
    monkeypatch.setattr(job_sources, "ADZUNA_APP_ID", "")
    monkeypatch.setattr(job_sources, "ADZUNA_APP_KEY", "")
    reports = job_sources.fetch_sources(["Python"], only_sources={"Adzuna"})
    assert reports[0].status == "not_configured"
    assert reports[0].configured is False
    assert "ADZUNA_APP_ID" in reports[0].error


def test_invalid_adzuna_credentials_report_http_status(monkeypatch):
    monkeypatch.setattr(job_sources, "ADZUNA_APP_ID", "test-id")
    monkeypatch.setattr(job_sources, "ADZUNA_APP_KEY", "not-a-real-secret")
    monkeypatch.setattr(job_sources, "_REQUEST_TIMES", {})
    monkeypatch.setattr(job_sources.time, "sleep", lambda _: None)

    class Session:
        def get(self, *args, **kwargs):
            return FakeResponse(401)

    monkeypatch.setattr(job_sources.requests, "get", Session().get)
    reports = job_sources.fetch_sources(["Python"], only_sources={"Adzuna"})
    assert reports[0].status == "http_error"
    assert reports[0].http_status == 401
    assert "not-a-real-secret" not in reports[0].error


def test_request_retries_timeout_then_returns_success(monkeypatch):
    monkeypatch.setattr(job_sources, "_REQUEST_TIMES", {})
    monkeypatch.setattr(job_sources.time, "sleep", lambda _: None)

    class Session:
        attempts = 0

        def get(self, *args, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise requests.Timeout("slow")
            return FakeResponse(payload={"ok": True})

    session = Session()
    payload, status = job_sources._get_json("TestTimeout", "https://example.test", session=session)
    assert payload == {"ok": True}
    assert status == 200 and session.attempts == 3


def test_request_retries_server_error_and_reports_http_error(monkeypatch):
    monkeypatch.setattr(job_sources, "_REQUEST_TIMES", {})
    monkeypatch.setattr(job_sources.time, "sleep", lambda _: None)

    class Session:
        attempts = 0

        def get(self, *args, **kwargs):
            self.attempts += 1
            return FakeResponse(503)

    session = Session()
    with pytest.raises(job_sources.SourceHTTPError) as err:
        job_sources._get_json("TestHTTP", "https://example.test", session=session)
    assert err.value.status_code == 503
    assert session.attempts == job_sources.RETRIES + 1


def test_arbeitnow_paginates_until_short_page(monkeypatch):
    requests_seen = []

    def get_json(source, url, params=None, **kwargs):
        requests_seen.append(params["page"])
        count = 10 if params["page"] == 1 else 3
        return {"data": [{
            "title": f"Role {i}", "company_name": "Acme", "location": "India",
            "url": f"https://example.test/{params['page']}/{i}",
        } for i in range(count)]}, 200

    monkeypatch.setattr(job_sources, "_get_json", get_json)
    jobs, status, pages = job_sources._arbeitnow()
    assert len(jobs) == 13 and status == 200
    assert pages == 2 and requests_seen == [1, 2]


def test_lever_paginates_with_skip_limit(monkeypatch):
    requests_seen = []

    def get_json(source, url, params=None, **kwargs):
        requests_seen.append((params["skip"], params["limit"]))
        count = 100 if params["skip"] == 0 else 3
        return [{
            "text": f"Role {i}",
            "hostedUrl": f"https://example.test/{params['skip']}/{i}",
        } for i in range(count)], 200

    monkeypatch.setattr(job_sources, "LEVER_BOARDS", ["example"])
    monkeypatch.setattr(job_sources, "_get_json", get_json)
    jobs, status, pages = job_sources._lever()

    assert len(jobs) == 103 and status == 200
    assert pages == 2 and requests_seen == [(0, 100), (100, 100)]


def test_adzuna_paginates_full_results(monkeypatch):
    pages = []
    monkeypatch.setattr(job_sources, "ADZUNA_BENGALURU_BATCH_SIZE", 1)
    monkeypatch.setattr(job_sources, "ADZUNA_MAJOR_CITY_BATCH_SIZE", 0)
    monkeypatch.setattr(job_sources, "ADZUNA_REMOTE_BATCH_SIZE", 0)
    monkeypatch.setattr(job_sources, "BENGALURU_LOCATIONS", ("Bengaluru",))

    def get_json(source, url, params=None, **kwargs):
        page = int(url.rsplit("/", 1)[1])
        pages.append(page)
        if page == 1:
            data = [{"title": f"Job {i}", "id": i} for i in range(50)]
        else:
            data = []
        return {"results": data}, 200

    monkeypatch.setattr(job_sources, "ADZUNA_APP_ID", "id")
    monkeypatch.setattr(job_sources, "ADZUNA_APP_KEY", "key")
    monkeypatch.setattr(job_sources, "_get_json", get_json)
    jobs, status, page_count = job_sources._adzuna(["Python"])
    assert len(jobs) == 50 and status == 200
    assert pages == [1, 2] and page_count == 2


def test_adzuna_search_plan_prioritizes_bengaluru_then_india_then_remote():
    plan = job_sources._adzuna_search_plan(
        0, roles=["AWS Cloud Support Associate"], include_other_cities=True
    )

    assert plan[0]["location_group"] == "Bengaluru"
    assert all(item["location_group"] == "Indian city" for item in plan[1:5])
    assert all(item["location_group"] == "Remote India" for item in plan[5:])


def test_source_failure_does_not_stop_later_source(monkeypatch):
    specs = [
        SourceSpec("broken", True, "", lambda: (_ for _ in ()).throw(requests.Timeout())),
        SourceSpec("working", True, "", lambda: ([{"id": "ok"}], 200, 1)),
    ]
    monkeypatch.setattr(job_sources, "source_specs", lambda terms: specs)
    reports = job_sources.fetch_sources([])
    assert [r.status for r in reports] == ["network_error", "searched"]
    assert reports[1].jobs == [{"id": "ok"}]


def test_database_source_backfill_is_idempotent_for_source_job_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "source-backfill.db")
    db.init_db()
    job = {
        **_job("stable-job-id"),
        "source_job_id": "native-source-id",
    }

    db.save_jobs([job])
    with db.connect() as con:
        before = con.execute(
            "SELECT source,source_job_id FROM job_source_records"
        ).fetchall()
    db.init_db()
    with db.connect() as con:
        after = con.execute(
            "SELECT source,source_job_id FROM job_source_records"
        ).fetchall()

    assert [tuple(row) for row in after] == [tuple(row) for row in before]
    assert [(row["source"], row["source_job_id"]) for row in before] == [
        ("Test", "native-source-id")
    ]


def test_location_and_remote_filtering():
    assert location_filter_reason({"location": "Bangalore, IN"})[0]
    assert location_filter_reason({"location": "Pune, Maharashtra, India"})[0]
    remote_missing = {"location": "", "description": "Fully remote position"}
    assert classify_work_mode(remote_missing) == "Remote"
    assert location_filter_reason(remote_missing)[0]
    assert not location_filter_reason({
        "location": "Toronto, Canada", "description": "Hybrid role"
    })[0]
    assert classify_work_mode({"description": "Remote work is not available"}) == "Not specified"
    unknown_hybrid = {"location": "", "description": "Hybrid role"}
    assert location_filter_reason(unknown_hybrid) == (
        True, "unknown location; manual review required"
    )


@pytest.mark.parametrize(
    "location",
    [
        "Electronic City, Bengaluru",
        "Whitefield, Bengaluru",
        "Marathahalli, Bengaluru",
        "Outer Ring Road, Bengaluru",
    ],
)
def test_bengaluru_area_filtering(location):
    assert location_filter_reason({"location": location}) == (True, "Bengaluru")


def test_freshness_uses_publication_date_windows():
    now = datetime(2026, 11, 11, 12, 0)
    assert freshness_window((now - timedelta(minutes=30)).isoformat(), now) == (1, "Last 1 hour")
    assert freshness_window((now - timedelta(hours=5)).isoformat(), now) == (2, "Last 24 hours")
    assert freshness_window((now - timedelta(days=2)).isoformat(), now) == (3, "Last 3 days")
    assert freshness_window((now - timedelta(days=14)).isoformat(), now) == (5, "Last 15 days")
    assert freshness_window((now - timedelta(days=45)).isoformat(), now) == (7, "Older than 30 days")
    assert freshness_window("not-a-date", now) == (8, "Date unknown")
    utc_now = now.replace(tzinfo=timezone.utc)
    assert freshness_window(
        str(int((utc_now - timedelta(minutes=10)).timestamp() * 1000)), utc_now
    ) == (
        1, "Last 1 hour"
    )


def test_search_terms_include_entry_level_roles_and_resume_skills():
    terms = generate_search_terms({
        "skills": [{"name": "Python", "status": "detected"},
                   {"name": "AWS EC2", "status": "detected"}]
    })
    joined = " | ".join(terms).lower()
    assert "graduate engineer trainee" in joined
    assert "associate software engineer" in joined
    assert "aws cloud support associate aws ec2 fresher" in joined
    assert "0-1 years" in joined
    assert " 0 years" in joined
    assert "remote india" in joined
    assert "qa engineer trainee" not in joined


@pytest.mark.parametrize("source,minutes", [("Adzuna", 15), ("Arbeitnow", 30)])
def test_source_refresh_intervals_respect_last_success(tmp_path, monkeypatch, source, minutes):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "source-state.db")
    db.init_db()
    now = datetime.now()
    db.update_source_refresh_state(
        source, "searched", succeeded=True,
        next_due_at=(now + timedelta(minutes=minutes)).isoformat(),
    )
    assert source not in db.sources_due({source: minutes}, now=now)
    assert db.sources_due({source: minutes}, now=now + timedelta(minutes=minutes + 1)) == [source]


def test_failed_source_is_retried_after_next_poll(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "source-retry.db")
    db.init_db()
    now = datetime.now()
    retry_at = now + timedelta(seconds=60)
    db.update_source_refresh_state(
        "Adzuna", "network_error", "simulated timeout", succeeded=False,
        next_due_at=retry_at.isoformat(timespec="seconds"),
    )
    assert db.sources_due({"Adzuna": 15}, now=now) == []
    assert db.sources_due({"Adzuna": 15}, now=retry_at + timedelta(seconds=1)) == ["Adzuna"]
    assert db.get_source_refresh_state()["Adzuna"]["last_successful_at"] is None


def test_scheduler_search_tick_updates_next_poll_and_runs_search(monkeypatch):
    calls = []
    import scheduler
    monkeypatch.setattr(scheduler, "set_next_scheduled_search", lambda value: calls.append(("next", value)))
    monkeypatch.setattr(scheduler, "run_search", lambda force=False: calls.append(("search", force)))
    scheduler._scheduled_search()
    assert calls[0][0] == "next"
    assert calls[1] == ("search", False)


def test_scheduler_singleton_lock_and_nonoverlapping_poll_job(tmp_path, monkeypatch):
    import scheduler
    monkeypatch.setattr(scheduler, "DB_PATH", tmp_path / "schedule.db")
    first_lock = scheduler._acquire_singleton_lock()
    assert first_lock is not None
    try:
        assert scheduler._acquire_singleton_lock() is None
    finally:
        first_lock.close()

    scheduled = scheduler.create_scheduler(lambda: None, poll_seconds=60)
    poll = scheduled.get_job("jobpilot_source_poll")
    assert poll is not None
    assert poll.trigger.interval.total_seconds() == 60
    assert poll.max_instances == 1
    assert scheduled.get_job("daily_jobpilot_agent") is not None


def test_search_process_lock_rejects_overlap(tmp_path, monkeypatch):
    monkeypatch.setattr(run_search, "DB_PATH", tmp_path / "jobpilot.db")
    with run_search._search_process_lock():
        with pytest.raises(RuntimeError, match="already running"):
            with run_search._search_process_lock():
                pass


def test_search_run_persists_and_reports_source_counts(tmp_path, monkeypatch):
    database_path = tmp_path / "run.db"
    monkeypatch.setattr(db, "DB_PATH", database_path)
    monkeypatch.setattr(run_search, "DB_PATH", database_path)
    monkeypatch.setattr(run_search, "SOURCE_REFRESH_MINUTES", {"Test": 15})
    monkeypatch.setattr(run_search, "master_resume_profile", lambda: {"skills": []})
    monkeypatch.setattr(run_search, "generate_search_terms", lambda profile: ["Python trainee"])
    spec = SourceSpec("Test", True, "", lambda: ([], 200, 1))
    monkeypatch.setattr(run_search, "source_specs", lambda terms: [spec])
    monkeypatch.setattr(run_search, "fetch_sources", lambda terms, only_sources=None: [
        SourceReport("Test", True, "searched", True, 200, 1, jobs=[_job()])
    ])
    monkeypatch.setattr(run_search, "enrich", lambda job, profile: job)

    report = run_search.run_search(force=True, print_report=False, return_report=True)
    assert report["status"] == "success"
    assert report["sources_searched"] == 1
    assert report["jobs_after_filtering"] == 1
    assert report["new_jobs"] == 1
    assert report["new_job_ids"] == ["id-1"]
    with db.connect() as con:
        row = con.execute(
            "SELECT id,first_discovered_at,original_posted_at,last_checked_at "
            "FROM jobs").fetchone()
        run = con.execute(
            "SELECT started_at,completed_at FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["id"] == "id-1"
        assert row["first_discovered_at"] and row["last_checked_at"]
        assert row["original_posted_at"] == _job()["posted"]
        assert run["started_at"] <= row["first_discovered_at"] <= run["completed_at"]


def test_search_rejects_non_target_and_senior_jobs(tmp_path, monkeypatch):
    database_path = tmp_path / "filter-run.db"
    monkeypatch.setattr(db, "DB_PATH", database_path)
    monkeypatch.setattr(run_search, "DB_PATH", database_path)
    monkeypatch.setattr(run_search, "SOURCE_REFRESH_MINUTES", {"Test": 15})
    monkeypatch.setattr(run_search, "master_resume_profile", lambda: {
        "skills": [{"name": skill, "status": "verified"}
                   for skill in ["AWS", "Linux", "Python", "Terraform"]],
        "education": ["B.E. Computer Science and Engineering"],
        "experience": [], "experience_level": "Fresher",
        "summary": [], "projects": [], "training": [],
    })
    monkeypatch.setattr(run_search, "generate_search_terms", lambda profile: ["Platform Engineer Trainee"])
    spec = SourceSpec("Test", True, "", lambda: ([], 200, 1))
    monkeypatch.setattr(run_search, "source_specs", lambda terms: [spec])
    jobs = [
        {
            **_job("entry"),
            "title": "Platform Engineer Trainee",
            "description": "0 years experience required. AWS, Linux, and Terraform.",
        },
        {
            **_job("senior"),
            "title": "Senior Platform Engineer",
            "description": "Requires 6 years of professional experience with AWS, Linux, and Terraform.",
        },
        {
            **_job("unrelated"),
            "title": "Senior Accountant",
            "description": "Finance role requiring 6 years of experience.",
        },
    ]
    monkeypatch.setattr(run_search, "fetch_sources", lambda terms, only_sources=None: [
        SourceReport("Test", True, "searched", True, 200, len(jobs), jobs=jobs)
    ])

    report = run_search.run_search(force=True, print_report=False, return_report=True)

    assert report["jobs_after_filtering"] == 1
    assert report["sources"][0]["rejected_by_experience"] == 1
    assert report["sources"][0]["rejected_by_role"] == 1
    assert report["new_jobs"] == 1
    with db.connect() as con:
        assert con.execute("SELECT title FROM jobs").fetchone()["title"] == "Platform Engineer Trainee"


def test_duplicate_url_preserves_job_id_and_application_status(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    db.init_db()
    first = _job()
    assert db.save_jobs([first]) == 1
    with db.connect() as con:
        con.execute(
            "INSERT INTO applications(job_id,company,title,url,status,detail) "
            "VALUES(?,?,?,?,?,?)",
            (first["id"], "Example", first["title"], first["url"], "Approved", "preserve"),
        )

    duplicate = _job("different-source-id", "OtherSource",
                     "https://jobs.example/jobs/1?utm_source=tracking")
    result = db.save_jobs([duplicate], return_details=True)
    assert result == {"new": 0, "updated": 0, "duplicates": 1, "new_job_ids": []}
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert tuple(con.execute("SELECT id,status FROM applications").fetchone()) == (1, "Approved")
        assert con.execute("SELECT COUNT(*) FROM job_source_tracking").fetchone()[0] == 2


def test_additive_migration_preserves_existing_records(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT, "
                    "url TEXT, description TEXT, source TEXT, posted TEXT, match_score INTEGER, "
                    "matched_skills TEXT, status TEXT, discovered_at TEXT)")
        con.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY, job_id TEXT UNIQUE, "
                    "company TEXT, title TEXT, url TEXT, status TEXT, detail TEXT, applied_at TEXT)")
        con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, started_at TEXT, jobs_found INTEGER, "
                    "new_jobs INTEGER, message TEXT)")
        con.execute("INSERT INTO jobs VALUES('stable-id','Title','Co','India','u','d','src','p',70,'Python','New','2026-11-01')")
        con.execute("INSERT INTO applications VALUES(4,'stable-id','Co','Title','u','Submitted','done','2026-11-01')")
        con.execute("INSERT INTO runs VALUES(3,'2026-11-01',1,1,'legacy')")

    db.init_db()
    with db.connect() as con:
        assert tuple(con.execute("SELECT id,status FROM jobs").fetchone()) == ("stable-id", "New")
        assert tuple(con.execute("SELECT id,status FROM applications").fetchone()) == (4, "Submitted")
        assert tuple(con.execute("SELECT id,message FROM runs").fetchone()) == (3, "legacy")
        assert con.execute("SELECT first_discovered_at FROM jobs").fetchone()[0] == "2026-11-01"
