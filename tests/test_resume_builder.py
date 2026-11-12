import sqlite3
from pathlib import Path

from pypdf import PdfReader

import resume_builder


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "master_resume.md"


def platform_job():
    return {
        "id": "platform-trainee-test",
        "company": "Example Platform",
        "title": "Platform Engineer | Trainee",
        "description": (
            "Build and support platform infrastructure using AWS, IAM, S3, "
            "Terraform, Python, Linux, Git/GitHub, and CI/CD. Ansible and "
            "Kubernetes are also listed as optional requirements."
        ),
    }


def test_builds_complete_selectable_tailored_pdf_without_changing_master(tmp_path, monkeypatch):
    output_dir = tmp_path / "resumes"
    monkeypatch.setattr(resume_builder, "RESUME_DIR", output_dir)
    before_bytes = MASTER.read_bytes()
    before_modified = MASTER.stat().st_mtime_ns

    pdf_path = resume_builder.build_resume(platform_job())
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert pdf_path.is_file() and pdf_path.stat().st_size > 0
    assert 1 <= len(reader.pages) <= 2
    assert "THOTHIREDDY MOHANREDDY" in text
    assert "+91 7569792989" in text
    assert "mohanreddythotthireddy@gmail.com" in text
    assert "linkedin.com/in/mohanreddythotthireddyaa6944370" in text
    assert "github.com" not in text
    assert "PROFESSIONAL SUMMARY" in text
    assert "TECHNICAL SKILLS" in text
    assert "PROJECTS" in text
    assert "EDUCATION" in text
    assert "CERTIFICATIONS" in text
    assert "TRAINING" in text
    assert "Student Management System" in text
    assert "Production-Ready AWS Infrastructure Platform" in text
    assert text.index("Production-Ready AWS Infrastructure Platform") < text.index("Student Management System")
    assert "Cambridge Institute of Technology" in text
    assert "PySpiders Institute" in text
    assert "Terraform" in text and "AWS IAM" in text and "S3" in text
    assert "Ansible" not in text and "Kubernetes" not in text
    assert "Role alignment" not in text
    assert "Keyword match score" not in text
    assert "verified from master resume" not in text
    assert MASTER.read_bytes() == before_bytes
    assert MASTER.stat().st_mtime_ns == before_modified


def test_internship_is_rendered_when_present_in_master_resume(tmp_path, monkeypatch):
    fixture = ROOT / "tests" / "fixtures" / "sample_resume.md"
    monkeypatch.setattr(resume_builder, "MASTER_RESUME", fixture)
    monkeypatch.setattr(resume_builder, "RESUME_DIR", tmp_path / "resumes")

    pdf_path = resume_builder.build_resume({
        "id": "experience-test",
        "company": "Example",
        "title": "Cloud Engineer Trainee",
        "description": "Cloud Engineer trainee using AWS, Linux, and Git.",
    })
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)

    assert "INTERNSHIP / EXPERIENCE" in text
    assert "Cloud Intern" in text


def test_resume_generation_preserves_existing_database_records(tmp_path, monkeypatch):
    database = tmp_path / "existing.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO jobs VALUES ('job-1', 'Saved job')")
        connection.execute("CREATE TABLE applications (job_id TEXT, status TEXT)")
        connection.execute("INSERT INTO applications VALUES ('job-1', 'PendingApproval')")
        before = (
            connection.execute("SELECT * FROM jobs").fetchall(),
            connection.execute("SELECT * FROM applications").fetchall(),
        )

    monkeypatch.setattr(resume_builder, "RESUME_DIR", tmp_path / "resumes")
    resume_builder.build_resume(platform_job())

    with sqlite3.connect(database) as connection:
        after = (
            connection.execute("SELECT * FROM jobs").fetchall(),
            connection.execute("SELECT * FROM applications").fetchall(),
        )
    assert after == before
