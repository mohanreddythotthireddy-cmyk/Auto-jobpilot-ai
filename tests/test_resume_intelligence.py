import sqlite3
from pathlib import Path

import pytest

from resume_intelligence import ResumeIntelligenceDB, infer_experience_level, summarize
from resume_parser import parse_resume_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.md"


@pytest.fixture
def setup(tmp_path):
    resume = tmp_path / "master_resume.md"
    resume.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return ResumeIntelligenceDB(tmp_path / "t.db"), resume


def names(p):
    return {s["name"] for s in p["skills"]}


def test_migration_preserves_existing_tables_and_rows(tmp_path):
    db_file = tmp_path / "existing.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, title TEXT)")
    con.execute("INSERT INTO jobs (title) VALUES ('Existing Job')")
    con.execute("CREATE TABLE applications (id INTEGER PRIMARY KEY, status TEXT)")
    con.execute("INSERT INTO applications (status) VALUES ('approved')")
    con.commit(); con.close()
    ResumeIntelligenceDB(db_file)
    ResumeIntelligenceDB(db_file)  # idempotent
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT title FROM jobs").fetchall() == [("Existing Job",)]
    assert con.execute("SELECT status FROM applications").fetchall() == [("approved",)]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ri_skills", "ri_skill_sources", "ri_corrections", "ri_resume_versions"} <= tables
    assert con.execute("SELECT COUNT(*) FROM ri_migrations").fetchone()[0] == 1


def test_refresh_stores_full_profile(setup):
    db, resume = setup
    status, _ = db.refresh_from_resume(resume)
    assert status == "created"
    p = db.get_profile()
    assert p["resume"]["name"] == "Test Candidate"
    assert {"Python", "AWS S3", "Docker", "Quantum Widget Toolkit"} <= names(p)
    assert len(p["projects"]) == 2 and p["certifications"] == ["AWS Certified Cloud Practitioner"]
    assert any("Computer Science" in e for e in p["education"])
    s3 = next(s for s in p["skills"] if s["name"] == "AWS S3")
    assert "Amazon Simple Storage Service" in s3["original_forms"]
    assert "Cloud Inventory Tracker" in s3["projects"]
    assert all(s["sources"] for s in p["skills"])
    assert "Quantum Widget Toolkit" in " ".join(p["missing_unclear"])


def test_unchanged_file_not_reparsed_changed_file_is(setup):
    db, resume = setup
    assert db.refresh_from_resume(resume)[0] == "created"
    assert db.refresh_from_resume(resume)[0] == "unchanged"
    resume.write_text(resume.read_text(encoding="utf-8") + "\n- Also used Jenkins in Training.\n", encoding="utf-8")
    assert db.refresh_from_resume(resume)[0] == "created"
    with sqlite3.connect(db.path) as c:
        assert c.execute("SELECT COUNT(*) FROM ri_resume_versions WHERE is_active=1").fetchone()[0] == 1


def test_master_resume_never_modified(setup):
    db, resume = setup
    before = (resume.read_bytes(), resume.stat().st_mtime_ns)
    db.refresh_from_resume(resume, force=True)
    db.add_correction("remove", "Python")
    db.get_profile()
    assert (resume.read_bytes(), resume.stat().st_mtime_ns) == before


def test_rename_recategorize_remove(setup):
    db, resume = setup
    db.refresh_from_resume(resume)
    db.add_correction("rename", "Quantum Widget Toolkit", new_name="Quantum Widget Kit")
    db.add_correction("recategorize", "Flask", new_category="Development Tools")
    db.add_correction("remove", "Ubuntu")
    p = db.get_profile()
    assert "Quantum Widget Kit" in names(p) and "Quantum Widget Toolkit" not in names(p)
    q = next(s for s in p["skills"] if s["name"] == "Quantum Widget Kit")
    assert q["status"] == "corrected" and "Quantum Widget Toolkit" in q["original_forms"] and q["sources"]
    assert next(s for s in p["skills"] if s["name"] == "Flask")["category"] == "Development Tools"
    assert "Ubuntu" not in names(p) and [s["name"] for s in p["removed_skills"]] == ["Ubuntu"]


def test_corrections_survive_reparse_and_can_be_undone(setup):
    db, resume = setup
    db.refresh_from_resume(resume)
    db.add_correction("remove", "Ubuntu")
    db.refresh_from_resume(resume, force=True)
    assert "Ubuntu" not in names(db.get_profile())
    db.delete_correction(db.list_corrections()[0]["id"])
    assert "Ubuntu" in names(db.get_profile())


def test_manual_skill_flagged_and_original_unchanged(setup):
    db, resume = setup
    db.refresh_from_resume(resume)
    db.add_correction("add", "Kubernetes", new_category="DevOps Tools", note="Added manually; user-confirmed")
    p = db.get_profile()
    k = next(s for s in p["skills"] if s["name"] == "Kubernetes")
    assert k["status"] == "manual" and k["sources"][0]["section_kind"] == "manual"
    assert "Kubernetes" not in resume.read_text(encoding="utf-8")
    assert "Kubernetes" in p["keywords"]


def test_orphaned_correction_reported(setup):
    db, resume = setup
    db.refresh_from_resume(resume)
    db.add_correction("remove", "Not A Real Skill")
    p = db.get_profile()
    assert len(p["orphaned_corrections"]) == 1
    assert any("no longer match" in m for m in p["missing_unclear"])


def test_summary_counts(setup):
    db, resume = setup
    db.refresh_from_resume(resume)
    s = summarize(db.get_profile())
    assert s["Programming languages"] == 6          # Python Java JavaScript C C++ SQL
    assert s["Cloud technologies"] == 6             # AWS + EC2 S3 IAM VPC RDS
    assert s["Database technologies"] == 2          # MySQL SQLite
    assert s["Certifications"] == 1 and s["Education entries"] == 2
    assert s["Total skills detected"] == len(db.get_profile()["skills"])


def test_experience_level_inference():
    f = lambda t: infer_experience_level(parse_resume_text(t))
    assert "no work experience" in f("## Skills\nPython\n")
    assert "internship" in f("## Experience\n**Cloud Intern** - X\n- did things\n")
    assert "3 year" in f("## Experience\n- 3 years at Acme\n")


def test_no_profile_before_parse(tmp_path):
    assert ResumeIntelligenceDB(tmp_path / "e.db").get_profile() is None
