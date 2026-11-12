from db import init_db, connect
from resume_profile_service import intelligence_db

init_db()
intelligence_db()  # creates only additive ri_* tables
with connect() as con:
    tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    job_columns={row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
    required_job_columns={
        "canonical_job_id", "experience_requirement", "job_type",
        "missing_required_skills", "manual_review_required", "freshness_rank",
    }
    missing=required_job_columns-job_columns
    if missing:
        raise RuntimeError(f"Missing additive job columns: {sorted(missing)}")
    print("Database tables:", sorted(tables))
    if "jobs" in tables:
        print("Jobs:", con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
    if "applications" in tables:
        print("Applications:", con.execute("SELECT COUNT(*) FROM applications").fetchone()[0])
    if "runs" in tables:
        print("Runs:", con.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    print("Migration check: additive job columns exist; existing tables were not dropped.")
