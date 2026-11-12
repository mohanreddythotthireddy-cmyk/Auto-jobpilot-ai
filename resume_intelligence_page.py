from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from config import DB_PATH, MASTER_RESUME
from resume_intelligence import ResumeIntelligenceDB, summarize


def _db_path() -> Path:
    value = os.getenv("JOBPILOT_DB") or os.getenv("JOBPILOT_DB_PATH") or str(DB_PATH)
    return Path(value).expanduser()


def _master_resume_path() -> Path:
    value = os.getenv("JOBPILOT_MASTER_RESUME") or os.getenv("MASTER_RESUME_PATH") or str(MASTER_RESUME)
    return Path(value).expanduser()


def _load_profile() -> tuple[ResumeIntelligenceDB, dict | None, Path]:
    resume_path = _master_resume_path()
    db = ResumeIntelligenceDB(_db_path())
    if resume_path.exists():
        db.refresh_from_resume(resume_path, force=True)
        return db, db.get_profile(), resume_path
    return db, None, resume_path


def render() -> None:
    st.title("Resume Intelligence")
    resume_path = _master_resume_path()
    db, profile, resume_path = _load_profile()

    if not resume_path.exists():
        st.warning(f"Master resume not found: {resume_path}. Set JOBPILOT_MASTER_RESUME or place a resume at this path.")
        return

    if profile is None:
        st.warning("Resume could not be parsed into a profile.")
        return

    summary = summarize(profile)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total skills detected", summary.get("Total skills detected", len(profile["skills"])))
    c2.metric("Programming languages", summary.get("Programming languages", 0))
    c3.metric("Cloud technologies", summary.get("Cloud technologies", 0))
    c4.metric("Certifications", summary.get("Certifications", 0))

    tabs = st.tabs(["Overview", "Skills", "Projects", "Missing / unclear", "Corrections", "Raw profile"])

    with tabs[0]:
        st.subheader("Resume overview")
        st.write(f"Source: {profile['resume']['source_path']}")
        st.write(f"Name: {profile['resume'].get('name') or 'Unknown'}")
        st.write(f"Experience: {profile['experience_level']}")
        if profile.get("warnings"):
            st.warning("; ".join(profile["warnings"]))

    with tabs[1]:
        st.dataframe(
            [{"Skill": s["name"], "Category": s["category"], "In catalog": s["in_catalog"]} for s in profile["skills"]],
            use_container_width=True,
            hide_index=True,
        )
        skill_names = [s["name"] for s in profile["skills"]]
        if skill_names:
            selected = st.selectbox("Detected skill to remove", skill_names, key="rm_old")
            if st.button("Remove"):
                db.add_correction("remove", selected)
                st.success(f"Removed {selected} from the active profile.")
                st.rerun()

    with tabs[2]:
        st.dataframe(
            [{"Project": p["name"], "Technologies": ", ".join(p["technologies_raw"]) or "(none)"} for p in profile["projects"]],
            use_container_width=True,
            hide_index=True,
        )

    with tabs[3]:
        if profile.get("missing_unclear"):
            st.write("\n".join(profile["missing_unclear"]))
        else:
            st.success("No missing or unclear items flagged.")

    with tabs[4]:
        corrections = db.list_corrections()
        if corrections:
            st.dataframe(corrections, use_container_width=True, hide_index=True)
        else:
            st.caption("No manual corrections yet.")

    with tabs[5]:
        st.json({
            "summary": summary,
            "resume": profile["resume"],
            "skills": profile["skills"][0:10],
            "projects": profile["projects"],
            "uncaptured_terms": profile.get("uncaptured_terms", []),
        })
