"""Phase 1 audit: find duplicates, unclassified skills and anything in your skill
lists that the extractor did NOT capture. Read-only; never changes the resume."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from resume_parser import ParsedResume, TECH_LINE_RE, BULLET_RE, strip_md
from skill_extractor import (LABEL_RE, OTHER, Skill, _split_top, dedupe_key)


def listed_atoms(resume: ParsedResume) -> list:
    """Every individual item the resume explicitly lists: (atom, section, line)."""
    atoms = []
    for b in resume.blocks:
        if b.kind is None:
            continue
        for raw in b.lines:
            plain = strip_md(raw).strip()
            if not plain:
                continue
            body = None
            if b.kind == "skills":
                lm = LABEL_RE.match(plain)
                body = lm.group(2) if lm else BULLET_RE.sub("", plain)
            else:
                tm = TECH_LINE_RE.match(plain)
                body = tm.group(2) if tm else None
            if not body:
                continue
            for item in _split_top(body):
                m = re.match(r"^(.*?)\s*[(\[](.*)[)\]]\s*(.*)$", item)
                parts = [m.group(1), *_split_top(m.group(2)), m.group(3)] if m and m.group(1).strip() else [item]
                for p in parts:
                    p = BULLET_RE.sub("", p).strip().strip(".:;-\u2013 ")
                    if p:
                        atoms.append((p, b.parent or b.title, plain))
    return atoms


def find_uncaptured(resume: ParsedResume, skills: list) -> list:
    forms = set()
    for s in skills:
        forms.add(s.name.lower())
        forms.update(f.lower() for f in s.original_forms)
    missing, seen = [], set()
    for atom, section, line in listed_atoms(resume):
        low = atom.lower()
        covered = low in forms or any(
            re.search(r"(?<![\w+#])" + re.escape(f) + r"(?![\w+#])", low) for f in forms if len(f) > 1
        )
        if not covered and low not in seen:
            seen.add(low)
            missing.append({"term": atom, "section": section, "line": line[:160]})
    return missing


def audit(resume: ParsedResume, skills: list) -> dict:
    keys: dict = {}
    for s in skills:
        keys.setdefault(dedupe_key(s.name), []).append(s.name)
    duplicates = [v for v in keys.values() if len(v) > 1]

    near = []
    for i, a in enumerate(skills):
        for b in skills[i + 1:]:
            if a.in_catalog and b.in_catalog:
                continue  # distinct catalogue entries are deliberately separate
            if SequenceMatcher(None, a.name.lower(), b.name.lower()).ratio() >= 0.85:
                near.append((a.name, b.name))

    return {
        "total_skills": len(skills),
        "duplicates": duplicates,
        "near_duplicates": near,
        "unclassified": [s.name for s in skills if s.category == OTHER],
        "not_in_catalogue": [s.name for s in skills if not s.in_catalog],
        "uncaptured_terms": find_uncaptured(resume, skills),
    }
