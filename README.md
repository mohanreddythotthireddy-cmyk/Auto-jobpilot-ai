# JobPilot AI

JobPilot AI is an India-first fresher job discovery dashboard. Bengaluru is
prioritized, while other Indian cities can be toggled in the dashboard.
Resume matching uses verified information from `master_resume.md`; unknown
locations are marked for manual review and are not treated as India-eligible.

## Run

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Run a scheduled source refresh with `python scheduler.py`, or run a one-time
refresh with `python run_search.py`. Optional source settings are documented in
`.env.example`; unconfigured sources are reported as such.

## Application safety

`HUMAN_APPROVAL_REQUIRED = True` and `AUTONOMOUS_SUBMIT = False`. JobPilot AI
can prepare a tailored PDF resume and open the original job listing, but never
submits an application automatically. Do not store passwords or OTPs.

See [README_UPGRADE.md](README_UPGRADE.md) for database preservation, supported
sources, matching behavior, and Windows setup details.
