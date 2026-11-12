from pathlib import Path
from config import DB_PATH, ACTIVE_RESUME_PATH, UPLOAD_DIR
from resume_intelligence import ResumeIntelligenceDB


def intelligence_db():
    # Resume Intelligence creates only ri_* tables in the existing JobPilot DB.
    return ResumeIntelligenceDB(DB_PATH)


def ensure_resume_profile(force=False):
    path = ACTIVE_RESUME_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Active resume not found: {path}. Upload a PDF/DOCX/MD resume in the dashboard."
        )
    db = intelligence_db()
    status, resume_id = db.refresh_from_resume(path, force=force)
    profile = db.get_profile()
    if not profile:
        raise RuntimeError("Resume was parsed but no active profile was returned.")
    return status, resume_id, profile


def profile_from_db():
    profile = intelligence_db().get_profile()
    if profile:
        return profile
    _, _, profile = ensure_resume_profile()
    return profile


def ingest_resume(uploaded_file):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix not in {".pdf", ".docx", ".md", ".txt"}:
        raise ValueError("Upload a PDF, DOCX, Markdown or TXT resume.")
    target = UPLOAD_DIR / ("active_resume" + suffix)
    target.write_bytes(uploaded_file.getbuffer())
    # Return the path; config is not mutated at runtime. The dashboard can parse
    # this path directly and store it as the active Resume Intelligence source.
    db = intelligence_db()
    status, rid = db.refresh_from_resume(target, force=True)
    return target, status, rid, db.get_profile()
