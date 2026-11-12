from __future__ import annotations

import msvcrt
from datetime import datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler

from config import DB_PATH, RUN_HOUR, RUN_MINUTE, SEARCH_POLL_SECONDS
from db import init_db, set_next_scheduled_search, set_search_schedule_state
from run_search import run_search


def _acquire_singleton_lock():
    lock_path = DB_PATH.parent / "jobpilot_scheduler.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None
    return handle


def _scheduled_search():
    now = datetime.now()
    next_run = now + timedelta(seconds=SEARCH_POLL_SECONDS)
    set_next_scheduled_search(next_run.isoformat(timespec="seconds"))
    print(f"Scheduled source poll started at {now:%Y-%m-%d %H:%M:%S}.")
    run_search(force=False)


def create_scheduler(daily_callback, poll_seconds=SEARCH_POLL_SECONDS):
    scheduler = BlockingScheduler()
    scheduler.add_job(
        _scheduled_search, "interval", seconds=poll_seconds,
        id="jobpilot_source_poll", replace_existing=True, max_instances=1,
        coalesce=True, misfire_grace_time=poll_seconds,
    )
    scheduler.add_job(
        daily_callback, "cron", hour=RUN_HOUR, minute=RUN_MINUTE,
        id="daily_jobpilot_agent", replace_existing=True, max_instances=1,
        coalesce=True,
    )
    return scheduler


def main():
    from daily_agent import run_daily_agent

    init_db()
    lock = _acquire_singleton_lock()
    if lock is None:
        print("Another JobPilot scheduler process already holds the scheduler lock.")
        return

    now = datetime.now()
    first_poll = now + timedelta(seconds=SEARCH_POLL_SECONDS)
    set_search_schedule_state(now.isoformat(timespec="seconds"),
                              first_poll.isoformat(timespec="seconds"),
                              SEARCH_POLL_SECONDS)
    scheduler = create_scheduler(run_daily_agent)
    print(f"Job source polling checks every {SEARCH_POLL_SECONDS} seconds.")
    print(f"Individual sources respect their configured refresh intervals.")
    print(f"Daily human-approved workflow scheduled for {RUN_HOUR:02d}:{RUN_MINUTE:02d} local time.")
    print("A one-minute poll is not a guarantee that websites publish new jobs every minute.")
    print("Keep this process running. Configure Windows Task Scheduler for startup.")
    try:
        scheduler.start()
    finally:
        lock.close()


if __name__ == "__main__":
    main()
