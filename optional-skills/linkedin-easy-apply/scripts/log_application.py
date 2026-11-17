#!/usr/bin/env python3
"""Append one row to data/tracking.csv, or report today's submitted count.

  log_application.py --company X --role Y --location Z --score 9 --tier A \
      --url https://www.linkedin.com/jobs/view/123/ --resume Resume.pdf \
      --status Submitted|Skipped|External|Duplicate|Stuck --notes "..."
  log_application.py --today      # prints count of Submitted rows dated today
  log_application.py --seen URL   # exit 0 if this job ID is already in the tracker
"""
import argparse, csv, datetime, os, re, sys

CSV = os.path.join(os.path.dirname(__file__), "..", "data", "tracking.csv")
FIELDS = ["Date", "Company", "Role", "Location", "Score", "Tier", "JobURL", "Resume", "Status", "Notes"]

def rows():
    if not os.path.exists(CSV):
        return []
    with open(CSV, newline="") as f:
        return list(csv.DictReader(f))

def job_id(url):
    m = re.search(r"(\d{8,})", url or "")
    return m.group(1) if m else url

ap = argparse.ArgumentParser()
ap.add_argument("--today", action="store_true")
ap.add_argument("--seen")
for f in ["company", "role", "location", "score", "tier", "url", "resume", "status", "notes"]:
    ap.add_argument(f"--{f}", default="")
a = ap.parse_args()

today = datetime.date.today().isoformat()
if a.today:
    print(sum(1 for r in rows() if r["Date"] == today and r["Status"] == "Submitted"))
    sys.exit(0)
if a.seen:
    hit = [r for r in rows() if job_id(r["JobURL"]) == job_id(a.seen)]
    if hit:
        print(f'{hit[-1]["Status"]} on {hit[-1]["Date"]}: {hit[-1]["Company"]} - {hit[-1]["Role"]}')
    sys.exit(0 if hit else 1)

new = not os.path.exists(CSV) or os.path.getsize(CSV) == 0
with open(CSV, "a", newline="") as f:
    w = csv.writer(f)
    if new:
        w.writerow(FIELDS)
    w.writerow([today, a.company, a.role, a.location, a.score, a.tier, a.url, a.resume, a.status, a.notes])
print("logged")
