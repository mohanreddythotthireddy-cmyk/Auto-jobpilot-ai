# JobPilot AI Complete Upgrade (Human-Approved)

This package integrates the Resume Intelligence parser and skill extractor into JobPilot AI. It is designed as a **separate upgrade copy**. It does not contain your `.env`, live SQLite database, or personal master resume.

## Safety and preservation
- The package never deletes or recreates your existing `jobs`, `applications`, or `runs` tables.
- `db.init_db()` performs additive column/index migrations only.
- Resume Intelligence creates only `ri_*` tables in the same SQLite database.
- Search metadata uses additive columns and new tracking tables; it does not drop or recreate existing tables.
- Existing job IDs, statuses, application rows and timestamps are preserved by migrations.
- `AUTONOMOUS_SUBMIT` is hard-disabled. The application workflow only prepares a resume and places a row in `PendingApproval`; the user manually completes and submits the employer form.
- Search updates job details and match analysis on conflict but deliberately does not update job `status` or application rows.

## Install safely on Windows
1. Stop Streamlit and the scheduler (Ctrl+C in their terminal windows).
2. Back up the live database before installing:
   ```cmd
   copy C:\JobPilotAI\jobpilot_ai\data\jobpilot.db C:\JobPilotAI\jobpilot_ai\data\jobpilot_before_upgrade.db
   ```
3. Extract this ZIP into a NEW folder, for example `C:\JobPilotAI\jobpilot_ai_upgrade`. Do not extract over the existing project.
4. Copy your existing `master_resume.md` into the new folder. Copy your existing `.env` into the new folder only if you want to retain Adzuna/email settings; do not share it.
5. Copy your existing `data\jobpilot.db` into the new folder's `data` folder. This lets you test the upgrade against a copy first.
6. Install dependencies using your existing virtual environment:
   ```cmd
   C:\JobPilotAI\.venv\Scripts\python.exe -m pip install -r C:\JobPilotAI\jobpilot_ai_upgrade\requirements.txt
   ```
7. Default database path is `data\jobpilot.db` inside the upgrade folder. If you choose a different path, set `JOBPILOT_DB_PATH` in the new folder's `.env`.
8. Run a syntax check:
   ```cmd
   cd /d C:\JobPilotAI\jobpilot_ai_upgrade
   C:\JobPilotAI\.venv\Scripts\python.exe -m compileall -q .
   ```
9. Run the included preservation check:
   ```cmd
   C:\JobPilotAI\.venv\Scripts\python.exe verify_database.py
   ```
10. Start the dashboard:
   ```cmd
   C:\JobPilotAI\.venv\Scripts\python.exe -m streamlit run app.py
   ```

## Resume Intelligence
- Upload a PDF, DOCX, MD or TXT resume in the dashboard sidebar and click **Analyze uploaded resume**.
- The parser stores a versioned profile and skill evidence in `ri_*` tables in the same database.
- Tailored resumes are generated directly as selectable-text PDFs from `master_resume.md`; uploaded-resume analysis remains a separate feature.
- In the selected job panel, review role alignment separately, choose **Generate Tailored Resume (PDF)**, and download the complete job-tailored resume. The full job description is used for project and skills prioritization.
- The PDF includes supported contact details, a targeted professional summary, technical skills, projects, education, and any supported experience, certifications, or training. It does not include match scores or alignment commentary.
- Skill corrections remain in Resume Intelligence tables. Review detected skills; extraction is not a guarantee of truth.

## Job matching, sources, and work mode
- Match score is a transparent heuristic, not a hiring probability or eligibility guarantee.
- Work arrangement is classified only when text contains clear evidence. Otherwise it remains `Not specified`; it is not guessed as on-site.
- Bengaluru is the highest-priority location. Other Indian cities can be excluded in the dashboard. Remote India requires explicit India eligibility; unknown locations are retained only for manual review and are not counted as India or Remote India.
- Fresher matching reports required and preferred experience separately, gives Bengaluru the strongest location preference, and uses the score tiers Excellent (80+), Strong (70–79), Good (60–69), Partial (40–59), and Low (below 40).
- Source adapters are available for the public Arbeitnow feed, Adzuna, Greenhouse, Lever, Ashby, and USAJOBS. Adzuna requires `ADZUNA_APP_ID` and `ADZUNA_APP_KEY`; Greenhouse, Lever, and Ashby require published board identifiers; USAJOBS requires `USAJOBS_API_KEY` and `USAJOBS_EMAIL`. Missing settings are reported as not configured, not as successful empty searches.
- Adzuna, Lever, Arbeitnow, and USAJOBS use pagination where supported. Greenhouse and Ashby return their published board listings without this adapter adding artificial pagination. Requests use bounded timeouts, retries, and per-source rate limits.
- Search diagnostics distinguish configuration, connection, HTTP, empty-result, filtering, and database outcomes. They include counts for returned, filtered, new, updated, and duplicate jobs.
- Sites without a confirmed permitted direct integration in this project are offered as manual official-site links in the dashboard and `diagnose_sources.py`. No CAPTCHA/authentication bypass or third-party scraping is used. Upwork and Toptal are shown separately as freelance sources, not employment listings.
- Jobs are sorted by original publication-date freshness windows. Source update timestamps are stored separately and are not treated as original publication dates.
- The dashboard separates Bengaluru fresher jobs, newly discovered India jobs, 24-hour/7-day jobs, other Indian cities, Remote India, resume match tiers, internships, manual-review items, and previously discovered jobs.
- Applications are never submitted automatically. `HUMAN_APPROVAL_REQUIRED = True` and `AUTONOMOUS_SUBMIT = False`; the dashboard only prepares the application and opens the original listing for you to complete.
- `python diagnose_sources.py` runs a live diagnostic and may add/update jobs from reachable sources. It never prints API secrets.

## Run commands
```cmd
python run_search.py
python diagnose_sources.py
python apply_agent.py
python -m streamlit run app.py
python scheduler.py
```

The scheduler checks for work at a configurable interval (`SEARCH_POLL_SECONDS`, at least 60 seconds) and enforces a separate refresh interval for each source. Polling every minute does not mean every site publishes a job every minute. A process lock prevents duplicate scheduler instances and search locks prevent overlapping searches. The dashboard shows the next poll and provides a manual refresh button. Keep the scheduler running or configure Windows Task Scheduler yourself.

The application workflow generates the same tailored PDF and opens the employer's original posting for review. Applications are never submitted automatically.
