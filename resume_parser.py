"""Phase 1 - Resume parser.

Reads a resume from Markdown/TXT, PDF or DOCX and turns it into a structured
``ParsedResume``. It never writes to the source file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# Order matters: first match wins ("Academic Projects" must be projects, not education).
SECTION_KINDS = [
    ("projects", ("project",)),
    ("certifications", ("certif", "licens")),
    ("training", ("training", "course")),
    ("experience", ("experience", "internship", "employment")),
    ("education", ("education", "academic", "qualification")),
    ("skills", ("skill", "competenc", "technologies", "tools")),
    ("achievements", ("achievement", "award", "honor", "honour", "accomplishment")),
    ("summary", ("summary", "objective", "profile", "about")),
]

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*+\u2022\u25cf\u25aa]\s+)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s-]?)?(?:\d[\s-]?){9,11}\d(?!\w)")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|(?:linkedin|github)\.com/\S+", re.I)
TECH_LINE_RE = re.compile(
    r"^\s*(?:[-*+\u2022]\s*)?(tech(?:nologies|nology)?(?:\s*stack)?|tools?(?:\s*used)?|"
    r"stack|built\s+with|environment|skills\s+used)\s*[:\-\u2013]\s*(.+)$",
    re.I,
)


def strip_md(line: str) -> str:
    """Remove bold/underline markers so labels like '**Skills:**' become 'Skills:'."""
    return re.sub(r"(\*\*|__)", "", line)


def classify_heading(title: str) -> Optional[str]:
    t = re.sub(r"[^a-z0-9 &/]", " ", title.lower()).strip()
    if not t or len(t.split()) > 6:
        return None
    for kind, needles in SECTION_KINDS:
        if any(n in t for n in needles):
            return kind
    return None


@dataclass
class Block:
    title: str
    kind: Optional[str]           # section kind (projects, skills, ...), None for header
    parent: Optional[str] = None  # section title when this block is an item inside it
    is_item: bool = False
    lines: list = field(default_factory=list)


@dataclass
class Project:
    name: str
    section: str
    description: list = field(default_factory=list)
    technologies_raw: list = field(default_factory=list)


@dataclass
class ParsedResume:
    source_path: Optional[str]
    raw_text: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    links: list = field(default_factory=list)
    blocks: list = field(default_factory=list)
    projects: list = field(default_factory=list)
    summary: list = field(default_factory=list)
    education: list = field(default_factory=list)
    certifications: list = field(default_factory=list)
    training: list = field(default_factory=list)
    experience: list = field(default_factory=list)
    achievements: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("raw_text", None)
        return d


# ---------------------------------------------------------------- file reading
def read_resume_text(path) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Resume not found: {p}")
    suffix = p.suffix.lower()
    if suffix in (".md", ".markdown", ".txt"):
        return p.read_text(encoding="utf-8-sig", errors="replace")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:  # pragma: no cover
            raise ImportError("PDF support needs: pip install pypdf") from e
        reader = PdfReader(str(p))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if suffix == ".docx":
        try:
            import docx
        except ImportError as e:  # pragma: no cover
            raise ImportError("DOCX support needs: pip install python-docx") from e
        d = docx.Document(str(p))
        out = []
        for para in d.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "") if para.style is not None else ""
            if style.lower().startswith("heading") or style.lower() == "title":
                out.append("## " + text)
            elif "list" in style.lower():
                out.append("- " + text)
            else:
                out.append(text)
        for table in d.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    out.append(" | ".join(cells))
        return "\n".join(out)
    raise ValueError(f"Unsupported resume format: {suffix} (use .md, .txt, .pdf, .docx)")


# --------------------------------------------------------------------- parsing
def _plain_heading(line: str) -> Optional[str]:
    """Detect headings in PDF/plain text such as 'TECHNICAL SKILLS' or 'Projects:'."""
    if BULLET_RE.match(line) or "," in line:
        return None
    s = re.sub(r"[*_:#]", "", line).strip()
    if not s or len(s.split()) > 5:
        return None
    return s if classify_heading(s) else None


def parse_resume_text(text: str, source_path: Optional[str] = None) -> ParsedResume:
    res = ParsedResume(source_path=source_path, raw_text=text)
    blocks: list[Block] = []
    header = Block(title="header", kind=None)
    blocks.append(header)
    cur_section: Optional[Block] = header
    cur: Block = header

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        m = HEADING_RE.match(line)
        title = None
        if m:
            title = strip_md(m.group(2)).strip()
            kind = classify_heading(title)
            if kind:
                cur = Block(title=title, kind=kind)
                blocks.append(cur)
                cur_section = cur
            elif cur_section is header:
                header.lines.append(title)  # e.g. "# Full Name"
            else:
                cur = Block(title=title, kind=cur_section.kind,
                            parent=cur_section.title, is_item=True)
                blocks.append(cur)
            continue
        plain = _plain_heading(strip_md(line))
        if plain:
            plain_kind = classify_heading(plain)
            if cur_section.kind == "education" and plain_kind == "training":
                cur = Block(
                    title=plain,
                    kind="education",
                    parent=cur_section.title,
                    is_item=True,
                )
                blocks.append(cur)
                continue
            cur = Block(title=plain, kind=plain_kind)
            blocks.append(cur)
            cur_section = cur
            continue
        # bold line starting an item inside projects / experience
        bm = re.match(r"^\s*(?:[-*+]\s*)?\*\*(.+?)\*\*\s*(.*)$", line)
        if bm and cur_section is not header and cur_section.kind in ("projects", "experience"):
            name = bm.group(1).strip()
            if not name.endswith(":") and not TECH_LINE_RE.match(strip_md(line)):
                cur = Block(title=name.strip(" -:|"), kind=cur_section.kind,
                            parent=cur_section.title, is_item=True)
                blocks.append(cur)
                rest = bm.group(2).strip(" -\u2013\u2014|:")
                if rest:
                    cur.lines.append(rest)
                continue
        cur.lines.append(line)

    res.blocks = blocks

    # name + contact
    for hl in header.lines:
        h = strip_md(hl).strip()
        if h and not EMAIL_RE.search(h) and not re.search(r"\d{5,}", h) and len(h.split()) <= 5:
            res.name = h.lstrip("# ").strip()
            break
    head_text = "\n".join(header.lines)
    em = EMAIL_RE.search(text)
    res.email = em.group(0) if em else None
    ph = PHONE_RE.search(head_text) or PHONE_RE.search(text)
    res.phone = ph.group(0).strip() if ph else None
    res.links = list(dict.fromkeys(u.rstrip(").,|") for u in URL_RE.findall(text)))

    def clean(lines):
        return [BULLET_RE.sub("", strip_md(l)).strip() for l in lines if l.strip()]

    for b in blocks:
        if b.kind == "summary":
            res.summary += clean(b.lines)
        elif b.kind == "education":
            res.education += ([b.title] if b.is_item else []) + clean(b.lines)
        elif b.kind == "certifications":
            res.certifications += ([b.title] if b.is_item else []) + clean(b.lines)
        elif b.kind == "training":
            res.training += ([b.title] if b.is_item else []) + clean(b.lines)
        elif b.kind == "experience":
            res.experience += ([b.title] if b.is_item else []) + clean(b.lines)
        elif b.kind == "achievements":
            res.achievements += clean(b.lines)

    # projects
    proj_sections = [b for b in blocks if b.kind == "projects"]
    item_blocks = [b for b in proj_sections if b.is_item]
    candidates = item_blocks or [b for b in proj_sections if b.lines]
    for b in candidates:
        pr = Project(name=b.title, section=b.parent or b.title)
        for l in b.lines:
            pl = strip_md(l)
            tm = TECH_LINE_RE.match(pl)
            if tm:
                pr.technologies_raw.append(tm.group(2).strip())
            elif pl.strip():
                pr.description.append(BULLET_RE.sub("", pl).strip())
        res.projects.append(pr)

    if not res.name:
        res.warnings.append("Name not detected")
    if not res.email:
        res.warnings.append("Email not detected")
    if not res.phone:
        res.warnings.append("Phone not detected")
    for kind, label in (("skills", "Skills"), ("education", "Education"), ("projects", "Projects")):
        if not any(b.kind == kind for b in blocks):
            res.warnings.append(f"No {label} section detected")
    return res


def parse_resume(path) -> ParsedResume:
    """Read + parse a resume file. The file itself is never modified."""
    return parse_resume_text(read_resume_text(path), source_path=str(path))
