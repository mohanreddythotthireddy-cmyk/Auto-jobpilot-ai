from __future__ import annotations

from config import TARGET_ROLES


_SEARCH_VARIANTS = (
    "fresher",
    "freshers",
    "entry level",
    "remote India",
    "graduate",
    "graduate trainee",
    "associate",
    "junior",
    "trainee",
    "0 years",
    "0-1 years",
    "campus hiring",
    "off campus",
    "early career",
)
_INTERNSHIP_ROLES = (
    "AWS Cloud Support Associate",
    "Cloud Support Engineer",
    "Python Developer Fresher",
    "Associate Software Engineer",
    "Software Engineer Trainee",
    "Junior Software Developer",
    "Application Developer",
    "Backend Developer Fresher",
    "Data Engineer Trainee",
    "Junior Data Engineer",
    "SQL Developer Fresher",
)


def generate_search_terms(profile=None):
    """Generate India-focused role, fresher, early-career, and internship queries."""
    if profile is None:
        from matcher import master_resume_profile

        profile = master_resume_profile()

    terms = []
    for role in TARGET_ROLES:
        role_lower = role.lower()
        terms.append(role)
        if not any(marker in role_lower for marker in ("fresher", "junior", "trainee")):
            terms.append(f"{role} fresher")
        terms.extend((f"{role} entry level", f"{role} 0-1 years"))

    for index, variant in enumerate(_SEARCH_VARIANTS):
        terms.append(f"{TARGET_ROLES[index % len(TARGET_ROLES)]} {variant}")

    terms.extend(f"{role} internship Bengaluru" for role in _INTERNSHIP_ROLES)

    skill_names = {
        str(skill.get("name") or "").strip()
        for skill in profile.get("skills", [])
        if skill.get("name") and skill.get("status") != "removed"
    }
    by_lower = {skill.lower(): skill for skill in skill_names}
    aws_skill = by_lower.get("aws") or next(
        (by_lower[key] for key in sorted(by_lower) if key.startswith("aws ")),
        None,
    )
    for skill, role in (
        (aws_skill, "AWS Cloud Support Associate"),
        (by_lower.get("python"), "Python Developer Fresher"),
        (by_lower.get("terraform"), "Platform Engineer Trainee"),
        (by_lower.get("linux"), "Linux Support Engineer"),
        (by_lower.get("mysql"), "Junior SQL Developer"),
    ):
        if skill:
            terms.append(f"{role} {skill} fresher")

    unique = {}
    for term in terms:
        normalized = " ".join(term.lower().split())
        unique.setdefault(normalized, term)
    return list(unique.values())


if __name__ == "__main__":
    terms = generate_search_terms()
    print("Generated India-focused fresher job-search terms:")
    for term in terms:
        print("-", term)
    print(f"Total search terms: {len(terms)}")
