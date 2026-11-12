"""Phase 2 - Resume Intelligence database.

* Only creates NEW tables prefixed ``ri_`` (CREATE TABLE IF NOT EXISTS), so it is
  safe to point at your existing SQLite file: existing tables/rows are never touched.
* The resume file is only read. Manual corrections live in ``ri_corrections`` and are
  re-applied after every re-parse, so they survive resume updates.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from resume_parser import ParsedResume, parse_resume
from skill_audit import find_uncaptured
from skill_extractor import (AWS, CLOUD, DB, DEVOPS, EXTRACTOR_VERSION, FW, OTHER, PL,
                             extract_skills)

MIGRATIONS = [
    (1, """
    CREATE TABLE IF NOT EXISTS ri_resume_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_path TEXT NOT NULL, source_type TEXT, file_hash TEXT NOT NULL,
        extractor_version TEXT, parsed_at TEXT NOT NULL,
        name TEXT, email TEXT, phone TEXT, links_json TEXT,
        experience_level TEXT, warnings_json TEXT, uncaptured_json TEXT,
        is_active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS ri_skills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resume_id INTEGER NOT NULL REFERENCES ri_resume_versions(id) ON DELETE CASCADE,
        name TEXT NOT NULL, category TEXT NOT NULL, in_catalog INTEGER NOT NULL,
        original_forms_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ri_skill_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        skill_id INTEGER NOT NULL REFERENCES ri_skills(id) ON DELETE CASCADE,
        section TEXT, section_kind TEXT, project TEXT, line TEXT, original TEXT);
    CREATE TABLE IF NOT EXISTS ri_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resume_id INTEGER NOT NULL REFERENCES ri_resume_versions(id) ON DELETE CASCADE,
        kind TEXT NOT NULL, position INTEGER NOT NULL, text TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS ri_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        resume_id INTEGER NOT NULL REFERENCES ri_resume_versions(id) ON DELETE CASCADE,
        name TEXT NOT NULL, description_json TEXT, technologies_raw_json TEXT);
    CREATE TABLE IF NOT EXISTS ri_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL CHECK (action IN ('rename','recategorize','remove','add')),
        skill_name TEXT NOT NULL, new_name TEXT, new_category TEXT, note TEXT,
        created_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_ri_skills_resume ON ri_skills(resume_id);
    CREATE INDEX IF NOT EXISTS idx_ri_sources_skill ON ri_skill_sources(skill_id);
    CREATE INDEX IF NOT EXISTS idx_ri_items_resume ON ri_items(resume_id, kind);
    """),
]

ITEM_KINDS = ("summary", "education", "certifications", "training", "experience", "achievements")


def infer_experience_level(r: ParsedResume) -> str:
    """Heuristic label only - the user should confirm it."""
    text = " ".join(r.experience)
    years = re.findall(r"(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b", text, re.I)
    if years:
        return f"{max(float(y) for y in years):g} year(s) stated in resume"
    if not r.experience:
        return "Fresher / entry-level (no work experience listed)"
    if re.search(r"intern|trainee|apprentice", text, re.I):
        return "Fresher / entry-level (internship experience listed)"
    return "Experience listed but duration unclear - please confirm"


class ResumeIntelligenceDB:
    def __init__(self, db_path):
        self.path = str(db_path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def migrate(self):
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS ri_migrations "
                      "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            done = {r[0] for r in c.execute("SELECT version FROM ri_migrations")}
            for version, sql in MIGRATIONS:
                if version in done:
                    continue
                for stmt in filter(None, (x.strip() for x in sql.split(";"))):
                    c.execute(stmt)
                c.execute("INSERT INTO ri_migrations VALUES (?, ?)", (version, _now()))

    # ------------------------------------------------------------- ingestion
    def refresh_from_resume(self, path, force: bool = False):
        """Parse the resume and store it. Returns (status, resume_id)."""
        p = Path(path)
        file_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        with self._conn() as c:
            row = c.execute(
                "SELECT id FROM ri_resume_versions WHERE is_active=1 AND source_path=? "
                "AND file_hash=? AND extractor_version=?",
                (str(p), file_hash, EXTRACTOR_VERSION)).fetchone()
            if row and not force:
                return "unchanged", row["id"]
        parsed = parse_resume(p)
        skills = extract_skills(parsed)
        uncaptured = find_uncaptured(parsed, skills)
        with self._conn() as c:
            c.execute("UPDATE ri_resume_versions SET is_active=0")
            cur = c.execute(
                "INSERT INTO ri_resume_versions (source_path, source_type, file_hash, extractor_version,"
                " parsed_at, name, email, phone, links_json, experience_level, warnings_json, uncaptured_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (str(p), p.suffix.lower().lstrip("."), file_hash, EXTRACTOR_VERSION, _now(),
                 parsed.name, parsed.email, parsed.phone, json.dumps(parsed.links),
                 infer_experience_level(parsed), json.dumps(parsed.warnings), json.dumps(uncaptured)))
            rid = cur.lastrowid
            for sk in skills:
                sc = c.execute("INSERT INTO ri_skills (resume_id,name,category,in_catalog,original_forms_json)"
                               " VALUES (?,?,?,?,?)",
                               (rid, sk.name, sk.category, int(sk.in_catalog), json.dumps(sk.original_forms)))
                c.executemany("INSERT INTO ri_skill_sources (skill_id,section,section_kind,project,line,original)"
                              " VALUES (?,?,?,?,?,?)",
                              [(sc.lastrowid, e.section, e.section_kind, e.project, e.line, e.original)
                               for e in sk.evidence])
            c.executemany("INSERT INTO ri_items (resume_id,kind,position,text) VALUES (?,?,?,?)",
                          [(rid, kind, i, text) for kind in ITEM_KINDS
                           for i, text in enumerate(getattr(parsed, kind))])
            c.executemany("INSERT INTO ri_projects (resume_id,name,description_json,technologies_raw_json)"
                          " VALUES (?,?,?,?)",
                          [(rid, pr.name, json.dumps(pr.description), json.dumps(pr.technologies_raw))
                           for pr in parsed.projects])
        return "created", rid

    def signature(self) -> tuple:
        """Changes whenever the stored profile or corrections change (used for caching)."""
        with self._conn() as c:
            return tuple(c.execute(
                "SELECT (SELECT COALESCE(MAX(id),0) FROM ri_resume_versions),"
                " (SELECT COALESCE(MAX(id),0) FROM ri_corrections),"
                " (SELECT COUNT(*) FROM ri_corrections)").fetchone())

    # ----------------------------------------------------------- corrections
    def add_correction(self, action, skill_name, new_name=None, new_category=None, note=None):
        with self._conn() as c:
            c.execute("INSERT INTO ri_corrections (action,skill_name,new_name,new_category,note,created_at)"
                      " VALUES (?,?,?,?,?,?)",
                      (action, skill_name.strip(), (new_name or "").strip() or None, new_category, note, _now()))

    def delete_correction(self, correction_id: int):
        with self._conn() as c:
            c.execute("DELETE FROM ri_corrections WHERE id=?", (correction_id,))

    def list_corrections(self) -> list:
        with self._conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM ri_corrections ORDER BY id")]

    # --------------------------------------------------------------- reading
    def get_profile(self) -> Optional[dict]:
        with self._conn() as c:
            rv = c.execute("SELECT * FROM ri_resume_versions WHERE is_active=1 ORDER BY id DESC LIMIT 1").fetchone()
            if rv is None:
                return None
            rid = rv["id"]
            sources: dict = {}
            for x in c.execute(
                    "SELECT ss.skill_id, ss.section, ss.section_kind, ss.project, ss.line, ss.original "
                    "FROM ri_skill_sources ss JOIN ri_skills k ON k.id = ss.skill_id "
                    "WHERE k.resume_id=? ORDER BY ss.id", (rid,)):
                sources.setdefault(x["skill_id"], []).append(
                    {k: x[k] for k in ("section", "section_kind", "project", "line", "original")})
            skills = [{"name": s["name"], "category": s["category"], "in_catalog": bool(s["in_catalog"]),
                       "original_forms": json.loads(s["original_forms_json"]),
                       "sources": sources.get(s["id"], []), "status": "detected", "original_name": s["name"]}
                      for s in c.execute("SELECT * FROM ri_skills WHERE resume_id=? ORDER BY category, name", (rid,))]
            items = {k: [] for k in ITEM_KINDS}
            for r in c.execute("SELECT kind,text FROM ri_items WHERE resume_id=? ORDER BY kind, position", (rid,)):
                items[r["kind"]].append(r["text"])
            projects = [{"name": r["name"], "description": json.loads(r["description_json"] or "[]"),
                         "technologies_raw": json.loads(r["technologies_raw_json"] or "[]")}
                        for r in c.execute("SELECT * FROM ri_projects WHERE resume_id=? ORDER BY id", (rid,))]
            corrections = [dict(r) for r in c.execute("SELECT * FROM ri_corrections ORDER BY id")]

        active, removed, orphaned = _apply_corrections(skills, corrections)
        for s in active + removed:
            s["found_in"] = sorted({x["section_kind"] or "other" for x in s["sources"]})
            s["projects"] = sorted({x["project"] for x in s["sources"]
                                    if x["section_kind"] == "projects" and x["project"]})
        warnings = json.loads(rv["warnings_json"] or "[]")
        uncaptured = json.loads(rv["uncaptured_json"] or "[]")
        profile = {
            "resume": {"id": rid, "source_path": rv["source_path"], "source_type": rv["source_type"],
                       "parsed_at": rv["parsed_at"], "name": rv["name"], "email": rv["email"],
                       "phone": rv["phone"], "links": json.loads(rv["links_json"] or "[]")},
            "skills": active, "removed_skills": removed, "orphaned_corrections": orphaned,
            "projects": projects, "experience_level": rv["experience_level"],
            "warnings": warnings, "uncaptured_terms": uncaptured, **items,
        }
        profile["keywords"] = _keywords(profile)
        profile["missing_unclear"] = _missing_unclear(profile)
        return profile


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _apply_corrections(skills: list, corrections: list):
    by_key = {s["name"].lower(): s for s in skills}
    removed, orphaned = [], []
    for c in corrections:
        key = c["skill_name"].lower()
        s = by_key.get(key)
        if c["action"] == "add":
            if s is None:
                by_key[key] = {"name": c["skill_name"], "category": c["new_category"] or OTHER, "in_catalog": False,
                               "original_forms": [c["skill_name"]], "status": "manual", "original_name": c["skill_name"],
                               "sources": [{"section": "Manual entry (confirmed by you)", "section_kind": "manual",
                                            "project": None, "line": c["note"] or "Added manually", "original": c["skill_name"]}]}
            continue
        if s is None:
            orphaned.append(c)
            continue
        if c["action"] == "recategorize" and c["new_category"]:
            s["category"] = c["new_category"]
            s["status"] = "corrected" if s["status"] == "detected" else s["status"]
        elif c["action"] == "rename" and c["new_name"]:
            del by_key[key]
            nk = c["new_name"].lower()
            if nk in by_key:  # merge into an existing skill
                t = by_key[nk]
                for f in s["original_forms"]:
                    if f not in t["original_forms"]:
                        t["original_forms"].append(f)
                t["sources"].extend(s["sources"])
                t["status"] = "corrected" if t["status"] == "detected" else t["status"]
            else:
                s["name"] = c["new_name"]
                s["status"] = "corrected" if s["status"] == "detected" else s["status"]
                by_key[nk] = s
        elif c["action"] == "remove":
            del by_key[key]
            s["status"] = "removed"
            removed.append(s)
    active = sorted(by_key.values(), key=lambda x: (x["category"], x["name"].lower()))
    return active, removed, orphaned


def _keywords(p: dict) -> list:
    seen, out = set(), []
    def add(x):
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    for s in p["skills"]:
        add(s["name"])
        for f in s["original_forms"]:
            add(f)
    for cert in p["certifications"]:
        add(cert)
    return out


def _missing_unclear(p: dict) -> list:
    out = list(p["warnings"])
    if not p["certifications"]:
        out.append("No certifications found")
    if not p["summary"]:
        out.append("No career objective / professional summary found")
    if not p["projects"]:
        out.append("No projects parsed")
    for pr in p["projects"]:
        if not pr["technologies_raw"]:
            out.append(f"Project '{pr['name']}' has no 'Technologies:' line (technologies may be only in prose)")
    for s in p["skills"]:
        if s["status"] == "detected" and not s["in_catalog"]:
            out.append(f"Skill '{s['name']}' is not in the synonym catalogue - confirm spelling/category")
        if s["status"] == "detected" and s["category"] == OTHER and s["in_catalog"]:
            out.append(f"Skill '{s['name']}' has no category")
    for u in p["uncaptured_terms"]:
        out.append(f"'{u['term']}' is listed in {u['section']} but was not captured as a skill")
    if p["orphaned_corrections"]:
        out.append(f"{len(p['orphaned_corrections'])} manual correction(s) no longer match any detected skill")
    out.append(f"Experience level is inferred: {p['experience_level']}")
    return out


def summarize(p: dict) -> dict:
    sk = p["skills"]
    count = lambda *cats: sum(1 for s in sk if s["category"] in cats)
    return {
        "Total skills detected": len(sk),
        "Programming languages": count(PL),
        "Cloud technologies": count(CLOUD, AWS),
        "DevOps tools": count(DEVOPS),
        "Database technologies": count(DB),
        "Frameworks": count(FW),
        "Project technologies": sum(1 for s in sk if "projects" in s["found_in"]),
        "Certifications": len(p["certifications"]),
        "Education entries": len(p["education"]),
        "Missing / unclear items": len(p["missing_unclear"]),
    }
