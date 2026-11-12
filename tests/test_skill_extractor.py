from pathlib import Path

from resume_parser import parse_resume
from skill_extractor import ALIAS_MAP, extract_skills, extract_skills_from_text

FIXTURE = Path(__file__).parent / "fixtures" / "sample_resume.md"


def by_name(skills):
    return {s.name: s for s in skills}


def fixture_skills():
    return by_name(extract_skills(parse_resume(FIXTURE)))


def test_detects_listed_skills():
    s = fixture_skills()
    for name in ["Python", "Java", "JavaScript", "C", "C++", "SQL", "MySQL", "SQLite",
                 "Docker", "Git", "GitHub", "Terraform", "PySpark", "Apache Spark",
                 "Linux", "Ubuntu", "Flask", "Pandas", "NumPy"]:
        assert name in s, name


def test_absent_skills_are_not_added():
    s = fixture_skills()
    for name in ["Kubernetes", "Jenkins", "React", "Kotlin", "Firebase", "Node.js",
                 "Azure", "Go", "R", "Excel", "Swift", "Microsoft Excel"]:
        assert name not in s, name


def test_unknown_listed_tool_is_captured():
    s = fixture_skills()
    assert "Quantum Widget Toolkit" in s
    assert s["Quantum Widget Toolkit"].in_catalog is False


def test_synonyms_normalised_with_original_wording():
    s = fixture_skills()
    assert "Amazon Web Services" in s["AWS"].original_forms
    assert "AWS" in s["AWS"].original_forms
    assert "Amazon Simple Storage Service" in s["AWS S3"].original_forms
    assert "Continuous Integration and Continuous Deployment" in s["CI/CD"].original_forms
    assert "Infrastructure as Code" in s["Infrastructure as Code"].original_forms
    assert "IaC" in s["Infrastructure as Code"].original_forms  # "(IaC)" in resume


def test_aws_services_under_aws_parentheses():
    s = fixture_skills()
    for svc in ["AWS EC2", "AWS S3", "AWS IAM", "AWS VPC", "AWS RDS"]:
        assert svc in s
        assert s[svc].category == "AWS Services"


def test_similar_technologies_not_merged():
    s = fixture_skills()
    assert "Java" in s and "JavaScript" in s
    assert "C" in s and "C++" in s
    assert "SQL" in s and "MySQL" in s
    assert "PySpark" in s and "Apache Spark" in s
    t = by_name(extract_skills_from_text("## Skills\nLanguages: JavaScript\n## Projects\n### A\nTechnologies: MySQL, React Native\n"))
    assert "Java" not in t and "SQL" not in t and "React" not in t
    assert "React Native" in t


def test_ambiguous_words_in_prose_ignored():
    s = fixture_skills()
    assert "React" not in s and "R" not in s
    t = by_name(extract_skills_from_text("## Summary\nI like to react fast, excel at teamwork and got a C grade. Go ahead.\n"))
    assert t == {}


def test_every_skill_has_source_reference():
    for sk in extract_skills(parse_resume(FIXTURE)):
        assert sk.evidence, sk.name
        assert all(e.section and e.line for e in sk.evidence)


def test_project_skills_linked_to_project():
    s = fixture_skills()
    assert "Cloud Inventory Tracker" in s["Flask"].projects
    assert "Log Analytics Pipeline" in s["Pandas"].projects
    assert "Cloud Inventory Tracker" in s["AWS S3"].projects
    assert "projects" in s["Docker"].found_in and "skills" in s["Docker"].found_in


def test_skills_from_training_and_certification_sections():
    s = fixture_skills()
    assert "training" in s["TCP/IP"].found_in
    assert "certifications" in s["AWS"].found_in


def test_contact_urls_do_not_create_skills():
    t = by_name(extract_skills_from_text("# Jane\nhttps://github.com/jane\n## Skills\nPython\n"))
    assert "GitHub" not in t and "Python" in t


def test_proficiency_words_not_treated_as_skills():
    t = by_name(extract_skills_from_text("## Skills\nPython (Basic), Java (Advanced), SQL (3.x)\n"))
    assert set(t) == {"Python", "Java", "SQL"}


def test_no_alias_collisions_and_catalogue_is_dictionary_only():
    assert "kubernetes" in ALIAS_MAP
    assert extract_skills_from_text("") == []
    assert extract_skills_from_text("## Skills\n") == []
