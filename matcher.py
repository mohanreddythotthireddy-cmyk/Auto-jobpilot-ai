from __future__ import annotations

import html
import re
from pathlib import Path

from config import MASTER_RESUME, TARGET_ROLES
from resume_parser import parse_resume
from resume_intelligence import infer_experience_level
from resume_job_terms import generate_search_terms  # re-exported for existing callers
from skill_extractor import extract_skills, extract_skills_from_text
from work_mode import location_category


_REQUIRED = re.compile(
    r"\b(required|required skills|requirements?|qualifications?|must[- ]have|"
    r"essential|mandatory|minimum)\b",
    re.I,
)
_REQUIRED_HEADING = re.compile(
    r"^(?:requirements|qualifications|minimum qualifications|"
    r"required skills|must[- ]have|what you need)\s*:?\s*$",
    re.I,
)
_PREFERRED = re.compile(
    r"\b(preferred|nice to have|desirable|bonus|ideally|plus)\b", re.I
)
_PREFERRED_HEADING = re.compile(
    r"^(?:preferred qualifications|preferred skills|nice to have|"
    r"bonus skills)\s*:?\s*$",
    re.I,
)
_RESET_HEADING = re.compile(
    r"^(?:responsibilities|what you will do|what you’ll do|what you'll do|"
    r"about the role|about us|benefits|overview)\b.*$",
    re.I,
)
_YEARS_RE = re.compile(
    r"(?<!\d)(?:(\d{1,2})\s*[-–]\s*)?(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
    re.I,
)
_TITLE_SENIOR_RE = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|manager|director|head|chief|architect)\b",
    re.I,
)
_ENTRY_RE = re.compile(
    r"\b(fresher|entry[- ]level|graduate|trainee|junior|associate|intern(?:ship)?|"
    r"0\s*[-–]\s*1\s*years?|0\s+years?\s+(?:of\s+)?experience|"
    r"no\s+(?:prior\s+)?experience\s+(?:required|needed)|no prior experience)\b",
    re.I,
)
_INTERNSHIP_RE = re.compile(
    r"\b(?:intern(?:ship)?|co[- ]?op|werkstudent|working student)\b",
    re.I,
)
_HTML_BREAK_RE = re.compile(r"</?(?:p|li|div|br|h[1-6]|tr)\b[^>]*>", re.I)
_WORD_RE = re.compile(r"[a-z0-9+#./-]+", re.I)
_GENERIC_ROLE_WORDS = {
    "engineer", "developer", "junior", "trainee", "fresher", "graduate",
    "associate", "entry", "level", "intern", "internship", "the", "and",
    "of", "a", "an",
}
_ROLE_NOUNS = (
    "engineer", "developer", "administrator", "operations", "associate",
    "support", "reliability",
)
_RESPONSIBILITY_VERBS = {
    "administer", "automate", "build", "configure", "deploy", "develop",
    "implement", "maintain", "manage", "monitor", "operate", "provision",
    "support", "troubleshoot",
}
_RESPONSIBILITY_STOPWORDS = {
    "about", "across", "also", "and", "are", "being", "build", "can", "candidate",
    "company", "for", "from", "have", "including", "into", "job", "more", "our",
    "role", "should", "that", "the", "their", "there", "these", "this", "through",
    "under", "using", "various", "with", "will", "within", "work", "years", "your",
    "experience", "responsibilities", "requirements", "required", "preferred",
}


def master_resume_profile() -> dict:
    """Build the matching profile only from the configured master resume."""
    path = Path(MASTER_RESUME)
    if not path.is_file():
        raise FileNotFoundError(f"Master resume not found: {path}")
    resume = parse_resume(path)
    skills = extract_skills(resume)
    return {
        "resume": {"source_path": str(path), "name": resume.name},
        "skills": [
            {
                "name": skill.name,
                "category": skill.category,
                "original_forms": skill.original_forms,
                "status": "verified",
            }
            for skill in skills
        ],
        "education": resume.education,
        "experience": resume.experience,
        "experience_level": infer_experience_level(resume),
        "summary": resume.summary,
        "projects": [
            {
                "name": project.name,
                "description": project.description,
                "technologies_raw": project.technologies_raw,
            }
            for project in resume.projects
        ],
        "training": resume.training,
    }


def contains_term(text: str, term: str) -> bool:
    term = str(term or "").strip().lower()
    if not term:
        return False
    escaped = re.escape(term).replace(r"\ ", r"\s+")
    return re.search(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])", text.lower()) is not None


def _plain_job_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = _HTML_BREAK_RE.sub("\n", text)
    text = re.sub(r"<[^>]*>", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def is_internship(job: dict) -> bool:
    return bool(
        _INTERNSHIP_RE.search(str(job.get("title") or ""))
        or _INTERNSHIP_RE.search(str(job.get("job_type") or ""))
    )


def _job_segments(text: str) -> list[tuple[str, str]]:
    state = "general"
    segments = []
    for raw_line in _plain_job_text(text).splitlines():
        line = raw_line.strip(" \t-*•")
        if not line:
            continue
        if _PREFERRED_HEADING.match(line) or (_PREFERRED.search(line) and len(line) < 100):
            state = "preferred"
        elif _REQUIRED_HEADING.match(line):
            state = "required"
        elif _RESET_HEADING.match(line):
            state = "general"

        for segment in re.split(r"(?<=[.!?])\s+", line):
            segment = segment.strip()
            if not segment:
                continue
            if _PREFERRED.search(segment):
                category = "preferred"
            elif _REQUIRED.search(segment):
                category = "required"
            else:
                category = state
            segments.append((segment, category))
    return segments


def _extract_skills(text: str) -> set[str]:
    if not text.strip():
        return set()
    bullet_text = "\n".join(
        "- " + line.strip() for line in text.splitlines() if line.strip()
    )
    return {
        skill.name
        for skill in extract_skills_from_text(f"## Technical Skills\n{bullet_text}")
    }


def _skill_sets(text: str) -> tuple[set[str], set[str], set[str]]:
    all_skills = _extract_skills(text)
    required: set[str] = set()
    preferred: set[str] = set()
    for segment, category in _job_segments(text):
        found = _extract_skills(segment)
        if category == "required":
            required.update(found)
        elif category == "preferred":
            preferred.update(found)
    preferred -= required
    general = all_skills - required - preferred
    return required, preferred, general


def _candidate_skills(profile: dict) -> set[str]:
    return {
        str(skill.get("name") or "").strip()
        for skill in profile.get("skills", [])
        if skill.get("name") and skill.get("status") != "removed"
    }


def _role_relevance(title: str) -> int:
    normalized_title = " ".join(_WORD_RE.findall(str(title or "").lower()))
    if not normalized_title:
        return 0
    best = 0
    for role in TARGET_ROLES:
        normalized_role = " ".join(_WORD_RE.findall(role.lower()))
        if normalized_role and normalized_role in normalized_title:
            return 20
        role_words = set(normalized_role.split()) - _GENERIC_ROLE_WORDS
        if not role_words:
            continue
        title_words = set(normalized_title.split()) - _GENERIC_ROLE_WORDS - {
            "senior", "staff", "principal", "lead", "sr",
        }
        overlap = role_words & title_words
        if overlap:
            best = max(best, round(20 * len(overlap) / len(role_words)))
    return best


def is_target_role(job: dict) -> bool:
    title = str(job.get("title") or "").lower()
    score = _role_relevance(title)
    return score >= 12 and any(noun in title for noun in _ROLE_NOUNS)


def _experience_assessment(job: dict) -> tuple[str, int, str, bool, str]:
    title = str(job.get("title") or "")
    description = _plain_job_text(job.get("description") or "")
    text = f"{title}\n{description}"
    preferred_years = []
    required_years = []
    for match in _YEARS_RE.finditer(text):
        lower_bound = int(match.group(1)) if match.group(1) else None
        number = int(match.group(2))
        if lower_bound == 0:
            continue
        context = text[max(0, match.start() - 80):min(len(text), match.end() + 100)]
        if re.search(r"\b(?:preferred|nice to have|desirable|ideally)\b", context, re.I):
            preferred_years.append(number)
        elif re.search(r"\b(?:not required|not needed|no experience required)\b", context, re.I):
            continue
        elif re.search(r"\b(?:experience|professional|relevant|work)\b", context, re.I):
            required_years.append(number)

    max_required = max(required_years, default=0)
    max_preferred = max(preferred_years, default=0)
    senior_title = bool(_TITLE_SENIOR_RE.search(title))
    entry_signal = bool(_ENTRY_RE.search(text))
    if senior_title or max_required >= 5:
        label = "Senior"
        points = 0
        reason = "Senior title or 5+ years of required experience"
        excluded = True
        requirement = (
            f"Required: {max_required}+ years"
            if max_required >= 5 else "Senior-level title"
        )
    elif max_required >= 3:
        label = "Experience required"
        points = 0
        reason = f"{max_required}+ years of experience indicated"
        excluded = False
        requirement = f"Required: {max_required}+ years"
    elif max_required >= 1:
        label = "Experience required"
        points = 5 if max_required == 1 else 2
        reason = f"{max_required} year(s) of experience indicated"
        excluded = False
        requirement = f"Required: {max_required} year(s)"
    elif entry_signal:
        label = "Fresher-friendly"
        points = 15
        reason = "Entry-level, junior, graduate, trainee, or internship signal"
        excluded = False
        requirement = (
            f"Preferred: {max_preferred}+ years; entry-level also stated"
            if max_preferred else "Fresher / entry-level"
        )
    else:
        label = "Unclear"
        points = 8
        reason = "No clear entry-level or required-experience signal"
        excluded = False
        requirement = (
            f"Preferred: {max_preferred}+ years (not stated as required)"
            if max_preferred else "Not stated"
        )
    if max_preferred and not required_years and label == "Unclear":
        reason = f"{max_preferred}+ years listed as preferred; verify whether flexible"
    return label, points, reason, excluded, requirement


def _education_assessment(text: str, profile: dict) -> tuple[int, str, str]:
    education = " ".join(str(item) for item in profile.get("education", []))
    lower = text.lower()
    if not re.search(
        r"\b(?:bachelor|bachelors|b\.?e\.?|b\.?tech|degree|computer science|"
        r"master'?s|ph\.?d\.?)\b",
        lower,
    ):
        return 8, "Not stated", ""
    if re.search(r"\b(?:master'?s|ph\.?d\.?)\b", lower) and not re.search(
        r"\b(?:master'?s|ph\.?d\.?)\b", education, re.I
    ):
        return 0, "Not verified", "Education requirement not verified from the master resume"
    if re.search(r"\b(?:bachelor|bachelors|b\.?e\.?|b\.?tech|computer science)\b", lower):
        if re.search(r"\b(?:b\.?e\.?|b\.?tech|computer science|bachelor)\b", education, re.I):
            return 10, "Matches B.E. in Computer Science", ""
        return 0, "Not verified", "Required computing degree not found in the master resume"
    return (8, "Not stated", "")


def _responsibility_score(text: str, profile: dict) -> int:
    candidate_text = " ".join(
        [
            *map(str, profile.get("summary", [])),
            *map(str, profile.get("education", [])),
            *map(str, profile.get("experience", [])),
            *map(str, profile.get("training", [])),
            *[
                " ".join(
                    [str(project.get("name") or ""), *map(str, project.get("description", [])),
                     *map(str, project.get("technologies_raw", []))]
                )
                for project in profile.get("projects", [])
            ],
        ]
    )
    responsibility_segments = [
        segment for segment, _ in _job_segments(text)
        if any(verb in segment.lower() for verb in _RESPONSIBILITY_VERBS)
    ]
    if not responsibility_segments:
        return 5

    def meaningful_words(value):
        return {
            word for word in _WORD_RE.findall(value.lower())
            if len(word) >= 4
            and word not in _RESPONSIBILITY_STOPWORDS
            and not word.isdigit()
        }

    responsibility_words = set().union(*(meaningful_words(x) for x in responsibility_segments))
    if not responsibility_words:
        return 0
    overlap = len(responsibility_words & meaningful_words(candidate_text))
    return min(10, round(10 * overlap / min(8, len(responsibility_words))))


def _location_assessment(job: dict) -> tuple[int, str, str]:
    category = location_category(job)
    if category == "Bengaluru":
        return 5, "Bengaluru (highest priority)", ""
    if category == "Major Indian city":
        return 4, "Major Indian IT city", ""
    if category == "Other India":
        return 3, "Other Indian location", ""
    if category == "Remote India":
        return 2, "Remote India (explicitly eligible)", ""
    if category == "Unknown / manual review":
        return 1, "Unknown location (manual review)", "Location is unknown; verify India eligibility"
    return 0, "Outside India", "Location is explicitly outside India"


def _tier(score: int) -> str:
    if score >= 80:
        return "Excellent match"
    if score >= 70:
        return "Strong match"
    if score >= 60:
        return "Good match"
    if score >= 40:
        return "Partial match"
    return "Low match"


def score_job(job: dict, profile: dict | None = None) -> dict:
    profile = master_resume_profile() if profile is None else profile
    title = str(job.get("title") or "")
    description = _plain_job_text(job.get("description") or "")
    job_text = f"{title}\n{description}"

    candidate_skills = _candidate_skills(profile)
    required_skills, preferred_skills, general_skills = _skill_sets(description)
    matched_required = required_skills & candidate_skills
    matched_preferred = preferred_skills & candidate_skills
    matched_general = general_skills & candidate_skills
    matched_skills = matched_required | matched_preferred | matched_general
    missing_required = required_skills - candidate_skills

    if required_skills:
        groups = [
            (0.70, matched_required, required_skills),
            (0.20, matched_preferred, preferred_skills),
            (0.10, matched_general, general_skills),
        ]
        active_weight = sum(group[0] for group in groups if group[2])
        skill_coverage = sum(
            weight * len(matched) / len(available)
            for weight, matched, available in groups if available
        ) / active_weight
    elif general_skills:
        skill_coverage = len(matched_general) / len(general_skills)
    else:
        skill_coverage = 0.0
    skill_points = round(40 * skill_coverage)

    role_points = _role_relevance(title)
    (
        experience_fit,
        experience_points,
        experience_reason,
        exclude_for_experience,
        experience_requirement,
    ) = _experience_assessment(job)
    education_points, education_fit, education_issue = _education_assessment(job_text, profile)
    location_points, location_fit, location_issue = _location_assessment(job)
    responsibility_points = _responsibility_score(job_text, profile)

    score = skill_points + role_points + responsibility_points + experience_points + education_points + location_points
    if experience_fit == "Experience required" and experience_points == 0:
        score -= 20
    if experience_fit == "Senior":
        score -= 25
    if role_points == 0:
        score = min(score, 39)
    if len(matched_skills) < 2:
        score = min(score, 59)
    elif len(matched_skills) == 2:
        score = min(score, 74)
    if missing_required:
        score = min(score, 74)
    score = max(0, min(100, score))

    missing_requirements = []
    if missing_required:
        missing_requirements.append(
            "Missing required skills: " + ", ".join(sorted(missing_required))
        )
    if experience_fit == "Senior" or experience_fit == "Experience required":
        missing_requirements.append("Experience fit: " + experience_reason)
    elif experience_fit == "Unclear":
        missing_requirements.append("Experience level is unclear; review the full description")
    if education_issue:
        missing_requirements.append(education_issue)
    if location_issue:
        missing_requirements.append(location_issue)
    if not job.get("posted"):
        missing_requirements.append("Posting date is unknown; verify the original listing")

    manual_review = bool(
        missing_required
        or experience_fit in {"Senior", "Experience required", "Unclear"}
        or education_issue
        or location_issue
        or location_fit.startswith("Unknown")
        or not job.get("posted")
    )
    tier = _tier(score)
    breakdown = (
        f"{tier}: skills {skill_points}/40 "
        f"({len(matched_skills)} matched; {len(required_skills)} identified as required), "
        f"role {role_points}/20, responsibilities {responsibility_points}/10, "
        f"experience {experience_points}/15 ({experience_fit}), "
        f"education {education_points}/10 ({education_fit}), "
        f"location {location_points}/5 ({location_fit})."
    )

    job.update({
        "match_score": score,
        "match_tier": tier,
        "matched_skills": sorted(matched_skills),
        "missing_required_skills": sorted(missing_required),
        "missing_requirements": missing_requirements,
        "match_explanation": breakdown,
        "experience_fit": experience_fit,
        "experience_requirement": experience_requirement,
        "location_category": location_category(job),
        "job_type": "Internship" if is_internship(job) else (
            str(job.get("job_type") or "Not specified")
        ),
        "manual_review_required": manual_review,
        "role_relevance": role_points,
        "exclude_for_experience": exclude_for_experience,
    })
    return job


def enrich(job: dict, profile: dict | None = None) -> dict:
    return score_job(job, profile)
