from __future__ import annotations

import html
import re
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from config import MASTER_RESUME, RESUME_DIR
from resume_parser import ParsedResume, parse_resume_text, read_resume_text


NAVY = colors.HexColor("#17365D")
DARK_GREY = colors.HexColor("#343A40")
LIGHT_GREY = colors.HexColor("#AAB4C0")
_WORD_RE = re.compile(r"[a-z0-9+#./-]+", re.I)
_LIST_PREFIX_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")


def _safe_name(value: object, fallback: str) -> str:
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "_", str(value or fallback))[:48].strip("_")
        or fallback
    )


def _plain_line(line: str) -> str:
    return _LIST_PREFIX_RE.sub("", line.strip())


def _rich_text(text: str) -> str:
    text = (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
    )
    escaped = html.escape(text, quote=False)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped)
    return escaped


def _relevance(text: str, job_text: str) -> int:
    return len(set(_WORD_RE.findall(text.lower())) & set(_WORD_RE.findall(job_text.lower())))


def _contact_details(resume: ParsedResume) -> list[str]:
    contact = []
    header = resume.blocks[0].lines if resume.blocks else []
    for line in header:
        candidate = line.strip()
        if candidate == resume.name:
            continue
        candidate = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "", candidate)
        candidate = re.sub(
            r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,11}\d(?!\w)",
            "",
            candidate,
        )
        candidate = re.sub(r"(?:https?://|www\.)\S+|(?:linkedin|github)\.com/\S+", "", candidate, flags=re.I)
        location = candidate.strip(" |,")
        if location and len(location) <= 70 and location.lower() not in {"linkedin:", "github:"}:
            contact.append(location)
            break
    if resume.phone:
        contact.append(resume.phone)
    if resume.email:
        contact.append(resume.email)
    for link in resume.links:
        lower = link.lower()
        if "linkedin.com/" in lower or "github.com/" in lower:
            contact.append(link)
    return list(dict.fromkeys(contact))


def _targeted_summary(resume: ParsedResume, job: dict, job_text: str) -> str:
    source_summary = " ".join(_plain_line(line) for line in resume.summary).strip()
    title = (job.get("title") or "the selected role").strip()
    if source_summary:
        return re.sub(
            r"^Entry[- ]level\b.*?\bwith\b",
            f"Entry-level candidate targeting {title}, with",
            source_summary,
            count=1,
            flags=re.I,
        )

    technologies = []
    for project in resume.projects:
        for technology_line in project.technologies_raw:
            for technology in technology_line.split(","):
                technology = technology.strip()
                if technology and technology.lower() in job_text.lower():
                    technologies.append(technology)
    technologies = list(dict.fromkeys(technologies))[:5]
    if technologies:
        return (
            f"Entry-level candidate targeting {title}, with project work using "
            f"{', '.join(technologies)}."
        )
    return f"Entry-level candidate targeting {title}."


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]
    return {
        "name": ParagraphStyle(
            "ResumeName", parent=base, fontName="Helvetica-Bold", fontSize=19,
            leading=22, textColor=NAVY, alignment=TA_LEFT, spaceAfter=2,
        ),
        "contact": ParagraphStyle(
            "ResumeContact", parent=base, fontName="Helvetica", fontSize=8.5,
            leading=11, textColor=DARK_GREY, spaceAfter=10,
        ),
        "section": ParagraphStyle(
            "ResumeSection", parent=base, fontName="Helvetica-Bold", fontSize=10.5,
            leading=13, textColor=NAVY, spaceBefore=5, spaceAfter=2,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ResumeBody", parent=base, fontName="Helvetica", fontSize=9,
            leading=12, textColor=DARK_GREY, spaceAfter=2,
        ),
        "bullet": ParagraphStyle(
            "ResumeBullet", parent=base, fontName="Helvetica", fontSize=9,
            leading=11.5, textColor=DARK_GREY, leftIndent=11, firstLineIndent=-8,
            spaceAfter=1,
        ),
        "project": ParagraphStyle(
            "ResumeProject", parent=base, fontName="Helvetica-Bold", fontSize=9.2,
            leading=12, textColor=DARK_GREY, spaceBefore=3, spaceAfter=1,
            keepWithNext=True,
        ),
    }


def _append_section(story: list, title: str, lines: list[str], styles: dict) -> None:
    if not lines:
        return
    story.append(Paragraph(html.escape(title), styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=LIGHT_GREY, spaceAfter=4))
    for line in lines:
        text = _plain_line(line)
        if text:
            story.append(Paragraph(_rich_text(text), styles["bullet"], bulletText="-"))


def _render_resume(resume: ParsedResume, job: dict, destination: Path) -> None:
    styles = _styles()
    story = []
    name = resume.name or "Candidate"
    story.append(Paragraph(html.escape(name), styles["name"]))
    contact = _contact_details(resume)
    if contact:
        story.append(Paragraph(html.escape(" | ".join(contact)), styles["contact"]))
    else:
        story.append(Spacer(1, 6))

    job_text = f"{job.get('title', '')} {job.get('description', '')}"
    story.append(Paragraph("PROFESSIONAL SUMMARY", styles["section"]))
    story.append(HRFlowable(width="100%", thickness=0.6, color=LIGHT_GREY, spaceAfter=4))
    story.append(Paragraph(_rich_text(_targeted_summary(resume, job, job_text)), styles["body"]))

    skill_lines = [
        line for block in resume.blocks if block.kind == "skills" for line in block.lines
        if _plain_line(line)
    ]
    skill_lines.sort(key=lambda line: _relevance(line, job_text), reverse=True)
    _append_section(story, "TECHNICAL SKILLS", skill_lines, styles)

    projects = sorted(
        enumerate(resume.projects),
        key=lambda item: (-_relevance(
            f"{item[1].name} {' '.join(item[1].technologies_raw)} "
            f"{' '.join(item[1].description)}",
            job_text,
        ), item[0]),
    )
    if projects:
        story.append(Paragraph("PROJECTS", styles["section"]))
        story.append(HRFlowable(width="100%", thickness=0.6, color=LIGHT_GREY, spaceAfter=4))
        for _, project in projects:
            project_name = re.sub(r"^\d+[.)]\s*", "", project.name).strip()
            title = html.escape(project_name)
            if project.technologies_raw:
                tech = html.escape(", ".join(project.technologies_raw))
                title += f" <font name='Helvetica' size='8.5'>| {tech}</font>"
            story.append(Paragraph(title, styles["project"]))
            for detail in project.description:
                text = _plain_line(detail)
                if text:
                    story.append(Paragraph(_rich_text(text), styles["bullet"], bulletText="-"))

    experience_lines = []
    for block in resume.blocks:
        if block.kind == "experience":
            if block.is_item:
                experience_lines.append(block.title)
            experience_lines.extend(block.lines)
    _append_section(story, "INTERNSHIP / EXPERIENCE", experience_lines, styles)

    _append_section(story, "EDUCATION", resume.education, styles)
    _append_section(story, "CERTIFICATIONS", resume.certifications, styles)
    _append_section(story, "TRAINING", resume.training, styles)

    def draw_page(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LIGHT_GREY)
        canvas.setLineWidth(0.4)
        canvas.line(doc.leftMargin, 14 * mm, A4[0] - doc.rightMargin, 14 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(DARK_GREY)
        canvas.drawRightString(A4[0] - doc.rightMargin, 9 * mm, str(doc.page))
        canvas.restoreState()

    document = SimpleDocTemplate(
        str(destination),
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=15 * mm,
        bottomMargin=19 * mm,
        title=f"{name} - {job.get('title', 'Resume')}",
        author=name,
    )
    document.build(story, onFirstPage=draw_page, onLaterPages=draw_page)


def build_resume(job: dict) -> Path:
    """Build a truthful, job-tailored, selectable-text PDF from the configured master resume."""
    source_path = Path(MASTER_RESUME)
    if not source_path.exists():
        raise FileNotFoundError(f"Master resume not found: {source_path}")

    source = read_resume_text(source_path)
    if "ADD YOUR" in source.upper() or "REPLACE WITH" in source.upper():
        raise ValueError("Complete master_resume.md and remove placeholders before generating a resume.")
    resume = parse_resume_text(source, source_path=str(source_path))
    if not resume.name and not source.strip():
        raise ValueError("The master resume is empty.")

    RESUME_DIR.mkdir(parents=True, exist_ok=True)
    filename = "_".join((
        _safe_name(job.get("title"), "resume"),
        _safe_name(job.get("company"), "company"),
        _safe_name(job.get("id"), "job"),
    ))
    pdf_path = RESUME_DIR / f"{filename}.pdf"
    _render_resume(resume, job, pdf_path)

    reader = PdfReader(str(pdf_path))
    extracted_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not reader.pages or not extracted_text.strip():
        raise RuntimeError(f"Generated PDF is empty or has no selectable text: {pdf_path}")
    if resume.name and resume.name not in extracted_text:
        raise RuntimeError(f"Generated PDF is missing the candidate name: {pdf_path}")
    return pdf_path
