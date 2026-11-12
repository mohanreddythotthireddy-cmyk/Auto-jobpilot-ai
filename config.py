from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
DB_PATH = Path(os.getenv("JOBPILOT_DB_PATH") or os.getenv("JOBPILOT_DB") or str(ROOT / "data" / "jobpilot.db")).expanduser()
RESUME_DIR = ROOT / "resumes"
UPLOAD_DIR = ROOT / "data" / "resume_uploads"
MASTER_RESUME = Path(os.getenv("MASTER_RESUME_PATH") or os.getenv("JOBPILOT_MASTER_RESUME") or str(ROOT / "master_resume.md")).expanduser()
ACTIVE_RESUME_PATH = Path(os.getenv("ACTIVE_RESUME_PATH") or str(MASTER_RESUME)).expanduser()
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "").strip()
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "").strip()
GREENHOUSE_BOARDS = [x.strip() for x in os.getenv("GREENHOUSE_BOARDS", "").split(",") if x.strip()]
LEVER_BOARDS = [x.strip() for x in os.getenv("LEVER_BOARDS", "").split(",") if x.strip()]
ASHBY_BOARDS = [x.strip() for x in os.getenv("ASHBY_BOARDS", "").split(",") if x.strip()]
USAJOBS_API_KEY = os.getenv("USAJOBS_API_KEY", "").strip()
USAJOBS_EMAIL = os.getenv("USAJOBS_EMAIL", "").strip()
JOB_SEARCH_LOCATIONS = [
    x.strip() for x in os.getenv("JOB_SEARCH_LOCATIONS", "Bengaluru,Karnataka,India").split(",")
    if x.strip()
]
INCLUDE_OTHER_INDIAN_CITIES = os.getenv("INCLUDE_OTHER_INDIAN_CITIES", "true").lower() in {"1", "true", "yes"}
INCLUDE_INDIA_REMOTE = os.getenv("INCLUDE_INDIA_REMOTE", "true").lower() in {"1", "true", "yes"}
INCLUDE_UNKNOWN_LOCATION_REMOTE = os.getenv("INCLUDE_UNKNOWN_LOCATION_REMOTE", "true").lower() in {"1", "true", "yes"}
SEARCH_POLL_SECONDS = max(60, int(os.getenv("SEARCH_POLL_SECONDS", "60")))
SOURCE_REFRESH_MINUTES = {
    "Adzuna": max(1, int(os.getenv("ADZUNA_REFRESH_MINUTES", "15"))),
    "Arbeitnow": max(1, int(os.getenv("ARBEITNOW_REFRESH_MINUTES", "30"))),
    "Greenhouse": max(1, int(os.getenv("GREENHOUSE_REFRESH_MINUTES", "60"))),
    "Lever": max(1, int(os.getenv("LEVER_REFRESH_MINUTES", "60"))),
    "Ashby": max(1, int(os.getenv("ASHBY_REFRESH_MINUTES", "60"))),
    "USAJOBS": max(1, int(os.getenv("USAJOBS_REFRESH_MINUTES", "60"))),
}
RUN_HOUR = int(os.getenv("RUN_HOUR", "8"))
RUN_MINUTE = int(os.getenv("RUN_MINUTE", "30"))
DAILY_APPLICATION_LIMIT = int(os.getenv("DAILY_APPLICATION_LIMIT", "50"))
MIN_MATCH_SCORE = int(os.getenv("MIN_MATCH_SCORE", "50"))
# JobPilot is intentionally human-approved. No browser form submission is enabled.
HUMAN_APPROVAL_REQUIRED = True
AUTONOMOUS_SUBMIT = False
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "").strip()
REPORT_TO = os.getenv("REPORT_TO", "").strip()
TARGET_ROLES = [
    "AWS Cloud Support Associate", "AWS Cloud Engineer Fresher",
    "Cloud Support Engineer", "Cloud Operations Associate", "Cloud Engineer Trainee",
    "Junior Cloud Engineer", "Infrastructure Support Engineer",
    "Technical Support Associate", "DevOps Engineer Fresher", "DevOps Trainee",
    "Junior DevOps Engineer", "Platform Engineer Trainee", "Junior Platform Engineer",
    "Linux Support Engineer", "Infrastructure Engineer Trainee",
    "Site Reliability Engineer Trainee", "Python Developer Fresher",
    "Junior Python Developer", "Associate Software Engineer",
    "Software Engineer Trainee", "Graduate Engineer Trainee",
    "Junior Software Developer", "Application Developer", "Backend Developer Fresher",
    "SQL Developer Fresher", "Junior SQL Developer", "Data Engineer Trainee",
    "Junior Data Engineer", "Database Support Engineer", "MySQL Developer",
    "Application Support Engineer", "Production Support Engineer",
    "IT Support Engineer", "System Administrator Trainee",
    "IT Operations Associate", "Technical Support Engineer", "Service Desk Engineer",
]

BENGALURU_LOCATIONS = (
    "Bangalore", "Bengaluru", "Electronic City", "Whitefield", "Marathahalli",
    "Bellandur", "Sarjapur Road", "Outer Ring Road", "Koramangala",
    "Manyata Tech Park", "Hebbal", "Indiranagar", "HSR Layout", "Yelahanka",
)
MAJOR_INDIAN_CITIES = (
    "Hyderabad", "Chennai", "Pune", "Mumbai", "Gurgaon", "Gurugram",
    "Noida", "Delhi", "Kolkata", "Kochi", "Coimbatore", "Ahmedabad",
    "Mysuru", "Mangalore", "Visakhapatnam",
)
# Backwards-compatible name for callers that display the configured query list.
SEARCH_TERMS = TARGET_ROLES
