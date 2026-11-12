import sqlite3

import pytest

import db
from duplicate_detection import (
    duplicate_match,
    normalize_company,
    normalize_location,
    normalize_title,
)


@pytest.fixture
def dedup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dedup.db")
    db.init_db()
    return db


def job(
    job_id,
    source,
    *,
    title="Senior Software Engineer, Cloud",
    company="Acme Technologies Pvt. Ltd.",
    location="Bangalore, IN",
    url=None,
    description="Build cloud services with Python, APIs, distributed systems, and AWS.",
):
    return {
        "id": job_id,
        "source_job_id": f"{source}-{job_id}",
        "source": source,
        "title": title,
        "company": company,
        "location": location,
        "url": url or f"https://{source.lower()}.example/jobs/{job_id}",
        "description": description,
        "posted": "2026-11-11T00:00:00+00:00",
        "match_score": 60,
        "matched_skills": ["Python"],
        "work_mode": "On-site",
    }


def test_text_normalization_removes_case_spacing_punctuation_and_company_suffixes():
    assert normalize_company("  Acme, Inc. ") == "acme"
    assert normalize_company("ACME Private Limited") == "acme"
    assert normalize_title("Senior Software-Engineer, Cloud!") == "senior software engineer cloud"
    assert normalize_location("Bangalore, Karnataka, India") == normalize_location(
        "Bengaluru / IN"
    )


def test_same_job_with_different_urls_is_grouped_and_urls_preserved(dedup_db):
    first = job("a1", "Adzuna", url="https://ads.example/jobs/123?utm_source=x")
    second = job("b2", "Arbeitnow", title="Senior Software Engineer Cloud",
                 company="ACME Inc", location="Bengaluru, Karnataka, India",
                 url="https://arbeitnow.example/jobs/456")
    assert dedup_db.save_jobs([first]) == 1
    result = dedup_db.save_jobs([second], return_details=True)
    assert result["new"] == 0 and result["duplicates"] == 1

    listings = dedup_db.get_jobs()
    assert len(listings) == 1
    assert set(listings[0]["sources"]) == {"Adzuna", "Arbeitnow"}
    assert {record["url"] for record in listings[0]["source_records"]} == {
        first["url"], second["url"]
    }
    with dedup_db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM job_source_records").fetchone()[0] == 2


def test_same_job_with_slightly_different_title_and_description_is_grouped():
    first = job("one", "Greenhouse", title="Senior Software Engineer Cloud")
    second = job(
        "two", "Lever", title="Senior Cloud Software Engineer",
        description="Build AWS cloud services and distributed APIs using Python.",
    )
    is_duplicate, reason = duplicate_match(first, second)
    assert is_duplicate
    assert "description=" in reason


@pytest.mark.parametrize("source", ["Arbeitnow", "Greenhouse", "Lever", "Ashby", "USAJOBS"])
def test_same_job_across_supported_source_portals(dedup_db, source):
    first = job("existing", "Adzuna")
    second = job(
        "incoming", source, title="Senior Cloud Software Engineer",
        company="Acme, Inc.", location="Bengaluru Karnataka India",
        description="Build cloud services with Python, APIs, distributed systems, and AWS.",
    )
    dedup_db.save_jobs([first])
    assert dedup_db.save_jobs([second]) == 0
    assert len(dedup_db.get_jobs()) == 1
    assert source in dedup_db.get_jobs()[0]["sources"]


def test_different_vacancies_at_same_company_are_not_merged(dedup_db):
    first = job("engineer", "Adzuna")
    different = job(
        "analyst", "Ashby", title="Quality Assurance Analyst",
        description="Write test plans, execute regression tests, and report software defects.",
    )
    dedup_db.save_jobs([first])
    assert dedup_db.save_jobs([different]) == 1
    assert len(dedup_db.get_jobs()) == 2


def test_same_vacancy_in_different_locations_is_not_merged(dedup_db):
    first = job("blr", "Adzuna", location="Bengaluru, India")
    different = job("pune", "Lever", location="Pune, India")
    dedup_db.save_jobs([first])
    assert dedup_db.save_jobs([different]) == 1
    assert len(dedup_db.get_jobs()) == 2


def test_same_remote_title_in_different_countries_is_not_merged():
    first = job("us", "Greenhouse", location="Remote, United States")
    second = job("india", "Lever", location="Remote, India")
    assert not duplicate_match(first, second)[0]


def test_missing_descriptions_require_very_close_title_match():
    first = job("one", "Greenhouse", description="")
    same = job("two", "Lever", title="Senior Software Engineer Cloud", description="")
    distinct = job("three", "Ashby", title="Senior QA Engineer Cloud", description="")
    assert duplicate_match(first, same)[0]
    assert not duplicate_match(first, distinct)[0]
    same["posted"] = ""
    first["posted"] = ""
    assert not duplicate_match(first, same)[0]


def test_repeated_scheduler_refreshes_do_not_add_duplicate_jobs(dedup_db):
    incoming = job("first", "Adzuna")
    cross_source = job(
        "second", "Arbeitnow", title="Senior Cloud Software Engineer",
        description="Build cloud services with Python, APIs, distributed systems, and AWS.",
    )
    assert dedup_db.save_jobs([incoming]) == 1
    assert dedup_db.save_jobs([cross_source]) == 0
    assert dedup_db.save_jobs([cross_source]) == 0
    assert dedup_db.get_duplicate_stats()["unique_jobs"] == 1
    assert len(dedup_db.get_jobs()) == 1


def test_existing_duplicates_are_grouped_without_deleting_records_or_history(tmp_path, monkeypatch):
    path = tmp_path / "existing.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as con:
        con.execute(
            "CREATE TABLE jobs (id TEXT PRIMARY KEY,title TEXT,company TEXT,location TEXT,url TEXT,"
            "description TEXT,source TEXT,posted TEXT,match_score INTEGER,matched_skills TEXT,"
            "status TEXT,discovered_at TEXT)"
        )
        con.execute(
            "CREATE TABLE applications (id INTEGER PRIMARY KEY,job_id TEXT UNIQUE,company TEXT,"
            "title TEXT,url TEXT,status TEXT,detail TEXT,applied_at TEXT)"
        )
        con.execute(
            "CREATE TABLE runs (id INTEGER PRIMARY KEY,started_at TEXT,jobs_found INTEGER,"
            "new_jobs INTEGER,message TEXT)"
        )
        con.executemany(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("old-a", "Senior Software Engineer Cloud", "Acme Inc", "Bangalore, IN",
                 "https://a.example/1", "Build AWS services and distributed APIs with Python.",
                 "Adzuna", "2026-11-01", 70, "Python", "New", "2026-11-01"),
                ("old-b", "Senior Cloud Software Engineer", "ACME Limited",
                 "Bengaluru Karnataka India", "https://b.example/2",
                 "Build AWS services and distributed APIs with Python.",
                 "Lever", "2026-11-02", 75, "Python", "Shortlisted", "2026-11-02"),
            ],
        )
        con.execute(
            "INSERT INTO applications VALUES(1,'old-b','ACME','Senior Cloud Software Engineer',"
            "'https://b.example/2','Approved','preserve','2026-11-02')"
        )
        con.execute("INSERT INTO runs VALUES(1,'2026-11-02',2,2,'preserve')")

    db.init_db()
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 2
        assert con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert tuple(con.execute("SELECT id,status FROM applications").fetchone()) == (1, "Approved")
        assert con.execute("SELECT canonical_job_id FROM jobs WHERE id='old-b'").fetchone()[0] == "old-a"
    assert len(db.get_jobs()) == 1
    assert db.get_duplicate_stats()["duplicate_rows_grouped"] == 1
    assert "https://b.example/2" in {
        record["url"] for record in db.get_jobs()[0]["source_records"]
    }


def test_application_lookup_and_queue_are_group_aware(dedup_db):
    first = job("root", "Adzuna")
    second = job("alias", "Lever", title="Senior Cloud Software Engineer")
    dedup_db.save_jobs([first])
    with dedup_db.connect() as con:
        normalized = {
            "canonical_job_id": "alias",
            "normalized_company": "acme",
            "normalized_title": "senior cloud software engineer",
            "normalized_location": "bengaluru",
        }
        con.execute(
            "INSERT INTO jobs(id,title,company,location,url,description,source,posted,match_score,"
            "matched_skills,status,discovered_at,canonical_job_id,normalized_company,"
            "normalized_title,normalized_location) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (second["id"], second["title"], second["company"], second["location"], second["url"],
             second["description"], second["source"], second["posted"], second["match_score"],
             "Python", "New", "2026-11-11", normalized["canonical_job_id"],
             normalized["normalized_company"], normalized["normalized_title"],
             normalized["normalized_location"]),
        )
        con.execute(
            "INSERT INTO applications(job_id,company,title,url,status,detail) "
            "VALUES('alias','Acme','Senior Cloud Software Engineer','url','Approved','keep')"
        )
    dedup_db.init_db()
    assert dedup_db.get_application("root")["status"] == "Approved"
    dedup_db.queue_application(dedup_db.get_jobs()[0], "resume.pdf")
    with dedup_db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
