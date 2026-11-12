from datetime import datetime
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.md"
SCRIPT = "import resume_intelligence_page as p\np.render()\n"


def make(tmp_path, monkeypatch):
    resume = tmp_path / "master_resume.md"
    resume.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("JOBPILOT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("JOBPILOT_MASTER_RESUME", str(resume))
    return resume


def test_page_renders_metrics_and_tabs(tmp_path, monkeypatch):
    resume = make(tmp_path, monkeypatch)
    before = resume.read_bytes()
    at = st_testing.AppTest.from_string(SCRIPT, default_timeout=30).run()
    assert not at.exception
    labels = {m.label: m.value for m in at.metric}
    assert labels["Total skills detected"] != "0"
    assert labels["Certifications"] == "1"
    assert len(at.tabs) == 6
    assert resume.read_bytes() == before


def test_page_manual_remove_correction(tmp_path, monkeypatch):
    make(tmp_path, monkeypatch)
    at = st_testing.AppTest.from_string(SCRIPT, default_timeout=30).run()
    total = int(next(m.value for m in at.metric if m.label == "Total skills detected"))
    at.selectbox(key="rm_old").select("Ubuntu")
    next(b for b in at.button if b.label == "Remove").click()
    at.run()
    assert not at.exception
    assert int(next(m.value for m in at.metric if m.label == "Total skills detected")) == total - 1


def test_page_without_resume_shows_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBPILOT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("JOBPILOT_MASTER_RESUME", str(tmp_path / "missing.md"))
    at = st_testing.AppTest.from_string(SCRIPT, default_timeout=30).run()
    assert not at.exception and at.warning


def test_dashboard_shows_scheduler_refresh_times(tmp_path, monkeypatch):
    import config
    import db
    import resume_profile_service

    database = tmp_path / "dashboard.db"
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "ACTIVE_RESUME_PATH", FIXTURE)
    db.init_db()
    db.log_run(2, 1, "test refresh", status="success")
    db.set_search_schedule_state(
        "2026-11-11T22:00:00", "2099-01-01T00:01:00", 60
    )

    app = Path(__file__).resolve().parents[1] / "app.py"
    at = st_testing.AppTest.from_file(str(app), default_timeout=45).run()
    assert not at.exception
    captions = [item.value for item in at.caption]
    assert any("Last successful refresh:" in value for value in captions)
    assert any("Next scheduled refresh poll:" in value for value in captions)


def test_dashboard_lists_unique_jobs_and_duplicate_count(tmp_path, monkeypatch):
    import config
    import db
    import resume_profile_service

    database = tmp_path / "dashboard-dedup.db"
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "ACTIVE_RESUME_PATH", FIXTURE)
    db.init_db()

    first = {
        "id": "dashboard-one", "source_job_id": "one", "source": "Adzuna",
        "title": "Graduate Engineer Trainee", "company": "Acme Inc",
        "location": "Bangalore, IN", "url": "https://a.example/jobs/1",
        "description": "Build software services and APIs using Python.",
        "match_score": 80, "matched_skills": ["Python"], "work_mode": "On-site",
    }
    second = {
        **first, "id": "dashboard-two", "source_job_id": "two",
        "source": "Lever", "title": "Graduate Software Engineer Trainee",
        "company": "Acme Private Limited", "location": "Bengaluru, India",
        "url": "https://b.example/jobs/2",
    }
    cycle_started = datetime.now().isoformat(timespec="seconds")
    assert db.save_jobs([first, second]) == 1
    db.log_run(
        1, 1, "test discovery",
        status="success",
        details={"new_jobs": 1, "new_job_ids": ["dashboard-one"]},
        started_at=cycle_started,
    )
    assert db.get_duplicate_stats()["duplicate_source_records"] == 1
    assert len(db.get_jobs()) == 1

    app = Path(__file__).resolve().parents[1] / "app.py"
    at = st_testing.AppTest.from_file(str(app), default_timeout=45).run()
    assert not at.exception
    metrics = {item.label: item.value for item in at.metric}
    assert int(metrics["Total unique jobs"]) == 1
    assert int(metrics["New jobs this cycle"]) == 1
    assert int(metrics["Duplicate listings grouped"]) == 1
    tabs = {item.label for item in at.tabs}
    assert {
        "Bengaluru Fresher Jobs",
        "Newly Discovered India Jobs",
        "Jobs posted in the last 24 hours",
        "Jobs posted in the last 7 days",
        "Other Indian City Jobs",
        "Remote India Jobs",
        "Excellent and Strong Resume Matches",
        "Good Matches",
        "Internships",
        "Unknown Location / Manual Review",
        "Previously Discovered Jobs",
    }.issubset(tabs)
    assert {item.label for item in at.slider} >= {"Match score range"}
    assert {item.label for item in at.selectbox} >= {"Required experience", "Job type", "Source"}
    assert any("Open original job posting" in item.value for item in at.markdown)


def test_dashboard_generates_tailored_pdf_for_selected_job(tmp_path, monkeypatch):
    import config
    import db
    import resume_builder
    import resume_profile_service

    database = tmp_path / "dashboard-resume.db"
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "DB_PATH", database)
    monkeypatch.setattr(resume_profile_service, "ACTIVE_RESUME_PATH", FIXTURE)
    monkeypatch.setattr(resume_builder, "RESUME_DIR", tmp_path / "generated")
    db.init_db()
    job = {
        "id": "platform-trainee-dashboard",
        "source_job_id": "platform-trainee-dashboard",
        "source": "Test",
        "title": "Platform Engineer | Trainee",
        "company": "Example Platform",
        "location": "Bengaluru",
        "url": "https://example.com/jobs/platform-trainee",
        "description": "Use AWS S3, Python, Linux, and Terraform.",
        "match_score": 80,
        "matched_skills": ["AWS S3", "Python", "Linux", "Terraform"],
        "work_mode": "On-site",
    }
    db.save_jobs([job])

    app = Path(__file__).resolve().parents[1] / "app.py"
    at = st_testing.AppTest.from_file(str(app), default_timeout=45).run()
    assert not at.exception
    assert any("Selected target job: Platform Engineer | Trainee" in item.value for item in at.subheader)
    generate = next(item for item in at.button if item.label == "Generate Tailored Resume (PDF)")
    generate.click()
    at.run()

    assert not at.exception
    assert any(item.label == "Download tailored resume (PDF)" for item in at.get("download_button"))
    assert list((tmp_path / "generated").glob("*.pdf"))
