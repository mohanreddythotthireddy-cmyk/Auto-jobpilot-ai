from datetime import datetime
from run_search import run_search
from apply_agent import run_apply_agent
from reporting import create_report
from db import init_db


def run_daily_agent():
    """Discover jobs and prepare tailored applications for human approval only."""
    init_db()
    print("JobPilot AI daily run:", datetime.now())
    search_result = run_search()
    application_result = run_apply_agent()
    report = create_report(search_result, application_result)
    print("Report saved:", report.resolve())
    print("No employer application was submitted automatically.")
    return search_result, application_result


if __name__ == "__main__":
    run_daily_agent()
