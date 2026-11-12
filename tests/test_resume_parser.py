from pathlib import Path

import pytest

from resume_parser import parse_resume, parse_resume_text, read_resume_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.md"


def test_contact_details():
    r = parse_resume(FIXTURE)
    assert r.name == "Test Candidate"
    assert r.email == "test.candidate@example.com"
    assert r.phone.replace(" ", "") == "+919876543210"
    assert any("github.com/testcandidate" in l for l in r.links)
    assert any("linkedin.com" in l for l in r.links)


def test_sections_detected():
    r = parse_resume(FIXTURE)
    kinds = {b.kind for b in r.blocks}
    assert {"summary", "skills", "education", "certifications", "projects",
            "experience", "training"} <= kinds
    assert r.warnings == []


def test_education_certs_projects():
    r = parse_resume(FIXTURE)
    assert any("Computer Science" in e for e in r.education)
    assert r.certifications == ["AWS Certified Cloud Practitioner"]
    assert [p.name for p in r.projects] == ["Cloud Inventory Tracker", "Log Analytics Pipeline"]
    assert r.projects[0].technologies_raw == ["Python, Flask, MySQL, Docker"]
    assert r.projects[1].technologies_raw == ["PySpark, Pandas, NumPy"]
    assert any("Simple Storage Service" in d for d in r.projects[0].description)


def test_pre_university_course_stays_in_education_section():
    from config import MASTER_RESUME

    r = parse_resume(MASTER_RESUME)
    assert any("Pre-University Course" in entry for entry in r.education)
    assert any("Narayana College" in entry for entry in r.education)
    assert not any("Narayana College" in entry for entry in r.training)


def test_missing_info_warnings():
    r = parse_resume_text("Jane Doe\n\n## Skills\nPython\n")
    assert "Email not detected" in r.warnings
    assert "No Education section detected" in r.warnings
    assert "No Projects section detected" in r.warnings


def test_plain_text_headings_like_pdf():
    text = "Jane Doe\njane@x.com\nTECHNICAL SKILLS\nPython, Docker\nPROJECTS\nBuilt a bot with Selenium\n"
    r = parse_resume_text(text)
    assert {b.kind for b in r.blocks} >= {"skills", "projects"}


def test_master_resume_never_modified(tmp_path):
    p = tmp_path / "master_resume.md"
    p.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    before = (p.read_bytes(), p.stat().st_mtime_ns)
    parse_resume(p)
    assert (p.read_bytes(), p.stat().st_mtime_ns) == before


def test_docx_upload(tmp_path):
    import docx
    d = docx.Document()
    d.add_heading("Jane Doe", level=1)
    d.add_paragraph("jane@example.com")
    d.add_heading("Skills", level=2)
    d.add_paragraph("Languages: Python, Go")
    d.add_heading("Projects", level=2)
    d.add_heading("Chat App", level=3)
    d.add_paragraph("Technologies: Firebase, Kotlin")
    p = tmp_path / "r.docx"
    d.save(p)
    r = parse_resume(p)
    assert r.name == "Jane Doe" and r.email == "jane@example.com"
    assert r.projects[0].name == "Chat App"
    assert "Firebase" in r.projects[0].technologies_raw[0]


def test_pdf_upload(tmp_path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    p = tmp_path / "r.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    y = 800
    for line in ["Jane Doe", "jane@example.com", "SKILLS", "Languages: Python, Java", "PROJECTS", "Technologies: Docker"]:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    r = parse_resume(p)
    assert r.email == "jane@example.com"
    assert {b.kind for b in r.blocks} >= {"skills", "projects"}


def test_unsupported_and_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_resume_text(tmp_path / "nope.md")
    f = tmp_path / "x.rtf"
    f.write_text("x")
    with pytest.raises(ValueError):
        read_resume_text(f)
