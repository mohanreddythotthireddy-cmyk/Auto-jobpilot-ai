import pandas as pd
from datetime import datetime
from pathlib import Path
from collections import Counter
import time
import streamlit as st

from db import (
    init_db, get_jobs, stats, update_status, queue_application,
    application_rows, set_application_status,
    daily_application_count, get_last_successful_search, get_search_schedule_state,
    get_source_refresh_state, get_duplicate_stats,
)
from resume_builder import build_resume
from config import DAILY_APPLICATION_LIMIT, ACTIVE_RESUME_PATH, SOURCE_REFRESH_MINUTES, UPLOAD_DIR
from config import INCLUDE_OTHER_INDIAN_CITIES
from matcher import is_internship
from resume_profile_service import ensure_resume_profile, ingest_resume, profile_from_db
from job_sources import MANUAL_SEARCH_LINKS, source_specs
from run_search import run_search
from work_mode import (
    is_bengaluru,
    is_india_listing,
    is_india_remote_or_hybrid,
    location_category,
    location_priority,
)

st.set_page_config(page_title="JobPilot AI", page_icon="🧭", layout="wide")
init_db()

st.title("🧭 JobPilot AI")
st.caption(
    "Bengaluru fresher job discovery, resume preparation "
    "and human-approved applications"
)

total, matched, applied, pending = stats()
duplicate_summary = get_duplicate_stats()
all_jobs = get_jobs()
last_search = get_last_successful_search()
last_search_details = last_search.get("details", {}) if last_search else {}
new_this_cycle = int(last_search_details.get("new_jobs", last_search.get("new_jobs", 0) if last_search else 0))
updated_this_cycle = int(last_search_details.get("existing_updated", 0))
duplicates_this_cycle = int(last_search_details.get("duplicates", 0))
fresh_jobs = sum(int(job.get("freshness_rank") or 8) <= 6 for job in all_jobs)
strong_jobs = sum(int(job.get("match_score") or 0) >= 70 for job in all_jobs)
bengaluru_jobs = sum(is_bengaluru(job.get("location")) for job in all_jobs)


def _job_rows(items):
    rows = []
    for job in items:
        score = int(job.get("match_score") or 0)
        tier = (
            "Excellent match" if score >= 80 else
            "Strong match" if score >= 70 else
            "Good match" if score >= 60 else
            "Partial match" if score >= 40 else "Low match"
        )
        rows.append({
            "Job title": job.get("title"),
            "Application URL": job.get("url"),
            "Company": job.get("company"),
            "Location": job.get("location"),
            "Work mode": job.get("work_mode") or "Not specified",
            "Match score": score,
            "Match tier": tier,
            "Matched skills": job.get("matched_skills"),
            "Missing required skills": job.get("missing_required_skills"),
            "Experience requirement": job.get("experience_requirement") or "Not stated",
            "Location match": location_category(job),
            "Job type": "Internship" if is_internship(job) else (
                job.get("job_type") or "Not specified"
            ),
            "Source": job.get("source"),
            "Posted": job.get("posted"),
            "Source updated": job.get("source_updated_at") or "Not reported",
            "Freshness": job.get("freshness_bucket") or "Date unknown",
            "Last seen": job.get("last_checked_at") or "Not verified",
            "Status": job.get("status"),
        })
    return rows


def _source_connection_label(source, configured):
    if not configured:
        return "Not configured"
    status = source.get("last_status")
    if status in {"searched", "empty_results", "partial"}:
        return "Connected"
    if status == "not_due":
        return "Awaiting next interval"
    if status:
        return "Failed"
    return "Not tested"


def _discovered_in_last_cycle(job, last_search):
    if not last_search or not last_search.get("started_at"):
        return False
    details = last_search.get("details") or {}
    if job.get("id") in details.get("new_job_ids", []):
        return True
    discovered = job.get("first_discovered_at") or job.get("discovered_at")
    if not discovered:
        return False
    try:
        first_seen = datetime.fromisoformat(str(discovered).replace("Z", "+00:00"))
        cycle_started = datetime.fromisoformat(
            str(last_search["started_at"]).replace("Z", "+00:00")
        )
        if first_seen.tzinfo:
            first_seen = first_seen.astimezone().replace(tzinfo=None)
        if cycle_started.tzinfo:
            cycle_started = cycle_started.astimezone().replace(tzinfo=None)
        return first_seen >= cycle_started
    except ValueError:
        return False


def _source_connection(source):
    if source.get("status") == "not_configured":
        return "Not configured"
    if source.get("status") == "not_due":
        return "Awaiting refresh interval"
    if source.get("connection_ok"):
        return "Connected"
    return "Failed" if source.get("configured") else "Not configured"

metrics = st.columns(6)
metrics[0].metric("Total unique jobs", total)
metrics[1].metric("New jobs this cycle", new_this_cycle)
metrics[2].metric("Updated this cycle", updated_this_cycle)
metrics[3].metric("Duplicate listings this cycle", duplicates_this_cycle)
metrics[4].metric("Fresh jobs (last 30 days)", fresh_jobs)
metrics[5].metric("Excellent / strong matches", strong_jobs)

application_metrics = st.columns(5)
application_metrics[0].metric("Bengaluru jobs", bengaluru_jobs)
application_metrics[1].metric("Duplicate listings grouped", duplicate_summary["duplicate_listings"])
application_metrics[2].metric("Good+ resume matches", matched)
application_metrics[3].metric("Confirmed applications", applied)
application_metrics[4].metric("Applications to review", pending)

with st.sidebar:
    st.header("Filters")
    st.header("Resume Intelligence")
    uploaded = st.file_uploader("Upload resume (PDF/DOCX/MD/TXT)", type=["pdf", "docx", "md", "txt"])
    if uploaded is not None and st.button("Analyze uploaded resume"):
        try:
            path, state, rid, profile = ingest_resume(uploaded)
            st.success(f"Resume analyzed: {len(profile.get('skills', []))} skills detected. Review extracted details below.")
            st.session_state["ri_active_resume_path"] = str(path)
        except Exception as exc:
            st.error(f"Resume analysis failed: {exc}")
    if st.button("Analyze configured master resume"):
        try:
            state, rid, profile = ensure_resume_profile(force=True)
            st.success(f"Resume analyzed: {len(profile.get('skills', []))} skills detected.")
        except Exception as exc:
            st.error(str(exc))
    try:
        profile = profile_from_db()
        st.caption(f"Active resume: {profile.get('resume', {}).get('source_path', 'Unknown')}")
        st.caption(f"Detected skills: {len(profile.get('skills', []))} | Experience: {profile.get('experience_level', 'Unclear')}")
        with st.expander("Review extracted resume details"):
            st.write("**Detected skills**")
            st.dataframe(pd.DataFrame([{"Skill": x.get("name"), "Category": x.get("category"), "Evidence sections": ", ".join(x.get("found_in", []))} for x in profile.get("skills", [])]), use_container_width=True, hide_index=True)
            st.write("**Projects detected**")
            st.dataframe(pd.DataFrame([{"Project": x.get("name"), "Technologies": ", ".join(x.get("technologies_raw", []))} for x in profile.get("projects", [])]), use_container_width=True, hide_index=True)
            if profile.get("warnings"):
                st.warning("Resume parser warnings: " + "; ".join(profile["warnings"]))
            if profile.get("missing_unclear"):
                st.info(f"Items to review: {len(profile['missing_unclear'])}. Check the source resume for missing or unclear details.")
    except Exception as exc:
        st.warning(f"Resume profile not ready: {exc}")
    st.divider()

    score_range = st.slider("Match score range", 0, 100, (40, 100))

    status_filter = st.selectbox(
        "Job status",
        [
            "All", "New", "Shortlisted", "PendingApproval",
            "Approved", "Applied", "Submitted", "Rejected", "Interview"
        ],
    )

    include_other_cities = st.checkbox(
        "Include other Indian cities",
        value=INCLUDE_OTHER_INDIAN_CITIES,
        help="When disabled, show Bengaluru, explicitly India-eligible remote, and unknown-location review items only.",
    )
    location_filter = st.selectbox(
        "City / location group",
        [
            "All",
            "Bengaluru",
            "Major Indian city",
            "Other India",
            "Remote India",
            "Unknown / manual review",
            "Outside India (historical)",
        ],
    )

    title_filter = st.text_input("Job role filter")
    company_filter = st.text_input("Company filter")
    specific_location_filter = st.text_input("Location filter")

    experience_options = ["All"] + sorted({
        str(job.get("experience_requirement"))
        for job in all_jobs if job.get("experience_requirement")
    })
    experience_filter = st.selectbox("Required experience", experience_options)
    job_type_filter = st.selectbox(
        "Job type", ["All", "Internship", "Non-internship"]
    )

    freshness_filter = st.selectbox(
        "Posted within",
        ["All", "Last 24 hours", "Last 3 days", "Last 7 days", "Last 15 days", "Last 30 days",
         "Older than 30 days", "Date unknown"],
    )

    sources = sorted({
        source for job in all_jobs
        for source in ([job.get("source")] + [
            record.get("source") for record in job.get("source_records", [])
        ])
        if source
    })
    source_filter = st.selectbox("Source", ["All"] + sources)
    search_text = st.text_input("Search title, company or location")

    cooldown_seconds = 30
    last_manual_refresh = st.session_state.get("last_manual_refresh", 0.0)
    cooldown_remaining = max(
        0, int(cooldown_seconds - (time.monotonic() - last_manual_refresh))
    )
    if st.button(
        "Refresh job listings now",
        disabled=cooldown_remaining > 0 or st.session_state.get("refresh_in_progress", False),
    ):
        st.session_state["last_manual_refresh"] = time.monotonic()
        st.session_state["refresh_in_progress"] = True
        try:
            search_report = run_search(
                force=False,
                print_report=False,
                return_report=True,
                include_other_cities=include_other_cities,
            )
            if search_report["status"] == "success":
                st.success(
                    f"Search complete: {search_report['new_jobs']} new jobs, "
                    f"{search_report['existing_updated']} updated."
                )
            elif search_report["status"] == "partial":
                st.warning(
                    f"Search partially completed: {search_report['new_jobs']} new jobs. "
                    "Review source diagnostics below."
                )
            elif search_report["status"] == "no_sources":
                st.info(
                    "No source refresh interval is due yet. Existing listings remain available."
                )
            else:
                st.error("No job source completed a connection. See source diagnostics.")
            st.dataframe(
                [{
                    "Source": s["source"], "Status": s["status"],
                    "Connection": (
                        "Awaiting next interval" if s["status"] == "not_due"
                        else "Not configured" if s["status"] == "not_configured"
                        else "Connected" if s["connection_ok"]
                        else "Failed"
                    ), "HTTP": s["http_status"],
                    "Returned": s["returned"], "After filtering": s["after_filtering"],
                    "India": s["india_listings"], "Bengaluru": s["bengaluru_listings"],
                    "Fresh (30d)": s["fresh_listings"],
                    "Rejected: location": s["rejected_by_location"],
                    "Rejected: role": s["rejected_by_role"],
                    "Rejected: experience": s["rejected_by_experience"],
                    "Rejected total": s["rejected"],
                    "Rejection reasons": s["rejection_reasons"],
                    "New": s["new_jobs"], "Updated": s["existing_updated"],
                    "Duplicates": s["duplicates"], "Error": s["error"],
                } for s in search_report["sources"]],
                use_container_width=True, hide_index=True,
            )
        except Exception as exc:
            st.error(f"Job search failed: {type(exc).__name__}: {exc}")
        finally:
            st.session_state["refresh_in_progress"] = False
    elif cooldown_remaining:
        st.caption(f"Manual refresh available in {cooldown_remaining} seconds.")

    if last_search:
        st.caption(f"Last successful refresh: {last_search.get('completed_at') or 'Unknown'}")
    schedule = get_search_schedule_state()
    if schedule and schedule.get("next_scheduled_at"):
        next_poll = schedule["next_scheduled_at"]
        try:
            if datetime.fromisoformat(next_poll) >= datetime.now():
                st.caption(f"Next scheduled refresh poll: {next_poll}")
            else:
                st.warning(
                    f"Scheduled refresh poll was due at {next_poll}; "
                    "the scheduler may not be running."
                )
        except ValueError:
            st.warning(f"Invalid next scheduled refresh timestamp: {next_poll}")
    else:
        st.caption("Automatic source polling is not running.")
    source_state = get_source_refresh_state()
    latest_source_reports = {
        report["source"]: report
        for report in last_search_details.get("sources", [])
    }
    source_config = {
        spec.name: spec.configured for spec in source_specs([])
    }
    with st.expander("Source connection and refresh status"):
        st.dataframe(
            [{
                "Source": source,
                "Connection": _source_connection_label(source_state.get(source, {}), source_config.get(source, False)),
                "Interval (minutes)": interval,
                "API status": latest_source_reports.get(source, {}).get("status", "Not run"),
                "HTTP": latest_source_reports.get(source, {}).get("http_status") or "—",
                "Returned": latest_source_reports.get(source, {}).get("returned", 0),
                "India": latest_source_reports.get(source, {}).get("india_listings", 0),
                "Bengaluru": latest_source_reports.get(source, {}).get("bengaluru_listings", 0),
                "Fresh (30d)": latest_source_reports.get(source, {}).get("fresh_listings", 0),
                "Accepted": latest_source_reports.get(source, {}).get("after_filtering", 0),
                "Rejected": latest_source_reports.get(source, {}).get("rejected", 0),
                "Rejection reasons": latest_source_reports.get(source, {}).get("rejection_reasons", {}),
                "New": latest_source_reports.get(source, {}).get("new_jobs", 0),
                "Updated": latest_source_reports.get(source, {}).get("existing_updated", 0),
                "Duplicates": latest_source_reports.get(source, {}).get("duplicates", 0),
                "Last successful refresh": source_state.get(source, {}).get("last_successful_at") or "Never",
                "Next due": source_state.get(source, {}).get("next_due_at") or "Not scheduled",
                "Last status": source_state.get(source, {}).get("last_status") or "Not run",
                "Last error": source_state.get(source, {}).get("last_error") or "",
            } for source, interval in SOURCE_REFRESH_MINUTES.items()],
            use_container_width=True, hide_index=True,
        )

    st.caption(
        f"Daily submission cap: {DAILY_APPLICATION_LIMIT}. "
        "Every application requires your review."
    )

    with st.expander("Manual platform searches"):
        st.caption(
            "These links open job sites for manual searching; no unsupported direct "
            "integrations or automated submissions are claimed."
        )
        st.write("**Employment**")
        for name, url in MANUAL_SEARCH_LINKS.items():
            if "(freelance)" not in name:
                st.markdown(f"- [{name}]({url})")
        st.write("**Freelance only — not added to employment applications**")
        for name, url in MANUAL_SEARCH_LINKS.items():
            if "(freelance)" in name:
                st.markdown(f"- [{name.replace(' (freelance)', '')}]({url})")

    st.info(
        "Run `python run_search.py` to discover jobs. "
        "Run `python scheduler.py` for daily discovery."
    )

jobs = [
    job for job in all_jobs
    if score_range[0] <= int(job.get("match_score") or 0) <= score_range[1]
    and (status_filter == "All" or job.get("status") == status_filter)
    and (
        experience_filter == "All"
        or job.get("experience_requirement") == experience_filter
    )
    and (
        job_type_filter == "All"
        or (job_type_filter == "Internship") == is_internship(job)
    )
    and (
        source_filter == "All"
        or job.get("source") == source_filter
        or any(record.get("source") == source_filter for record in job.get("source_records", []))
    )
]

if not include_other_cities:
    jobs = [
        job for job in jobs
        if location_category(job) not in {"Major Indian city", "Other India"}
    ]

if location_filter != "All":
    if location_filter == "Remote India":
        jobs = [job for job in jobs if is_india_remote_or_hybrid(job)]
    else:
        selected_category = {
            "Major Indian city": "Major Indian city",
            "Other India": "Other India",
            "Unknown / manual review": "Unknown / manual review",
            "Outside India (historical)": "Outside India",
        }.get(location_filter, location_filter)
        jobs = [
            job for job in jobs
            if location_category(job) == selected_category
        ]

if freshness_filter != "All":
    freshness_predicates = {
        "Last 24 hours": lambda rank: rank <= 2,
        "Last 3 days": lambda rank: rank <= 3,
        "Last 7 days": lambda rank: rank <= 4,
        "Last 15 days": lambda rank: rank <= 5,
        "Last 30 days": lambda rank: rank <= 6,
        "Older than 30 days": lambda rank: rank == 7,
        "Date unknown": lambda rank: rank == 8,
    }
    predicate = freshness_predicates[freshness_filter]
    jobs = [
        job for job in jobs
        if predicate(int(job.get("freshness_rank") or 8))
    ]

for field, value in (
    ("title", title_filter),
    ("company", company_filter),
    ("location", specific_location_filter),
):
    if value.strip():
        jobs = [
            job for job in jobs
            if value.strip().casefold() in str(job.get(field) or "").casefold()
        ]

if search_text.strip():
    query = search_text.strip().casefold()
    jobs = [
        job for job in jobs
        if any(query in str(job.get(field) or "").casefold()
               for field in ("title", "company", "location"))
    ]

jobs.sort(
    key=lambda job: (
        location_priority(job),
        int(job.get("freshness_rank") or 8),
        -int(job.get("match_score") or 0),
    )
)

india_jobs = [job for job in all_jobs if is_india_listing(job)]
city_counts = Counter(job.get("location") or "Unknown" for job in india_jobs)
source_counts = Counter(
    source for job in all_jobs
    for source in (job.get("sources") or ([job.get("source")] if job.get("source") else []))
)

st.subheader("Job discovery overview")

overview = st.columns(5)
overview[0].metric("India-eligible jobs", len(india_jobs))
overview[1].metric("Bengaluru", bengaluru_jobs)
overview[2].metric("Other Indian cities", sum(
    location_category(job) in {"Major Indian city", "Other India"}
    for job in all_jobs
))
overview[3].metric("Explicit Remote India", sum(
    is_india_remote_or_hybrid(job) for job in all_jobs
))
overview[4].metric("Unknown location review", sum(
    location_category(job) == "Unknown / manual review" for job in all_jobs
))

with st.expander("Jobs by city and source"):
    city_col, source_col = st.columns(2)
    city_col.dataframe(
        pd.DataFrame(
            [{"City / location": city, "Unique jobs": count}
             for city, count in city_counts.most_common()]
        ),
        use_container_width=True,
        hide_index=True,
    )
    source_col.dataframe(
        pd.DataFrame(
            [{"Source": source, "Unique jobs": count}
             for source, count in source_counts.most_common()]
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()

if not jobs:
    st.warning(
        "No jobs match these filters. Lower the match score, "
        "change the work arrangement, or run a job search."
    )
else:
    non_internships = [job for job in jobs if not is_internship(job)]
    internships = [job for job in jobs if is_internship(job)]
    categories = [
        ("Bengaluru Fresher Jobs", [
            job for job in non_internships
            if is_bengaluru(job.get("location"))
            and job.get("experience_fit") == "Fresher-friendly"
        ]),
        ("Newly Discovered India Jobs", [
            job for job in non_internships
            if is_india_listing(job) and _discovered_in_last_cycle(job, last_search)
        ]),
        ("Jobs posted in the last 24 hours", [
            job for job in non_internships if int(job.get("freshness_rank") or 8) <= 2
        ]),
        ("Jobs posted in the last 7 days", [
            job for job in non_internships if int(job.get("freshness_rank") or 8) <= 4
        ]),
        ("Other Indian City Jobs", [
            job for job in non_internships
            if location_category(job) in {"Major Indian city", "Other India"}
        ]),
        ("Remote India Jobs", [
            job for job in non_internships if is_india_remote_or_hybrid(job)
        ]),
        ("Excellent and Strong Resume Matches", [
            job for job in non_internships if int(job.get("match_score") or 0) >= 70
        ]),
        ("Good Matches", [
            job for job in non_internships
            if 60 <= int(job.get("match_score") or 0) < 70
        ]),
        ("Internships", internships),
        ("Unknown Location / Manual Review", [
            job for job in non_internships
            if location_category(job) == "Unknown / manual review"
            or bool(job.get("manual_review_required"))
        ]),
        ("Previously Discovered Jobs", [
            job for job in non_internships
            if not _discovered_in_last_cycle(job, last_search)
        ]),
        ("All Non-internship Jobs", non_internships),
    ]
    category_tabs = st.tabs([category[0] for category in categories])
    for tab, (name, items) in zip(category_tabs, categories):
        with tab:
            st.subheader(f"{name} ({len(items)})")
            if items:
                st.dataframe(
                    pd.DataFrame(_job_rows(items)),
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "Application URL": st.column_config.LinkColumn(
                            "Original application URL",
                            display_text="Open original listing",
                        )
                    },
                )
            else:
                st.info("No jobs in this category match the current filters.")

    st.subheader("Review a job")

    choices = {
        f"{j['title']} — {j['company']} ({j['match_score']}%)": j
        for j in jobs
    }

    selected = st.selectbox("Choose job", list(choices.keys()))
    job = choices[selected]

    st.subheader(f"Selected target job: {job['title']}")
    st.markdown(
        f"**Company:** {job['company']} | "
        f"**Location:** {job['location']}"
    )

    st.markdown(
        f"**Work arrangement:** "
        f"{job.get('work_mode') or 'Not specified'}"
    )

    with st.expander("Role alignment and keyword match analysis", expanded=True):
        st.markdown(f"**Keyword match score:** {job['match_score']}%")
        st.markdown(f"**Experience requirement:** {job.get('experience_requirement') or 'Not stated'}")
        st.markdown(f"**Location match:** {location_category(job)}")
        st.markdown(f"**Matched skills:** {job['matched_skills']}")
        if job.get("match_explanation"):
            st.caption(job["match_explanation"])
        if job.get("missing_requirements"):
            st.warning("; ".join(job["missing_requirements"]))

    with st.expander("Full job description"):
        st.write(job.get("description") or "No job description available.")

    generated_resume_key = f"tailored_resume_{job['id']}"
    if st.button("Generate Tailored Resume (PDF)", width="stretch"):
        try:
            generated_path = build_resume(job)
            st.session_state[generated_resume_key] = str(generated_path.resolve())
            st.success(f"PDF resume generated for {job['title']}.")
        except Exception as exc:
            st.error(f"Could not generate tailored resume: {exc}")

    generated_path = Path(st.session_state.get(generated_resume_key, ""))
    if generated_path.is_file():
        st.download_button(
            "Download tailored resume (PDF)",
            generated_path.read_bytes(),
            file_name=generated_path.name,
            mime="application/pdf",
            width="stretch",
            key=f"download_tailored_resume_{job['id']}",
        )

    if job.get("url"):
        st.markdown(f"[Open original job posting]({job['url']})")
    alternate_sources = [
        record for record in job.get("source_records", [])
        if record.get("url") and record.get("url") != job.get("url")
    ]
    if alternate_sources:
        with st.expander("Other source listings for this vacancy"):
            for record in alternate_sources:
                st.markdown(
                    f"- [{record.get('source') or 'Source'} listing]({record['url']}) "
                    f"(source ID: `{record.get('source_job_id')}`)"
                )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Shortlist job", width="stretch"):
            update_status(job["id"], "Shortlisted")
            st.rerun()

    with col2:
        if st.button(
            "Prepare application for my approval",
            width="stretch"
        ):
            try:
                resume_path = build_resume(job)
                queue_application(job, str(resume_path.resolve()))
                st.success(
                    "Application prepared and added to your approval queue. "
                    "Nothing has been submitted."
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Could not prepare application: {exc}")

st.divider()
st.subheader("Application approval queue")

st.caption(
    "Review each job and resume. Approving opens the employer's "
    "official posting; you complete and submit the form yourself."
)

queue = [
    x for x in application_rows(200)
    if x["status"] in ("PendingApproval", "Approved")
]

if not queue:
    st.info(
        "No applications are waiting for your approval. "
        "Select a job above and prepare an application."
    )
else:
    for item in queue:
        with st.container(border=True):
            st.markdown(f"**{item['title']} — {item['company']}**")
            st.caption(f"Status: {item['status']} | {item['url']}")

            resume_path = item.get("resume_path") or ""

            if resume_path and Path(resume_path).exists():
                rp = Path(resume_path)

                st.download_button(
                    f"Download resume — {rp.name}",
                    rp.read_bytes(),
                    file_name=rp.name,
                    mime="application/pdf",
                    key=f"resume_{item['job_id']}",
                )

            if item["status"] == "PendingApproval":
                confirm = st.checkbox(
                    "I reviewed this job and resume, and approve "
                    "proceeding to the employer's application page.",
                    key=f"confirm_{item['job_id']}",
                )

                if st.button(
                    "Approve & open official application",
                    key=f"approve_{item['job_id']}",
                    disabled=not confirm,
                ):
                    set_application_status(
                        item["job_id"],
                        "Approved",
                        "User approved; official application page opened for manual completion."
                    )

                    st.success(
                        "Approved. Open the employer application below, "
                        "complete it yourself, and confirm submission afterward."
                    )
                    st.rerun()

            else:
                st.link_button(
                    "Open employer application",
                    item["url"],
                    width="stretch"
                )

                submitted = st.checkbox(
                    "I have personally submitted this application "
                    "on the employer's website.",
                    key=f"submitted_{item['job_id']}",
                )

                if submitted and st.button(
                    "Confirm application submitted",
                    key=f"confirm_submit_{item['job_id']}",
                ):
                    set_application_status(
                        item["job_id"],
                        "Submitted",
                        "User confirmed they submitted on the employer's website."
                    )
                    st.success("Submission recorded based on your confirmation.")
                    st.rerun()

                if st.button(
                    "Return to pending approval",
                    key=f"revoke_{item['job_id']}",
                ):
                    set_application_status(
                        item["job_id"],
                        "PendingApproval",
                        "Approval withdrawn by user."
                    )
                    st.rerun()

st.subheader("Application history")

history = application_rows(100)

if history:
    st.dataframe(
        pd.DataFrame(history),
        width="stretch",
        hide_index=True
    )
else:
    st.info("No application records yet.")

today_count = daily_application_count()

st.caption(
    f"Confirmed submissions today: {today_count}/{DAILY_APPLICATION_LIMIT}. "
    "JobPilot never clicks Submit automatically. CAPTCHA, OTP, login "
    "and required declarations remain your responsibility."
)
