import html
import re

from config import (
    INCLUDE_INDIA_REMOTE,
    INCLUDE_OTHER_INDIAN_CITIES,
    BENGALURU_LOCATIONS,
    JOB_SEARCH_LOCATIONS,
    MAJOR_INDIAN_CITIES,
)

_INDIAN_CITIES = (
    "agra", "ahmedabad", "amritsar", "bangalore", "bhopal", "bengaluru",
    "bhubaneswar", "chandigarh", "chennai", "coimbatore", "dehradun", "delhi",
    "faridabad", "ghaziabad", "gurgaon", "gurugram", "guwahati", "hyderabad",
    "indore", "jaipur", "jodhpur", "kanpur", "kochi", "kolkata", "lucknow",
    "ludhiana", "madurai", "mangalore", "mangaluru", "mumbai", "mysore", "mysuru",
    "nagpur", "navi mumbai", "noida", "patna", "pune", "raipur", "ranchi",
    "surat", "thane", "thiruvananthapuram", "tiruchirappalli", "trivandrum",
    "vadodara", "varanasi", "vijayawada", "visakhapatnam", "vizag",
)
_BENGALURU_AREAS = (
    *BENGALURU_LOCATIONS,
    "kr puram", "silk board", "yeshwanthpur",
)
_MAJOR_INDIAN_CITIES = MAJOR_INDIAN_CITIES
_FOREIGN_LOCATIONS = (
    "australia", "austria", "bangladesh", "belgium", "brazil", "canada", "china",
    "denmark", "egypt", "finland", "france", "germany", "greece", "hong kong",
    "indonesia", "ireland", "israel", "italy", "japan", "malaysia", "mexico",
    "nepal", "netherlands", "new zealand", "norway", "pakistan", "philippines",
    "poland", "portugal", "qatar", "russia", "saudi arabia", "singapore",
    "south africa", "spain", "sri lanka", "sweden", "switzerland", "taiwan",
    "turkey", "uk", "united arab emirates", "united kingdom", "united states",
    "usa", "vietnam", "berlin", "london", "paris", "amsterdam", "zurich",
    "new york", "san francisco", "toronto", "vancouver", "sydney", "melbourne",
    "tokyo", "dubai", "munich", "madrid", "stockholm",
)
_REMOTE_PATTERNS = (
    r"\bremote[- ](?:first|only)\b",
    r"\bwork(?:ing)?\s+from\s+home\b",
    r"\bwork\s+remotely\b",
    r"\bfully\s+remote\b",
    r"\b100\s*%\s*remote\b",
    r"\bremote\s+(?:work|role|position|job|opportunity)\b",
    r"\bwfh\b",
)


def _positive_signal(text, patterns):
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            before = text[max(0, match.start() - 24):match.start()]
            after = text[match.end():match.end() + 36]
            negated_before = re.search(r"\b(?:not|no|never|isn't|is\s+not|is\s+no)\s+$", before)
            negated_after = re.match(
                r"\s*(?:is\s+)?(?:not\s+available|not\s+offered|not\s+supported|unavailable|isn't\s+available)",
                after,
            )
            if not negated_before and not negated_after:
                return True
    return False


def classify_work_mode(job):
    saved_mode = str(job.get("work_mode") or "").strip().lower()
    if saved_mode in {"remote", "hybrid", "on-site"}:
        return "On-site" if saved_mode == "on-site" else saved_mode.title()
    workplace_type = str(job.get("workplaceType") or job.get("workplace_type") or "").lower()
    if job.get("isRemote") is True or job.get("remote") is True or workplace_type == "remote":
        return "Remote"
    if workplace_type == "hybrid":
        return "Hybrid"

    text = " ".join(str(job.get(k) or "") for k in ("title", "location", "description")).lower()
    location = str(job.get("location") or "").strip().lower()
    hybrid_patterns = (r"\bhybrid\b", r"\bpart(?:ly|ially)\s+remote\b")
    if _positive_signal(text, hybrid_patterns):
        return "Hybrid"
    if location == "remote" or re.match(r"^remote\s*[-,]", location):
        return "Remote"
    if _positive_signal(text, _REMOTE_PATTERNS):
        return "Remote"
    if _positive_signal(text, (r"\bwork\s+from\s+office(?:\s+only)?\b",
                               r"\bon[- ]site\s+only\b", r"\boffice[- ]based\b")):
        return "On-site"
    return "Not specified"


def is_bengaluru(location):
    loc = str(location or "").lower()
    return any(
        re.search(r"\b" + re.escape(area.lower()) + r"\b", loc)
        for area in _BENGALURU_AREAS
    )


def _contains_india_or_city(text):
    value = str(text or "").lower()
    return bool(re.search(r"\bindia\b|\bkarnataka\b", value)) or any(
        re.search(r"\b" + re.escape(city) + r"\b", value)
        for city in _INDIAN_CITIES
    )


def _description_confirms_india_remote(description):
    text = html.unescape(str(description or "")).lower()
    text = re.sub(r"<[^>]*>", " ", text)
    segments = re.split(r"(?<=[.!?])\s+|[\r\n;]", text)
    pattern = re.compile(
        r"\b(?:remote|remotely|hybrid)\b.{0,40}\b(?:in|from|within|across)\s+india\b"
        r"|\bindia\b.{0,40}\b(?:remote|hybrid)\b"
    )
    return any(pattern.search(segment) for segment in segments)


def _is_indian_location(location):
    value = str(location or "").strip()
    return _contains_india_or_city(value) or bool(re.search(r"(?:,|\s)\s*IN$", value, re.I))


def _is_unknown_location(location):
    value = re.sub(r"[\s,;:/-]+", " ", str(location or "").lower()).strip()
    return not value or value in {
        "remote", "worldwide", "anywhere", "not specified", "unspecified",
        "location not specified", "flexible", "global",
    }


def _is_outside_india(location):
    value = str(location or "").lower()
    return any(
        re.search(r"\b" + re.escape(place) + r"\b", value)
        for place in _FOREIGN_LOCATIONS
    )


def location_category(job):
    """Return a ranked India-first location class; unknown is never India."""
    location = str(job.get("location") or "")
    mode = classify_work_mode(job)
    if is_bengaluru(location):
        return "Bengaluru"
    if mode in ("Remote", "Hybrid") and (
        _is_indian_location(location)
        or _description_confirms_india_remote(job.get("description"))
    ):
        if any(
            re.search(r"\b" + re.escape(city.lower()) + r"\b", location.lower())
            for city in _MAJOR_INDIAN_CITIES
        ):
            return "Major Indian city"
        return "Remote India"
    if _is_indian_location(location):
        if any(
            re.search(r"\b" + re.escape(city.lower()) + r"\b", location.lower())
            for city in _MAJOR_INDIAN_CITIES
        ):
            return "Major Indian city"
        return "Other India"
    if _is_unknown_location(location):
        return "Unknown / manual review"
    if _is_outside_india(location):
        return "Outside India"
    return "Unknown / manual review"


def location_priority(job):
    return {
        "Bengaluru": 1,
        "Major Indian city": 2,
        "Other India": 3,
        "Remote India": 4,
        "Unknown / manual review": 5,
        "Outside India": 6,
    }[location_category(job)]


def is_india_listing(job):
    return location_category(job) in {
        "Bengaluru", "Major Indian city", "Other India", "Remote India",
    }


def is_india_remote_or_hybrid(job):
    mode = classify_work_mode(job).lower()
    if mode not in {"remote", "hybrid"}:
        return False
    location = str(job.get("location") or "")
    return (
        (_is_indian_location(location) and not _is_outside_india(location))
        or _description_confirms_india_remote(job.get("description"))
    )


def location_filter_reason(job, include_other_cities=None):
    location = str(job.get("location") or "").strip()
    category = location_category(job)
    include_other = (
        INCLUDE_OTHER_INDIAN_CITIES
        if include_other_cities is None else include_other_cities
    )
    if category == "Bengaluru":
        return True, "Bengaluru"
    if is_india_remote_or_hybrid(job):
        return (
            INCLUDE_INDIA_REMOTE,
            "Remote India" if INCLUDE_INDIA_REMOTE else "Remote India disabled",
        )
    if category == "Major Indian city":
        return (include_other, "Major Indian city" if include_other else "other Indian cities disabled")
    if category == "Other India":
        return (include_other, "Other Indian location" if include_other else "other Indian cities disabled")
    if category == "Remote India":
        return (INCLUDE_INDIA_REMOTE, "Remote India" if INCLUDE_INDIA_REMOTE else "Remote India disabled")
    if category == "Unknown / manual review":
        return True, "unknown location; manual review required"
    return False, "location is explicitly outside India"
