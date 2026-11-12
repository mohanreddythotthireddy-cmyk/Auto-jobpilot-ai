import json
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from config import DB_PATH
from duplicate_detection import duplicate_match, normalized_job


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _columns(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, title TEXT, company TEXT, location TEXT,
            url TEXT, description TEXT, source TEXT, posted TEXT,
            match_score INTEGER, matched_skills TEXT, status TEXT DEFAULT 'New',
            discovered_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("""CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL UNIQUE,
            company TEXT, title TEXT, url TEXT, status TEXT NOT NULL, detail TEXT,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        con.execute("""CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT DEFAULT CURRENT_TIMESTAMP,
            jobs_found INTEGER DEFAULT 0, new_jobs INTEGER DEFAULT 0, message TEXT)""")
        jc = _columns(con, "jobs")
        for name, sqltype in {
            "work_mode": "TEXT", "match_explanation": "TEXT",
            "missing_requirements": "TEXT", "experience_fit": "TEXT",
            "first_discovered_at": "TEXT", "original_posted_at": "TEXT",
            "last_updated_at": "TEXT", "last_checked_at": "TEXT",
            "source_updated_at": "TEXT", "freshness_rank": "INTEGER DEFAULT 8",
            "freshness_bucket": "TEXT",
            "missing_required_skills": "TEXT",
            "experience_requirement": "TEXT",
            "job_type": "TEXT",
            "manual_review_required": "INTEGER DEFAULT 1",
            "canonical_job_id": "TEXT", "normalized_company": "TEXT",
            "normalized_title": "TEXT", "normalized_location": "TEXT",
        }.items():
            if name not in jc:
                con.execute(f"ALTER TABLE jobs ADD COLUMN {name} {sqltype}")
        con.execute("UPDATE jobs SET canonical_job_id=id WHERE canonical_job_id IS NULL")
        for row in con.execute(
                "SELECT id,company,title,location FROM jobs "
                "WHERE normalized_company IS NULL OR normalized_title IS NULL OR normalized_location IS NULL").fetchall():
            normalized = normalized_job(dict(row))
            con.execute(
                "UPDATE jobs SET normalized_company=?,normalized_title=?,normalized_location=? WHERE id=?",
                (normalized["company"], normalized["title"], normalized["location"], row["id"]))
        con.execute("UPDATE jobs SET first_discovered_at=discovered_at WHERE first_discovered_at IS NULL")
        con.execute("UPDATE jobs SET last_checked_at=discovered_at WHERE last_checked_at IS NULL")
        con.execute("UPDATE jobs SET last_updated_at=discovered_at WHERE last_updated_at IS NULL")
        ac = _columns(con, "applications")
        for name in ("resume_path", "approved_at", "submitted_at"):
            if name not in ac:
                con.execute(f"ALTER TABLE applications ADD COLUMN {name} TEXT")
        rc = _columns(con, "runs")
        for name, sqltype in {"completed_at": "TEXT", "status": "TEXT", "details_json": "TEXT"}.items():
            if name not in rc:
                con.execute(f"ALTER TABLE runs ADD COLUMN {name} {sqltype}")
        con.execute("""CREATE TABLE IF NOT EXISTS job_source_tracking (
            source TEXT NOT NULL, source_job_id TEXT NOT NULL, job_id TEXT NOT NULL,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_updated_at TEXT,
            PRIMARY KEY(source, source_job_id),
            FOREIGN KEY(job_id) REFERENCES jobs(id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS job_source_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL, source_job_id TEXT NOT NULL,
            canonical_job_id TEXT NOT NULL, original_job_id TEXT,
            url TEXT, title TEXT, company TEXT, location TEXT, description TEXT,
            first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source,source_job_id))""")
        con.execute("""CREATE TABLE IF NOT EXISTS source_refresh_state (
            source TEXT PRIMARY KEY, last_attempted_at TEXT,
            last_successful_at TEXT, last_status TEXT, last_error TEXT,
            next_due_at TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS search_schedule_state (
            id INTEGER PRIMARY KEY CHECK(id=1), scheduler_started_at TEXT,
            next_scheduled_at TEXT, poll_seconds INTEGER, updated_at TEXT)""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_work_mode ON jobs(work_mode)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_first_discovered ON jobs(first_discovered_at)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_canonical ON jobs(canonical_job_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_normalized_identity "
                    "ON jobs(normalized_company,normalized_location)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_source_tracking_job ON job_source_tracking(job_id)")
        _group_existing_jobs(con)
        _backfill_source_records(con)


def _group_existing_jobs(con):
    rows = [dict(row) for row in con.execute(
        "SELECT * FROM jobs WHERE canonical_job_id=id ORDER BY COALESCE(discovered_at,''),id"
    )]
    candidates: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        normalized = normalized_job(row)
        key = (normalized["company"], normalized["location"])
        if not key[0]:
            continue
        matching = None
        for canonical in candidates.get(key, []):
            is_duplicate, _ = duplicate_match(canonical, row)
            if is_duplicate:
                matching = canonical
                break
        if matching is not None:
            con.execute(
                "UPDATE jobs SET canonical_job_id=? WHERE id=?",
                (matching["id"], row["id"]))
        else:
            candidates.setdefault(key, []).append(row)


def _record_source(con, job, canonical_id, now):
    source = str(job.get("source") or "Unknown")
    original_id = str(job.get("id") or "")
    source_job_id = str(job.get("source_job_id") or original_id or job.get("url") or "unknown")
    con.execute("""INSERT INTO job_source_records
        (source,source_job_id,canonical_job_id,original_job_id,url,title,company,location,
         description,first_seen_at,last_seen_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source,source_job_id) DO UPDATE SET
            canonical_job_id=excluded.canonical_job_id,
            original_job_id=COALESCE(job_source_records.original_job_id,excluded.original_job_id),
            url=COALESCE(job_source_records.url,excluded.url),
            title=COALESCE(job_source_records.title,excluded.title),
            company=COALESCE(job_source_records.company,excluded.company),
            location=COALESCE(job_source_records.location,excluded.location),
            description=CASE WHEN length(excluded.description)>length(job_source_records.description)
                             THEN excluded.description ELSE job_source_records.description END,
            last_seen_at=excluded.last_seen_at""",
        (source, source_job_id, canonical_id, original_id or None, job.get("url"),
         job.get("title"), job.get("company"), job.get("location"),
         job.get("description"), now, now))
    con.execute("""INSERT INTO job_source_tracking
        (source,source_job_id,job_id,first_seen_at,last_seen_at,source_updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(source,source_job_id) DO UPDATE SET
            job_id=excluded.job_id,last_seen_at=excluded.last_seen_at,
            source_updated_at=COALESCE(excluded.source_updated_at,job_source_tracking.source_updated_at)""",
        (source, source_job_id, canonical_id, now, now, job.get("source_updated_at") or None))


def _backfill_source_records(con):
    now = datetime.now().isoformat(timespec="seconds")
    tracked_job_ids = {
        row[0] for row in con.execute(
            "SELECT DISTINCT job_id FROM job_source_tracking"
        )
    }
    recorded_job_ids = {
        row[0] for row in con.execute(
            "SELECT DISTINCT original_job_id FROM job_source_records "
            "WHERE original_job_id IS NOT NULL"
        )
    }
    for row in con.execute(
            "SELECT j.*,COALESCE(j.canonical_job_id,j.id) AS canonical_id FROM jobs j").fetchall():
        job = dict(row)
        if job["id"] in tracked_job_ids or job["id"] in recorded_job_ids:
            continue
        _record_source(con, job, job["canonical_id"], now)
    tracking = con.execute(
        "SELECT t.source,t.source_job_id,t.job_id,t.source_updated_at,j.*, "
        "COALESCE(j.canonical_job_id,j.id) AS canonical_id "
        "FROM job_source_tracking t JOIN jobs j ON j.id=t.job_id"
    ).fetchall()
    for row in tracking:
        record = dict(row)
        _record_source(con, {
            "id": record["job_id"], "source": record["source"],
            "source_job_id": record["source_job_id"], "url": record["url"],
            "title": record["title"], "company": record["company"],
            "location": record["location"], "description": record["description"],
            "source_updated_at": record["source_updated_at"],
        }, record["canonical_id"], now)


def _normalized_url(url):
    if not url:
        return ""
    parsed = urlsplit(str(url).strip())
    if not parsed.scheme or not parsed.netloc:
        return str(url).strip().rstrip("/").lower()
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"source", "ref", "tracking"}]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                       parsed.path.rstrip("/"), urlencode(query), ""))


def _joined_text(value):
    if isinstance(value, str):
        return value
    return "; ".join(str(item) for item in (value or []))


def _comma_text(value):
    if isinstance(value, str):
        return value
    return ", ".join(str(item) for item in (value or []))


def save_jobs(jobs, return_details=False):
    counts = {"new": 0, "updated": 0, "duplicates": 0, "new_job_ids": []}
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        known_urls = {}
        for row in con.execute(
                "SELECT url,canonical_job_id,id FROM jobs WHERE url IS NOT NULL AND url!=''"):
            key = _normalized_url(row["url"])
            if key:
                known_urls[key] = row["canonical_job_id"] or row["id"]
        for row in con.execute(
                "SELECT url,canonical_job_id FROM job_source_records WHERE url IS NOT NULL AND url!=''"):
            key = _normalized_url(row["url"])
            if key:
                known_urls[key] = row["canonical_job_id"]

        candidates: dict[tuple[str, str], list[dict]] = {}
        for row in con.execute(
                "SELECT * FROM jobs WHERE canonical_job_id=id ORDER BY COALESCE(discovered_at,''),id"):
            candidate = dict(row)
            normalized = normalized_job(candidate)
            key = (normalized["company"], normalized["location"])
            if key[0]:
                candidates.setdefault(key, []).append(candidate)

        for job in jobs:
            incoming_id = job.get("id")
            url_key = _normalized_url(job.get("url"))
            existing_id = con.execute(
                "SELECT COALESCE(canonical_job_id,id) FROM jobs WHERE id=?", (incoming_id,)
            ).fetchone()
            source_key = str(job.get("source_job_id") or incoming_id or job.get("url") or "unknown")
            source_alias = con.execute(
                "SELECT canonical_job_id FROM job_source_records WHERE source=? AND source_job_id=?",
                (str(job.get("source") or "Unknown"), source_key),
            ).fetchone()
            same_source_listing = bool(existing_id or source_alias)
            canonical_id = (
                existing_id[0] if existing_id else
                source_alias["canonical_job_id"] if source_alias else
                known_urls.get(url_key)
            )
            matching = (
                con.execute("SELECT * FROM jobs WHERE id=?", (canonical_id,)).fetchone()
                if canonical_id else None
            )

            if matching is None:
                normalized = normalized_job(job)
                key = (normalized["company"], normalized["location"])
                for candidate in candidates.get(key, []):
                    is_duplicate, _reason = duplicate_match(candidate, job)
                    if is_duplicate:
                        matching = candidate
                        canonical_id = candidate["id"]
                        break

            if matching is None:
                if not incoming_id:
                    raise ValueError("A discovered job must have a stable id before it can be saved.")
                canonical_id = incoming_id
                normalized = normalized_job(job)
                con.execute("""INSERT INTO jobs
                    (id,title,company,location,url,description,source,posted,match_score,matched_skills,
                     work_mode,match_explanation,missing_requirements,missing_required_skills,
                     experience_fit,experience_requirement,job_type,manual_review_required,first_discovered_at,
                     original_posted_at,last_updated_at,last_checked_at,source_updated_at,
                     freshness_rank,freshness_bucket,canonical_job_id,normalized_company,
                     normalized_title,normalized_location)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (canonical_id, job.get("title"), job.get("company"), job.get("location"),
                     job.get("url"), job.get("description"), job.get("source"), job.get("posted"),
                    int(job.get("match_score") or 0), _comma_text(job.get("matched_skills")),
                     job.get("work_mode", "Not specified"), job.get("match_explanation", ""),
                     _joined_text(job.get("missing_requirements")),
                    _comma_text(job.get("missing_required_skills")),
                     job.get("experience_fit", "Unclear"),
                     job.get("experience_requirement", "Not stated"),
                    job.get("job_type", "Not specified"),
                     int(bool(job.get("manual_review_required", True))),
                     now, job.get("posted"),
                     now, now, job.get("source_updated_at") or None,
                     int(job.get("freshness_rank", 8)), job.get("freshness_bucket", "Date unknown"),
                     canonical_id, normalized["company"], normalized["title"], normalized["location"]))
                counts["new"] += 1
                counts["new_job_ids"].append(canonical_id)
                candidate = {**job, "id": canonical_id, "canonical_job_id": canonical_id}
                key = (normalized["company"], normalized["location"])
                if key[0]:
                    candidates.setdefault(key, []).append(candidate)
            else:
                updates = {}
                if same_source_listing:
                    old = dict(matching)
                    candidate_values = {
                        "title": job.get("title"),
                        "company": job.get("company"),
                        "location": job.get("location"),
                        "description": job.get("description"),
                        "posted": job.get("posted"),
                        "original_posted_at": job.get("posted"),
                        "match_score": job.get("match_score"),
                        "matched_skills": _comma_text(job.get("matched_skills")),
                        "work_mode": job.get("work_mode"),
                        "match_explanation": job.get("match_explanation"),
                        "missing_requirements": _joined_text(job.get("missing_requirements")),
                        "missing_required_skills": _comma_text(job.get("missing_required_skills")),
                        "experience_fit": job.get("experience_fit"),
                        "experience_requirement": job.get("experience_requirement"),
                        "job_type": job.get("job_type"),
                        "manual_review_required": (
                            int(bool(job.get("manual_review_required")))
                            if "manual_review_required" in job else None
                        ),
                        "freshness_rank": job.get("freshness_rank"),
                        "freshness_bucket": job.get("freshness_bucket"),
                        "source_updated_at": job.get("source_updated_at"),
                    }
                    for column, value in candidate_values.items():
                        if value is None or value == "":
                            continue
                        if old.get(column) != value:
                            updates[column] = value
                    if any(key in updates for key in ("company", "title", "location")):
                        normalized = normalized_job({**old, **updates})
                        updates.update({
                            f"normalized_{key}": value
                            for key, value in normalized.items()
                            if key in {"company", "title", "location"}
                        })
                    if updates:
                        updates["last_updated_at"] = now
                if updates:
                    assignments = ", ".join(f"{column}=?" for column in updates)
                    con.execute(
                        f"UPDATE jobs SET {assignments},last_checked_at=? WHERE id=?",
                        (*updates.values(), now, canonical_id),
                    )
                    counts["updated"] += 1
                else:
                    counts["duplicates"] += 1
                    con.execute(
                        "UPDATE jobs SET last_checked_at=?,source_updated_at=COALESCE(?,source_updated_at) "
                        "WHERE id=?",
                        (now, job.get("source_updated_at") or None, canonical_id))
            _record_source(con, job, canonical_id, now)
            if url_key:
                known_urls[url_key] = canonical_id
    return counts if return_details else counts["new"]


def log_run(
    found, added, message="Completed", status="success", details=None,
    started_at=None,
):
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        con.execute("INSERT INTO runs(started_at,completed_at,jobs_found,new_jobs,message,status,details_json) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (started_at or now, now, found, added, message, status,
                     json.dumps(details or {}, ensure_ascii=False)))


def update_source_refresh_state(source, status, error="", succeeded=False, next_due_at=None):
    now = datetime.now().isoformat(timespec="seconds")
    success_at = now if succeeded else None
    with connect() as con:
        con.execute("""INSERT INTO source_refresh_state
            (source,last_attempted_at,last_successful_at,last_status,last_error,next_due_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(source) DO UPDATE SET
                last_attempted_at=excluded.last_attempted_at,
                last_successful_at=COALESCE(excluded.last_successful_at,source_refresh_state.last_successful_at),
                last_status=excluded.last_status,last_error=excluded.last_error,
                next_due_at=COALESCE(excluded.next_due_at,source_refresh_state.next_due_at)""",
            (source, now, success_at, status, error or None, next_due_at))


def get_source_refresh_state():
    with connect() as con:
        return {row["source"]: dict(row) for row in con.execute("SELECT * FROM source_refresh_state")}


def sources_due(source_intervals, now=None):
    now = now or datetime.now()
    state = get_source_refresh_state()
    due = []
    for source, minutes in source_intervals.items():
        source_state = state.get(source, {})
        next_due = source_state.get("next_due_at")
        last = source_state.get("last_successful_at")
        if next_due:
            try:
                if now < datetime.fromisoformat(next_due):
                    continue
            except ValueError:
                pass
        elif not last:
            due.append(source)
            continue
        else:
            try:
                elapsed = now - datetime.fromisoformat(last)
            except ValueError:
                due.append(source)
                continue
            if elapsed < timedelta(minutes=minutes):
                continue
        due.append(source)
    return due


def get_search_schedule_state():
    with connect() as con:
        row = con.execute("SELECT * FROM search_schedule_state WHERE id=1").fetchone()
        return dict(row) if row else None


def set_search_schedule_state(started_at, next_scheduled_at, poll_seconds):
    now = datetime.now().isoformat(timespec="seconds")
    with connect() as con:
        con.execute("""INSERT INTO search_schedule_state
            (id,scheduler_started_at,next_scheduled_at,poll_seconds,updated_at)
            VALUES(1,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET scheduler_started_at=excluded.scheduler_started_at,
                next_scheduled_at=excluded.next_scheduled_at,poll_seconds=excluded.poll_seconds,
                updated_at=excluded.updated_at""",
            (started_at, next_scheduled_at, poll_seconds, now))


def set_next_scheduled_search(next_scheduled_at):
    with connect() as con:
        con.execute("UPDATE search_schedule_state SET next_scheduled_at=?,updated_at=? WHERE id=1",
                    (next_scheduled_at, datetime.now().isoformat(timespec="seconds")))


def get_last_successful_search():
    with connect() as con:
        row = con.execute(
            "SELECT started_at,completed_at,jobs_found,new_jobs,details_json FROM runs "
            "WHERE status IN ('success','partial') ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        result = dict(row)
        result["details"] = json.loads(result.pop("details_json") or "{}")
        return result


def get_duplicate_stats():
    with connect() as con:
        canonical_jobs = con.execute(
            "SELECT COUNT(*) FROM jobs WHERE canonical_job_id=id OR canonical_job_id IS NULL"
        ).fetchone()[0]
        duplicate_rows = con.execute(
            "SELECT COUNT(*) FROM jobs WHERE canonical_job_id IS NOT NULL AND canonical_job_id!=id"
        ).fetchone()[0]
        duplicate_groups = con.execute(
            "SELECT COUNT(*) FROM (SELECT canonical_job_id FROM jobs "
            "WHERE canonical_job_id IS NOT NULL GROUP BY canonical_job_id HAVING COUNT(*)>1)"
        ).fetchone()[0]
        duplicate_source_records = con.execute(
            "SELECT COALESCE(SUM(MAX(job_count,source_count)-1),0) FROM ("
            "SELECT j.canonical_job_id,COUNT(DISTINCT j.id) AS job_count,"
            "COUNT(DISTINCT r.source) AS source_count FROM jobs j "
            "LEFT JOIN job_source_records r ON r.canonical_job_id=j.canonical_job_id "
            "GROUP BY j.canonical_job_id HAVING job_count>1 OR source_count>1)"
        ).fetchone()[0]
    return {
        "unique_jobs": canonical_jobs,
        "duplicate_rows_grouped": duplicate_rows,
        "duplicate_groups": duplicate_groups,
        "duplicate_source_records": duplicate_source_records,
        "duplicate_listings": duplicate_source_records,
    }


def get_jobs(min_score=0, status=None, work_mode=None, query=None):
    sql = (
        "SELECT * FROM jobs WHERE COALESCE(match_score,0)>=? "
        "AND (canonical_job_id=id OR canonical_job_id IS NULL)"
    )
    args = [min_score]
    if status and status != "All": sql += " AND status=?"; args.append(status)
    if work_mode and work_mode != "All": sql += " AND COALESCE(work_mode,'Not specified')=?"; args.append(work_mode)
    if query:
        sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
        like=f"%{query}%"; args.extend([like,like,like])
    sql += " ORDER BY COALESCE(freshness_rank,8), match_score DESC, discovered_at DESC"
    with connect() as con:
        jobs = [dict(row) for row in con.execute(sql, args).fetchall()]
        for job in jobs:
            job["canonical_job_id"] = job.get("canonical_job_id") or job["id"]
        if not jobs:
            return jobs
        ids = [job["id"] for job in jobs]
        placeholders = ",".join("?" for _ in ids)
        records = con.execute(
            f"SELECT canonical_job_id,source,source_job_id,url FROM job_source_records "
            f"WHERE canonical_job_id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    by_id = {job["id"]: job for job in jobs}
    for job in jobs:
        job["source_records"] = []
    for record in records:
        job = by_id.get(record["canonical_job_id"])
        if job is not None:
            job["source_records"].append(dict(record))
    for job in jobs:
        sources = list(dict.fromkeys(
            record["source"] for record in job["source_records"] if record.get("source")
        ))
        job["sources"] = sources or ([job.get("source")] if job.get("source") else [])
        if job["sources"]:
            job["source"] = ", ".join(job["sources"])
    return jobs


def update_status(job_id,status):
    with connect() as con:
        row = con.execute("SELECT COALESCE(canonical_job_id,id) FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row:
            con.execute(
                "UPDATE jobs SET status=? WHERE COALESCE(canonical_job_id,id)=?",
                (status, row[0]))


def stats():
    with connect() as con:
        total=con.execute(
            "SELECT COUNT(*) FROM jobs WHERE canonical_job_id=id OR canonical_job_id IS NULL"
        ).fetchone()[0]
        matched=con.execute(
            "SELECT COUNT(*) FROM jobs WHERE match_score>=60 AND "
            "(canonical_job_id=id OR canonical_job_id IS NULL)"
        ).fetchone()[0]
        applied=con.execute("SELECT COUNT(*) FROM applications WHERE status='Submitted'").fetchone()[0]
        pending=con.execute("SELECT COUNT(*) FROM applications WHERE status IN ('PendingApproval','Approved')").fetchone()[0]
    return total,matched,applied,pending


def work_mode_counts():
    with connect() as con:
        return {r[0] or "Not specified":r[1] for r in con.execute(
            "SELECT COALESCE(work_mode,'Not specified'),COUNT(*) FROM jobs "
            "WHERE canonical_job_id=id OR canonical_job_id IS NULL "
            "GROUP BY COALESCE(work_mode,'Not specified')")}


def get_application(job_id):
    with connect() as con:
        canonical = con.execute(
            "SELECT COALESCE(canonical_job_id,id) FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        canonical_id = canonical[0] if canonical else job_id
        row = con.execute(
            "SELECT a.* FROM applications a JOIN jobs j ON j.id=a.job_id "
            "WHERE COALESCE(j.canonical_job_id,j.id)=? ORDER BY a.id LIMIT 1",
            (canonical_id,),
        ).fetchone()
        return dict(row) if row else None


def queue_application(job,resume_path):
    with connect() as con:
        canonical = con.execute(
            "SELECT COALESCE(canonical_job_id,id) FROM jobs WHERE id=?", (job["id"],)
        ).fetchone()
        canonical_id = canonical[0] if canonical else job["id"]
        existing = con.execute(
            "SELECT 1 FROM applications a JOIN jobs j ON j.id=a.job_id "
            "WHERE COALESCE(j.canonical_job_id,j.id)=? LIMIT 1",
            (canonical_id,),
        ).fetchone()
        if existing:
            return
        con.execute("""INSERT OR IGNORE INTO applications(job_id,company,title,url,status,detail,resume_path)
            VALUES(?,?,?,?,?,?,?)""",(canonical_id,job["company"],job["title"],job.get("url",""),"PendingApproval","Prepared for user review; not submitted.",resume_path))
        con.execute("UPDATE jobs SET status='PendingApproval' WHERE COALESCE(canonical_job_id,id)=?",(canonical_id,))


def set_application_status(job_id,status,detail=""):
    allowed={"PendingApproval","Approved","Submitted","Rejected"}
    if status not in allowed: raise ValueError(f"Unsupported application status: {status}")
    with connect() as con:
        canonical = con.execute(
            "SELECT COALESCE(canonical_job_id,id) FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        canonical_id = canonical[0] if canonical else job_id
        application = con.execute(
            "SELECT a.id FROM applications a JOIN jobs j ON j.id=a.job_id "
            "WHERE COALESCE(j.canonical_job_id,j.id)=? ORDER BY a.id LIMIT 1",
            (canonical_id,),
        ).fetchone()
        if application is None:
            return
        target_application_id = application["id"]
        if status=="Approved":
            con.execute("UPDATE applications SET status=?,detail=?,approved_at=CURRENT_TIMESTAMP WHERE id=?",(status,detail[:1500],target_application_id))
        elif status=="Submitted":
            con.execute("UPDATE applications SET status=?,detail=?,submitted_at=CURRENT_TIMESTAMP,applied_at=CURRENT_TIMESTAMP WHERE id=?",(status,detail[:1500],target_application_id))
        else:
            con.execute("UPDATE applications SET status=?,detail=? WHERE id=?",(status,detail[:1500],target_application_id))
        con.execute("UPDATE jobs SET status=? WHERE COALESCE(canonical_job_id,id)=?",(status,canonical_id))


def already_processed(job_id): return get_application(job_id) is not None


def record_application(job,status,detail):
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO applications(job_id,company,title,url,status,detail) VALUES(?,?,?,?,?,?)",(job["id"],job["company"],job["title"],job.get("url",""),status,detail[:1500]))
        con.execute("UPDATE jobs SET status=? WHERE id=?",(status,job["id"]))


def daily_application_count():
    with connect() as con:
        return con.execute("SELECT COUNT(*) FROM applications WHERE status='Submitted' AND date(COALESCE(submitted_at,applied_at))=date('now','localtime')").fetchone()[0]


def application_rows(limit=100):
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM applications ORDER BY applied_at DESC LIMIT ?",(limit,)).fetchall()]
