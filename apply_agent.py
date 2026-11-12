"""Prepare application packets for explicit human review. Never submits forms."""
from config import DAILY_APPLICATION_LIMIT, MIN_MATCH_SCORE
from db import get_jobs, get_application, queue_application, daily_application_count
from resume_builder import build_resume


def run_apply_agent():
    remaining=max(0,DAILY_APPLICATION_LIMIT-daily_application_count())
    prepared=already_queued=failed=0
    for job in get_jobs(min_score=MIN_MATCH_SCORE):
        if prepared>=remaining: break
        if get_application(job["id"]): already_queued+=1; continue
        try:
            path=build_resume(job); queue_application(job,str(path.resolve())); prepared+=1
            print(f"PendingApproval: {job['title']} | {job['company']} | {job.get('url','')}")
        except Exception as exc:
            failed+=1; print(f"Could not prepare {job.get('title')}: {exc}")
    return {"PendingApproval":prepared,"AlreadyQueued":already_queued,"Failed":failed,"ConfirmedSubmissionsToday":daily_application_count(),"AutomaticSubmissions":0}

if __name__=="__main__": print(run_apply_agent())
