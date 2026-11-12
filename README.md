# JobPilot AI 🚀

### AI-Powered Job Discovery, Resume Intelligence & Career Assistant

JobPilot AI is a Python-based job discovery and resume preparation platform designed to help freshers find relevant IT job opportunities, analyze job descriptions, calculate skill matches, and prepare tailored resumes.

The platform prioritizes fresher opportunities in Bengaluru and supports job discovery across multiple sources.

## ✨ Key Features

### 1. AI-Powered Job Discovery
- Discover IT job opportunities from supported job sources.
- Search for fresher and entry-level positions.
- Prioritize Bengaluru job opportunities.
- Identify remote and India-based opportunities.
- Track newly discovered and updated job listings.

### 2. Intelligent Resume Matching
- Analyze job descriptions against candidate skills.
- Calculate job match scores.
- Identify matching and missing skills.
- Categorize job opportunities based on relevance.
- Support resume-based job recommendations.

### 3. Resume Intelligence
- Parse and analyze resume content.
- Extract technical skills and keywords.
- Identify skill gaps.
- Generate tailored resumes for relevant job descriptions.
- Prepare downloadable PDF resumes.

### 4. Duplicate Job Detection
- Identify duplicate job listings.
- Track previously discovered opportunities.
- Avoid repeatedly reviewing the same jobs.

### 5. Work Mode Classification
- Classify opportunities as Remote, Hybrid, or On-site.
- Identify location information.
- Separate verified remote opportunities from unknown work modes.

### 6. Dashboard and Reporting
- Interactive Streamlit dashboard.
- Job discovery statistics.
- Job match scores and categories.
- Source diagnostics.
- Job listing links.
- Application tracking and reporting.

### 7. Scheduled Job Discovery
- Run scheduled job source refreshes.
- Perform manual job searches.
- Maintain local job discovery records.

## 🛠️ Technologies Used

| Category | Technologies |
|---|---|
| Programming Language | Python |
| Frontend / Dashboard | Streamlit |
| Database | SQLite |
| Job Discovery | Adzuna API and other supported sources |
| Resume Processing | Python-based parsing and analysis |
| Data Processing | Python |
| Testing | Pytest |
| Version Control | Git and GitHub |

## 📁 Project Structure

```text
Auto-jobpilot-ai/
│
├── app.py
├── config.py
├── db.py
├── profile.py
│
├── run_search.py
├── daily_agent.py
├── scheduler.py
├── apply_agent.py
│
├── job_sources.py
├── matcher.py
├── duplicate_detection.py
├── classify_work_modes.py
├── work_mode.py
│
├── resume_builder.py
├── resume_parser.py
├── resume_intelligence.py
├── resume_intelligence_page.py
├── resume_job_terms.py
├── resume_profile_service.py
│
├── skill_audit.py
├── skill_extractor.py
├── refresh_matches.py
├── reporting.py
├── diagnose_sources.py
├── verify_database.py
│
├── tests/
│
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
└── README_UPGRADE.md
```

## ⚙️ Installation and Setup

### Step 1: Clone the Repository

```bash
git clone https://github.com/mohanreddythotthireddy-cmyk/Auto-jobpilot-ai.git
```

### Step 2: Navigate to Project Directory

```bash
cd Auto-jobpilot-ai
```

### Step 3: Create a Virtual Environment

Windows:

```powershell
python -m venv venv
```

### Step 4: Activate Virtual Environment

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 5: Install Dependencies

```bash
python -m pip install -r requirements.txt
```

### Step 6: Configure Environment Variables

Create a `.env` file using `.env.example` as a reference.

Add your own API credentials and configuration values locally.

**Never upload your `.env` file or API keys to GitHub.**

### Step 7: Run the Application

```bash
python -m streamlit run app.py
```

Open the local Streamlit URL displayed in your terminal.

## 🔍 Running Job Discovery

Run a one-time job search:

```bash
python run_search.py
```

Run scheduled source refresh:

```bash
python scheduler.py
```

## 🧪 Run Tests

Execute the project test suite:

```bash
python -m pytest
```

## 🔐 Application Safety

JobPilot AI follows a human-approved application workflow.

- `HUMAN_APPROVAL_REQUIRED = True`
- `AUTONOMOUS_SUBMIT = False`

The platform can prepare tailored PDF resumes and open original job listings.

It does not automatically submit job applications.

Never store passwords, OTPs, or sensitive login credentials in the project.

## 🎯 Project Objective

The objective of JobPilot AI is to simplify job searching for fresh graduates by combining job discovery, resume intelligence, skill-gap analysis, job matching, and application preparation in one platform.

## 🚀 Future Enhancements

- More job-source integrations.
- Improved job recommendation algorithms.
- Advanced resume optimization.
- Enhanced application tracking.
- Better job market analytics.
- Additional career preparation tools.

## 👨‍💻 Developer

**Thotthireddy Mohanreddy**

GitHub: https://github.com/mohanreddythotthireddy-cmyk

Project: [Auto-jobpilot-ai](https://github.com/mohanreddythotthireddy-cmyk/Auto-jobpilot-ai)

---

⭐ If you find this project useful, consider giving the repository a star!

**JobPilot AI – Discover Opportunities. Match Your Skills. Build Your Career.**
