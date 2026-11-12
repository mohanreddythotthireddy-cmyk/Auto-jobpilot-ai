import json
from config import ROOT, MASTER_RESUME

def load_profile():
    return json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))

def validate_profile():
    errors = []
    p = load_profile()
    for key in ("full_name", "email", "phone", "highest_education"):
        value = str(p.get(key, "")).strip()
        if not value or "REPLACE" in value:
            errors.append(f"Complete profile.json field: {key}")
    if not p.get("consent", {}).get("profile_verified_by_user", False):
        errors.append("After checking your details, set consent.profile_verified_by_user to true in profile.json.")
    if not p.get("consent", {}).get("allow_automated_submission_to_supported_public_ats", False):
        errors.append("Automated submission consent is disabled in profile.json.")
    if not MASTER_RESUME.exists():
        errors.append("master_resume.md is missing.")
    elif "ADD YOUR" in MASTER_RESUME.read_text(encoding="utf-8") or "REPLACE WITH" in MASTER_RESUME.read_text(encoding="utf-8"):
        errors.append("Remove all placeholders from master_resume.md.")
    return errors
