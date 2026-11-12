import sqlite3
from datetime import datetime

from config import DB_PATH
from db import connect
from matcher import enrich, master_resume_profile
from run_search import freshness_window

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    backup_path = DB_PATH.with_name(
        f"jobpilot_backup_{datetime.now():%Y%m%d_%H%M%S}.db"
    )

    # Create a consistent SQLite backup.
    with sqlite3.connect(DB_PATH) as source:
        with sqlite3.connect(backup_path) as backup:
            source.backup(backup)

    print(f"Database backup created: {backup_path}")

    with connect() as con:
        columns = {
            row["name"]
            for row in con.execute("PRAGMA table_info(jobs)")
        }

        required = {
            "id", "title", "description",
            "match_score", "matched_skills"
        }

        if not required.issubset(columns):
            raise RuntimeError(
                f"Missing database columns: {required - columns}"
            )

        jobs = [
            dict(row)
            for row in con.execute("SELECT * FROM jobs").fetchall()
        ]

        print(f"Existing jobs found: {len(jobs)}")
        profile = master_resume_profile()

        for job in jobs:
            job["posted"] = job.get("original_posted_at") or job.get("posted")
            job["freshness_rank"], job["freshness_bucket"] = freshness_window(job["posted"])
            updated = enrich(job, profile)

            con.execute(
                """UPDATE jobs
                   SET match_score = ?, matched_skills = ?,
                       match_explanation = ?, missing_requirements = ?,
                       missing_required_skills = ?, experience_fit = ?,
                       experience_requirement = ?, job_type = ?,
                       manual_review_required = ?, freshness_rank = ?,
                       freshness_bucket = ?
                   WHERE id = ?""",
                (
                    updated["match_score"],
                    ", ".join(updated["matched_skills"]),
                    updated["match_explanation"],
                    "; ".join(updated["missing_requirements"]),
                    ", ".join(updated["missing_required_skills"]),
                    updated["experience_fit"],
                    updated["experience_requirement"],
                    updated["job_type"],
                    int(updated["manual_review_required"]),
                    updated["freshness_rank"],
                    updated["freshness_bucket"],
                    job["id"]
                )
            )

    print(f"Successfully refreshed {len(jobs)} job matches.")
    print("Job statuses and application history were not modified.")

if __name__ == "__main__":
    main()
