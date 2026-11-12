import smtplib
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path
from config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_APP_PASSWORD, REPORT_TO
from db import application_rows, stats

def create_report(search_result, application_result):
    total, matched, submitted, pending = stats()
    lines = [
        f"JobPilot AI Daily Report – {datetime.now()}",
        f"Today's search: {search_result}",
        f"Today's application workflow: {application_result}",
        f"Jobs discovered total: {total}",
        f"Good matches total: {matched}",
        f"Confirmed submissions total: {submitted}",
        f"Pending jobs: {pending}", "",
        "Recent attempts:"
    ]
    for row in application_rows(100):
        lines.append(f"{row['applied_at']} | {row['status']} | {row['title']} | {row['company']} | {row['url']} | {row['detail']}")
    body = "\\n".join(lines)
    folder = Path("reports")
    folder.mkdir(exist_ok=True)
    path = folder / ("daily_report_" + datetime.now().strftime("%Y%m%d") + ".txt")
    path.write_text(body, encoding="utf-8")
    if SMTP_USER and SMTP_APP_PASSWORD and REPORT_TO:
        try:
            msg = EmailMessage()
            msg["Subject"] = "JobPilot AI daily report"
            msg["From"] = SMTP_USER
            msg["To"] = REPORT_TO
            msg.set_content(body)
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_APP_PASSWORD)
                server.send_message(msg)
        except Exception as exc:
            print("Email report failed:", exc)
    print(body)
    return path
