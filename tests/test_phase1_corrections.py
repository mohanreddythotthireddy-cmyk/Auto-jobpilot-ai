"""Tests for the Phase 1 improvement round (AWS networking terms, duplicates, audit)."""
from resume_parser import parse_resume_text
from skill_audit import audit, find_uncaptured
from skill_extractor import CATALOG, CATEGORY, AWS, dedupe_key, extract_skills, extract_skills_from_text

RESUME = """# Jane Doe
jane@example.com
## Technical Skills
**Languages:** Python, C, C++
**AWS Services:** EC2, S3, VPC, Internet Gateway, NAT Gateway, Security Groups, Subnets, ALB
**Networking:** Subnetting, Security Group
## Projects
### Three-Tier VPC
- Placed web servers behind an Application Load Balancer in private subnets.
- Technologies: AWS (VPC, Subnets, NAT Gateway), Terraform
"""


def sk():
    return {s.name: s for s in extract_skills_from_text(RESUME)}


def test_aws_networking_terms_classified_as_aws_services():
    s = sk()
    for name in ["AWS Internet Gateway", "AWS NAT Gateway", "AWS Security Groups", "AWS Subnets", "AWS ALB"]:
        assert name in s, name
        assert s[name].category == AWS, (name, s[name].category)
        assert s[name].in_catalog


def test_original_wording_preserved_not_prefixed():
    s = sk()
    assert "EC2" in s["AWS EC2"].original_forms and "AWS EC2" not in s["AWS EC2"].original_forms
    assert "Internet Gateway" in s["AWS Internet Gateway"].original_forms
    assert {"Security Groups", "Security Group"} <= set(s["AWS Security Groups"].original_forms)
    assert "Application Load Balancer" in s["AWS ALB"].original_forms
    assert "ALB" in s["AWS ALB"].original_forms


def test_alb_spelled_out_in_prose_links_to_project():
    s = sk()
    assert "Three-Tier VPC" in s["AWS ALB"].projects
    assert "Three-Tier VPC" in s["AWS Subnets"].projects
    assert all(e.line and e.section for e in s["AWS ALB"].evidence)


def test_subnetting_stays_separate_from_subnets():
    s = sk()
    assert "Subnetting" in s and "AWS Subnets" in s
    assert s["Subnetting"].category == "Networking"


def test_category_label_not_treated_as_skill():
    s = sk()
    assert "Computer Networks" not in s  # came only from the "Networking:" label


def test_no_duplicates_and_c_cpp_not_merged():
    names = list(sk())
    assert len({dedupe_key(n) for n in names}) == len(names)
    assert dedupe_key("C") != dedupe_key("C++") != dedupe_key("C#")
    assert "C" in names and "C++" in names


def test_catalogue_has_no_duplicate_keys():
    keys = [dedupe_key(c[0]) for c in CATALOG]
    assert len(keys) == len(set(keys))


def test_unknown_plural_duplicates_merge():
    t = {s.name: s for s in extract_skills_from_text("## Skills\nWidget Forge, Widget Forges\n")}
    assert len(t) == 1
    assert set(next(iter(t.values())).original_forms) == {"Widget Forge", "Widget Forges"}


def test_absent_aws_terms_not_added():
    s = {x.name for x in extract_skills_from_text("## Skills\nPython, AWS (EC2)\n")}
    assert s == {"Python", "AWS", "AWS EC2"}


def test_audit_reports_clean_resume():
    r = parse_resume_text(RESUME)
    skills = extract_skills(r)
    rep = audit(r, skills)
    assert rep["duplicates"] == [] and rep["unclassified"] == []
    assert rep["uncaptured_terms"] == []


def test_audit_flags_dropped_items_and_unknowns():
    r = parse_resume_text("## Skills\nTools: Python, Gizmo Suite, Basic\n")
    skills = extract_skills(r)
    rep = audit(r, skills)
    assert "Gizmo Suite" in rep["not_in_catalogue"]
    assert any(u["term"] == "Basic" for u in rep["uncaptured_terms"])
    assert find_uncaptured(r, skills) == rep["uncaptured_terms"]
