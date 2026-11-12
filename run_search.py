from __future__ import annotations

import contextlib
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from config import DB_PATH, SEARCH_POLL_SECONDS, SOURCE_REFRESH_MINUTES
from db import (
    init_db,
    log_run,
    save_jobs,
    sources_due,
    update_source_refresh_state,
)
from job_sources import SourceReport, fetch_sources, source_specs
from matcher import enrich, is_target_role, master_resume_profile
from resume_job_terms import generate_search_terms
from work_mode import (
    classify_work_mode,
    is_bengaluru,
    is_india_listing,
    location_filter_reason,
)


def freshness_window(posted, now=None):
    """Classify only the source's original publication date, never update time."""
    if not posted:
        return 8, "Date unknown"
    value = str(posted).strip()
    try:
        if value.isdigit():
            timestamp = int(value)
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            published = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        else:
            published = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        else:
            published = published.astimezone(timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        else:
            current = current.astimezone(timezone.utc)
        age = current - published
    except (OverflowError, OSError, TypeError, ValueError):
        return 8, "Date unknown"
    if age < timedelta(0):
        return 8, "Date unknown"
    if age <= timedelta(hours=1):
        return 1, "Last 1 hour"
    if age <= timedelta(days=1):
        return 2, "Last 24 hours"
    if age <= timedelta(days=3):
        return 3, "Last 3 days"
    if age <= timedelta(days=7):
        return 4, "Last 7 days"
    if age <= timedelta(days=15):
        return 5, "Last 15 days"
    if age <= timedelta(days=30):
        return 6, "Last 30 days"
    return 7, "Older than 30 days"


@contextlib.contextmanager
def _search_process_lock():
    lock_path = DB_PATH.parent / "jobpilot_search.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("Another job search is already running.") from exc
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _report_dict(report):
    return {
        "source": report.name,
        "configured": report.configured,
        "status": report.status,
        "connection_ok": report.connection_ok,
        "http_status": report.http_status,
        "pages": report.pages,
        "returned": report.returned,
        "india_listings": report.india_listings,
        "bengaluru_listings": report.bengaluru_listings,
        "fresh_listings": report.fresh_listings,
        "freshness_counts": report.freshness_counts,
        "after_filtering": report.after_filtering,
        "rejected": (
            report.rejected_by_location + report.rejected_by_role
            + report.rejected_by_experience + report.filter_errors
        ),
        "rejected_by_location": report.rejected_by_location,
        "rejected_by_role": report.rejected_by_role,
        "rejected_by_experience": report.rejected_by_experience,
        "new_jobs": report.saved,
        "existing_updated": report.updated,
        "duplicates": report.duplicates,
        "filter_errors": report.filter_errors,
        "database_error": report.database_error,
        "rejection_reasons": report.rejection_reasons,
        "error": report.error,
    }


def _print_report(report):
    print("\nSource diagnostics")
    for source in report["sources"]:
        connection = "connected" if source["connection_ok"] else "not connected"
        http_status = f", HTTP {source['http_status']}" if source["http_status"] else ""
        print(
            f"- {source['source']}: {source['status']} ({connection}{http_status}); "
            f"returned={source['returned']}, India={source['india_listings']}, "
            f"Bengaluru={source['bengaluru_listings']}, fresh<=30d={source['fresh_listings']}, "
            f"after_filtering={source['after_filtering']}, "
            f"rejected_location={source['rejected_by_location']}, "
            f"rejected_role={source['rejected_by_role']}, "
            f"rejected_experience={source['rejected_by_experience']}, "
            f"new={source['new_jobs']}, "
            f"updated={source['existing_updated']}, duplicates={source['duplicates']}"
        )
        if source["error"]:
            print(f"  Detail: {source['error']}")
        if source["filter_errors"]:
            print(f"  Scoring/filter errors: {source['filter_errors']}")
        if source["database_error"]:
            print(f"  Database error: {source['database_error']}")
    print(
        f"Search status: {report['status']}; sources actually searched: "
        f"{report['sources_searched']}; accepted: {report['jobs_after_filtering']}; "
        f"new: {report['new_jobs']}; updated: {report['existing_updated']}; "
        f"duplicates: {report['duplicates']}"
    )
    if report["warnings"]:
        for warning in report["warnings"]:
            print(f"Warning: {warning}")


def _run_search_unlocked(
    force=False, print_report=True, return_report=False, include_other_cities=None
):
    """Run due sources, continue after per-source failures, and return (found, added)."""
    started_at = datetime.now().isoformat(timespec="seconds")
    init_db()
    warnings = []
    try:
        profile = master_resume_profile()
    except (FileNotFoundError, OSError, ValueError, sqlite3.Error) as exc:
        profile = {"skills": []}
        warnings.append(
            f"Master resume profile unavailable; using targeted role terms without skill scoring "
            f"({type(exc).__name__})."
        )

    terms = generate_search_terms(profile)
    specs = (
        source_specs(terms)
        if include_other_cities is None
        else source_specs(terms, include_other_cities)
    )
    configured_sources = {
        spec.name for spec in specs if spec.configured
    }
    due = (
        [source for source in SOURCE_REFRESH_MINUTES if source in configured_sources]
        if force
        else [source for source in sources_due(SOURCE_REFRESH_MINUTES)
              if source in configured_sources]
    )
    selected = set(due)
    if include_other_cities is None:
        source_reports = fetch_sources(terms, only_sources=selected)
    else:
        source_reports = fetch_sources(
            terms, only_sources=selected,
            include_other_cities=include_other_cities,
        )
    fetched = {result.name: result for result in source_reports}
    reports = []
    for spec in specs:
        report = fetched.get(spec.name)
        if report is None:
            report = SourceReport(
                spec.name, spec.configured, "not_due" if spec.configured else "not_configured",
                error="Source-specific refresh interval has not elapsed." if spec.configured else spec.config_error,
            )
        reports.append(report)

    totals = {
        "accepted": 0, "new": 0, "updated": 0, "duplicates": 0,
        "new_job_ids": [],
    }
    freshness_buckets = {}
    database_errors = []
    for report in reports:
        for job in report.jobs:
            if is_india_listing(job):
                report.india_listings += 1
            if is_bengaluru(job.get("location")):
                report.bengaluru_listings += 1
            freshness_rank, freshness_bucket = freshness_window(job.get("posted"))
            report.freshness_counts[freshness_bucket] = (
                report.freshness_counts.get(freshness_bucket, 0) + 1
            )
            if freshness_rank <= 6:
                report.fresh_listings += 1
        if report.status not in {"searched", "empty_results", "partial"}:
            if report.configured and report.status != "not_due":
                retry_at = datetime.now() + timedelta(seconds=SEARCH_POLL_SECONDS)
                update_source_refresh_state(
                    report.name, report.status, report.error, succeeded=False,
                    next_due_at=retry_at.isoformat(timespec="seconds"),
                )
            continue

        accepted = []
        for job in report.jobs:
            keep, reason = location_filter_reason(
                job, include_other_cities=include_other_cities
            )
            if not keep:
                report.rejected_by_location += 1
                report.rejection_reasons[reason] = report.rejection_reasons.get(reason, 0) + 1
                continue
            try:
                job["work_mode"] = classify_work_mode(job)
                job["freshness_rank"], job["freshness_bucket"] = freshness_window(job.get("posted"))
                job = enrich(job, profile)
                if not is_target_role(job):
                    report.rejected_by_role += 1
                    reason = "job title is not in the fresher target-role families"
                    report.rejection_reasons[reason] = report.rejection_reasons.get(reason, 0) + 1
                    continue
                if job.get("exclude_for_experience"):
                    report.rejected_by_experience += 1
                    reason = "senior title or 5+ years of required experience"
                    report.rejection_reasons[reason] = report.rejection_reasons.get(reason, 0) + 1
                    continue
                report.after_filtering += 1
                accepted.append(job)
                bucket = job["freshness_bucket"]
                freshness_buckets[bucket] = freshness_buckets.get(bucket, 0) + 1
            except Exception as exc:
                report.filter_errors += 1
                report.error = (report.error + "; " if report.error else "") + (
                    f"job scoring failed ({type(exc).__name__}): {str(exc)[:160]}"
                )
                print(f"{report.name}: could not score listing {job.get('title')!r}: {exc}")

        totals["accepted"] += report.after_filtering
        try:
            saved = save_jobs(accepted, return_details=True)
            report.saved = saved["new"]
            report.updated = saved["updated"]
            report.duplicates = saved["duplicates"]
            totals["new"] += saved["new"]
            totals["updated"] += saved["updated"]
            totals["duplicates"] += saved["duplicates"]
            totals["new_job_ids"].extend(saved["new_job_ids"])
        except sqlite3.Error as exc:
            report.database_error = f"{type(exc).__name__}: {exc}"
            report.error = (report.error + "; " if report.error else "") + f"database save failed: {report.database_error}"
            database_errors.append(f"{report.name}: {report.database_error}")
            print(f"{report.name}: database save failed: {report.database_error}")

        next_due = datetime.now() + timedelta(minutes=SOURCE_REFRESH_MINUTES[report.name])
        update_source_refresh_state(
            report.name, report.status, report.error,
            succeeded=report.connection_ok and not report.database_error,
            next_due_at=next_due.isoformat(timespec="seconds"),
        )

    searched = sum(1 for report in reports if report.connection_ok)
    source_errors = sum(
        1 for report in reports
        if report.configured and (
            report.status not in {"searched", "empty_results", "partial", "not_due"}
            or report.status == "partial"
            or report.filter_errors
            or report.database_error
        )
    )
    if searched == 0:
        status = "failed" if source_errors else "no_sources"
    elif database_errors or source_errors:
        status = "partial"
    else:
        status = "success"

    summary = {
        "status": status,
        "terms_count": len(terms),
        "sources_searched": searched,
        "jobs_after_filtering": totals["accepted"],
        "new_jobs": totals["new"],
        "existing_updated": totals["updated"],
        "duplicates": totals["duplicates"],
        "new_job_ids": totals["new_job_ids"],
        "freshness_buckets": freshness_buckets,
        "rejected_by_location": sum(r.rejected_by_location for r in reports),
        "rejected_by_role": sum(r.rejected_by_role for r in reports),
        "rejected_by_experience": sum(r.rejected_by_experience for r in reports),
        "database_errors": database_errors,
        "warnings": warnings,
        "sources": [_report_dict(report) for report in reports],
    }
    summary_message = (
        f"{status}: {searched} sources connected; {totals['accepted']} accepted, "
        f"{totals['new']} new, {totals['updated']} updated, {totals['duplicates']} duplicates"
    )
    log_run(
        totals["accepted"], totals["new"], summary_message,
        status=status, details=summary, started_at=started_at,
    )
    if print_report:
        print(f"Generated search terms: {len(terms)}")
        print(f"Source polling interval: at least {SEARCH_POLL_SECONDS} seconds.")
        _print_report(summary)
        print(
            "Posting freshness windows to prioritize: 1 hour, 24 hours, 3, 7, "
            "15, and 30 days; older and unknown dates are separated. Source update timestamps are stored separately "
            "from original publication dates."
        )
        print(f"Completed at: {datetime.now().isoformat(timespec='seconds')}")
    if return_report:
        return summary
    return totals["accepted"], totals["new"]


def run_search(
    force=False, print_report=True, return_report=False, include_other_cities=None
):
    with _search_process_lock():
        return _run_search_unlocked(
            force, print_report, return_report, include_other_cities
        )


if __name__ == "__main__":
    run_search()
