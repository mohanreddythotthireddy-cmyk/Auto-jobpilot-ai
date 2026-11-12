from __future__ import annotations

from config import DB_PATH
from db import get_last_successful_search, get_source_refresh_state
from job_sources import MANUAL_SEARCH_LINKS
from run_search import run_search


def main():
    print("JobPilot AI source diagnostic")
    print(f"Database: {DB_PATH}")
    print("No API secret values are displayed.")
    report = run_search(force=True, print_report=False, return_report=True)
    refresh_state = get_source_refresh_state()

    print("\nConfigured source results")
    for source in report["sources"]:
        state = refresh_state.get(source["source"], {})
        if source["source"] == "Arbeitnow":
            configuration = "public feed; credentials not required"
        elif source["source"] in {"Greenhouse", "Lever", "Ashby"}:
            configuration = f"board configured={'yes' if source['configured'] else 'no'}"
        else:
            configuration = f"credentials configured={'yes' if source['configured'] else 'no'}"
        print(
            f"- {source['source']}: {configuration}; "
            f"connection={'yes' if source['connection_ok'] else 'no'}; "
            f"HTTP={source['http_status'] if source['http_status'] is not None else 'n/a'}; "
            f"returned={source['returned']}; after filtering={source['after_filtering']}; "
            f"new={source['new_jobs']}; updated={source['existing_updated']}; "
            f"duplicates={source['duplicates']}; "
            f"last successful refresh={state.get('last_successful_at') or 'never'}"
        )
        if source["error"]:
            print(f"  Error: {source['error']}")
        if source["database_error"]:
            print(f"  Database error: {source['database_error']}")

    connected = [s["source"] for s in report["sources"] if s["connection_ok"]]
    awaiting = [s["source"] for s in report["sources"]
                if not s["configured"] and s["status"] == "not_configured"]
    live_failures = [s for s in report["sources"]
                     if s["configured"] and s["status"] not in {"searched", "empty_results"}]
    empty = [s["source"] for s in report["sources"] if s["status"] == "empty_results"]
    print("\nSource classification")
    print("Implemented adapters: Adzuna, Arbeitnow, Greenhouse, Lever, Ashby, USAJOBS.")
    print(f"Connected in this run: {', '.join(connected) if connected else 'none'}.")
    print(f"Implemented but awaiting configuration: {', '.join(awaiting) if awaiting else 'none'}.")
    print(
        "Configured sources failing live checks: "
        + (", ".join(f"{s['source']} ({s['status']})" for s in live_failures) or "none")
    )
    print(f"Connected with zero results: {', '.join(empty) if empty else 'none'}.")

    last = get_last_successful_search()
    print(f"\nOverall diagnostic status: {report['status']}")
    print(f"Sources actually searched: {report['sources_searched']}")
    if report["sources_searched"] == 0:
        print("No source completed a connection; this is not a successful search.")
    print(f"Last successful search: {last.get('completed_at') if last else 'never'}")

    print("\nManual search links (no direct integration claimed)")
    for name, url in MANUAL_SEARCH_LINKS.items():
        category = "Freelance" if "(freelance)" in name else "Employment"
        print(f"- {category}: {name} — {url}")
    print(
        "Unsupported direct integrations in this build require manual search; "
        "the links above do not imply API or feed access."
    )

    return report


if __name__ == "__main__":
    main()
