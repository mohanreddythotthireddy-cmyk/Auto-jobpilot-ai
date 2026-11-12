from __future__ import annotations

from datetime import datetime, timezone
import html
import re
from difflib import SequenceMatcher


_COMPANY_SUFFIXES = {
    "company", "co", "corporation", "corp", "inc", "incorporated", "limited", "ltd",
    "llc", "llp", "plc", "private", "pvt", "gmbh", "ag", "sarl", "sa", "bv",
    "pte", "pty", "technologies", "technology",
}
_UNKNOWN_COMPANIES = {"", "unknown", "not specified", "n a", "na"}
_CITY_ALIASES = {
    "bengaluru": "bengaluru", "bangalore": "bengaluru",
    "mumbai": "mumbai", "bombay": "mumbai",
    "chennai": "chennai", "madras": "chennai",
    "kolkata": "kolkata", "calcutta": "kolkata",
    "gurgaon": "gurugram", "gurugram": "gurugram",
    "mysore": "mysuru", "mysuru": "mysuru",
    "trivandrum": "thiruvananthapuram", "thiruvananthapuram": "thiruvananthapuram",
    "vizag": "visakhapatnam", "visakhapatnam": "visakhapatnam",
}
_LOCATION_NOISE = {
    "karnataka", "state", "district", "remote", "hybrid",
    "on", "site", "onsite", "work", "from", "home",
}
_COUNTRIES = {
    "in": "india", "india": "india", "us": "united states", "usa": "united states",
    "united states": "united states", "uk": "united kingdom", "united kingdom": "united kingdom",
    "canada": "canada", "australia": "australia", "germany": "germany",
    "france": "france", "singapore": "singapore",
}


def _words(value: str) -> list[str]:
    normalized = re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE)
    return normalized.split()


def normalize_company(value: str) -> str:
    tokens = _words(value)
    while tokens and tokens[-1] in _COMPANY_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def normalize_title(value: str) -> str:
    return " ".join(_words(value))


def normalize_location(value: str) -> str:
    tokens = _words(value)
    if not tokens:
        return ""
    city = next((_CITY_ALIASES[token] for token in tokens if token in _CITY_ALIASES), "")
    country = next((_COUNTRIES[token] for token in tokens if token in _COUNTRIES), "")
    if city:
        return f"{city} {country}".strip()
    remaining = [_COUNTRIES.get(token, token) for token in tokens
                 if token not in _LOCATION_NOISE and token not in _COUNTRIES]
    return " ".join(dict.fromkeys([*remaining, country] if country else remaining))


def normalize_description(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"https?://\S+", " ", text, flags=re.I)
    return " ".join(_words(text))


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    left_tokens, right_tokens = set(left.split()), set(right.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    if max(len(left), len(right)) > 2048:
        return overlap
    seq = SequenceMatcher(None, left, right, autojunk=False).ratio()
    return max(seq, overlap)


def _published_date(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.isdigit():
            timestamp = int(text)
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, timezone.utc)
        published = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        return published.astimezone(timezone.utc)
    except (OverflowError, OSError, TypeError, ValueError):
        return None


def normalized_job(job: dict) -> dict[str, str]:
    return {
        "company": normalize_company(job.get("company", "")),
        "title": normalize_title(job.get("title", "")),
        "location": normalize_location(job.get("location", "")),
        "description": normalize_description(job.get("description", "")),
        "url": normalize_url(job.get("url", "")),
    }


def normalize_url(value: str) -> str:
    raw = str(value or "").strip().casefold()
    raw = re.sub(r"[?&](?:utm_[^=]+|source|ref|tracking)=[^&]*", "", raw)
    raw = re.sub(r"[?&]+$", "", raw)
    raw = re.sub(r"[?#].*$", "", raw)
    return raw.rstrip("/")


def duplicate_match(existing: dict, incoming: dict) -> tuple[bool, str]:
    """Conservative vacancy match; company alone can never cause a merge."""
    left = normalized_job(existing)
    right = normalized_job(incoming)

    if left["url"] and left["url"] == right["url"]:
        return True, "same normalized URL"

    if (not left["company"] or left["company"] in _UNKNOWN_COMPANIES
            or left["company"] != right["company"]):
        return False, ""
    if not left["title"] or not right["title"]:
        return False, ""
    if left["location"] != right["location"]:
        return False, ""

    title_score = _similarity(left["title"], right["title"])
    left_description, right_description = left["description"], right["description"]
    if left_description and right_description:
        description_score = _similarity(left_description, right_description)
        if title_score >= 0.90 and description_score >= 0.70:
            return True, f"title={title_score:.2f}, description={description_score:.2f}"
        if title_score >= 0.76 and description_score >= 0.86:
            return True, f"title={title_score:.2f}, description={description_score:.2f}"
        return False, ""

    if title_score >= 0.94:
        left_date = _published_date(existing.get("posted"))
        right_date = _published_date(incoming.get("posted"))
        if left_date and right_date and abs((left_date - right_date).total_seconds()) <= 3 * 86400:
            return True, f"title={title_score:.2f}; descriptions unavailable; dates within 3 days"
    return False, ""
