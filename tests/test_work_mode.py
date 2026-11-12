from work_mode import (
    classify_work_mode,
    is_bengaluru,
    is_india_listing,
    is_india_remote_or_hybrid,
    location_category,
    location_filter_reason,
    location_priority,
)

def test_unknown_is_not_guessed_onsite():
    assert classify_work_mode({"title":"Python Developer","location":"Bengaluru","description":"Build APIs"}) == "Not specified"

def test_hybrid():
    assert classify_work_mode({"description":"Hybrid work model"}) == "Hybrid"

def test_remote():
    assert classify_work_mode({"description":"100% remote role"}) == "Remote"


def test_remote_job_with_unrelated_india_mention_is_not_india_eligible():
    job = {
        "location": "Berlin, Germany",
        "description": (
            "Fully remote role. The company serves customers in India."
        ),
    }

    assert not is_india_remote_or_hybrid(job)
    assert location_filter_reason(job)[0] is False


def test_india_first_location_priority_and_unknown_review():
    bengaluru = {"location": "Manyata Tech Park, Bengaluru"}
    major_city = {"location": "Hyderabad, Telangana, India"}
    other_india = {"location": "Jaipur, India"}
    remote_india = {
        "location": "Remote",
        "description": "Fully remote role open to candidates across India.",
    }
    unknown = {"location": "Worldwide"}

    assert is_bengaluru(bengaluru["location"])
    assert is_india_listing(bengaluru)
    assert location_category(major_city) == "Major Indian city"
    assert location_category(other_india) == "Other India"
    assert location_category(remote_india) == "Remote India"
    assert location_category(unknown) == "Unknown / manual review"
    assert location_priority(bengaluru) < location_priority(major_city)
    assert location_priority(major_city) < location_priority(other_india)
    assert location_priority(other_india) < location_priority(remote_india)
    assert not is_india_listing(unknown)


def test_other_city_filter_can_be_disabled_without_losing_manual_review():
    assert location_filter_reason(
        {"location": "Pune, India"}, include_other_cities=False
    ) == (False, "other Indian cities disabled")
    assert location_filter_reason(
        {"location": "No location listed"}, include_other_cities=False
    ) == (True, "unknown location; manual review required")


def test_remote_india_is_separate_from_city_priority():
    bengaluru_remote = {
        "location": "Bengaluru",
        "work_mode": "Remote",
        "description": "Remote role open to candidates located in India.",
    }
    hyderabad_hybrid = {
        "location": "Hyderabad, India",
        "work_mode": "Hybrid",
        "description": "Hybrid role open to candidates across India.",
    }

    assert location_category(bengaluru_remote) == "Bengaluru"
    assert is_india_remote_or_hybrid(bengaluru_remote)
    assert location_filter_reason(
        hyderabad_hybrid, include_other_cities=False
    )[0] is True
