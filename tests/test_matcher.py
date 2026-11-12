import pytest

from matcher import _tier, score_job


def _profile(skills):
    return {
        "skills": [{"name": skill, "status": "verified"} for skill in skills],
        "education": ["B.E. Computer Science and Engineering"],
        "experience": [],
        "experience_level": "Fresher",
        "summary": [],
        "projects": [],
        "training": [],
    }


def test_one_keyword_cannot_produce_a_high_match_score():
    job = {
        "title": "Python Developer Fresher",
        "description": "Entry-level role using Python.",
        "location": "Bengaluru",
        "posted": "2026-11-12",
    }

    result = score_job(job, _profile(["Python"]))

    assert result["matched_skills"] == ["Python"]
    assert result["match_score"] < 60
    assert result["match_tier"] == "Partial match"


def test_required_and_preferred_skills_are_reported_separately():
    job = {
        "title": "Platform Engineer Trainee",
        "description": (
            "Required skills: AWS, Terraform, Kubernetes.\n"
            "Preferred skills: Docker.\n"
            "Responsibilities: Provision AWS infrastructure using Terraform and Linux."
        ),
        "location": "Bengaluru",
        "posted": "2026-11-12",
    }

    result = score_job(job, _profile(["AWS", "Terraform", "Docker", "Linux"]))

    assert result["missing_required_skills"] == ["Kubernetes"]
    assert "Kubernetes" in result["missing_requirements"][0]
    assert result["matched_skills"] == ["AWS", "Docker", "Linux", "Terraform"]
    assert result["match_score"] <= 74
    assert result["manual_review_required"] is True


def test_senior_experience_requirements_reduce_and_exclude_match():
    job = {
        "title": "Senior Platform Engineer",
        "description": "Requires 6 years of professional experience with AWS.",
        "location": "Bengaluru",
        "posted": "2026-11-12",
    }

    result = score_job(job, _profile(["AWS", "Linux", "Terraform"]))

    assert result["experience_fit"] == "Senior"
    assert result["exclude_for_experience"] is True
    assert result["match_score"] < 60


def test_zero_year_experience_is_classified_as_fresher_friendly():
    job = {
        "title": "Cloud Support Associate",
        "description": "0 years experience required. AWS and Linux support.",
        "location": "Bengaluru",
        "posted": "2026-11-12",
    }

    result = score_job(job, _profile(["AWS", "Linux"]))

    assert result["experience_fit"] == "Fresher-friendly"
    assert result["match_explanation"].find("Fresher-friendly") >= 0


def test_manager_role_is_not_treated_as_fresher_friendly():
    job = {
        "title": "Technical Support Manager | Working Student",
        "description": "Work with the technical support team.",
        "location": "Bengaluru",
        "posted": "2026-11-12",
    }

    result = score_job(job, _profile(["Python", "Linux"]))

    assert result["experience_fit"] == "Senior"
    assert result["exclude_for_experience"] is True


@pytest.mark.parametrize(
    "score,tier",
    [
        (100, "Excellent match"),
        (80, "Excellent match"),
        (79, "Strong match"),
        (70, "Strong match"),
        (69, "Good match"),
        (60, "Good match"),
        (59, "Partial match"),
        (40, "Partial match"),
        (39, "Low match"),
    ],
)
def test_match_tier_boundaries(score, tier):
    assert _tier(score) == tier


def test_preferred_experience_is_not_treated_as_required():
    job = {
        "title": "Cloud Support Associate",
        "description": (
            "Fresher applicants are welcome. 2 years of experience preferred. "
            "AWS and Linux troubleshooting."
        ),
        "location": "Bengaluru",
    }

    result = score_job(job, _profile(["AWS", "Linux"]))

    assert result["experience_fit"] == "Fresher-friendly"
    assert result["experience_requirement"] == (
        "Preferred: 2+ years; entry-level also stated"
    )
    assert result["exclude_for_experience"] is False
