"""Live progress of one unattended cycle, for the dashboard's progress bar (data/run-progress.json).

run_cycle.py turns it on by setting JOBSEARCH_PROGRESS=1 (child scripts inherit it); anything else is a no-op."""
import json
import os
import time

PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "run-progress.json")
# (label, start %, end %): the fetch dominates the wall clock, so it gets the widest band
PHASES = {"prepare": ("Preparing", 0, 4), "fetch": ("Fetching job sources", 4, 62), "discover": ("Discovering new companies", 62, 66),
          "filter": ("Filtering postings", 66, 72), "judge": ("Judging with AI", 72, 90), "log": ("Scoring and logging", 90, 97),
          "report": ("Writing report", 97, 100)}


def _write(rec):
    if os.environ.get("JOBSEARCH_PROGRESS") != "1":
        return
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, PATH)
    except OSError:
        pass  # progress must never break a run


def update(phase, frac=0.0, detail=""):
    label, lo, hi = PHASES[phase]
    try:
        started = json.load(open(PATH)).get("started")
    except (OSError, ValueError):
        started = None
    _write({"running": True, "pid": os.getpid() if phase == "prepare" else _pid(), "phase": label, "detail": detail,
            "pct": round(lo + (hi - lo) * max(0.0, min(1.0, frac)), 1), "started": started or time.time(), "updated": time.time()})


def _pid():
    try:
        return json.load(open(PATH)).get("pid")
    except (OSError, ValueError):
        return os.getppid()


def start():
    try:
        os.remove(PATH)
    except OSError:
        pass
    update("prepare")


def finish(ok):
    try:
        rec = json.load(open(PATH))
    except (OSError, ValueError):
        rec = {}
    _write({**rec, "running": False, "ok": ok, "pct": 100 if ok else rec.get("pct", 0), "phase": "Done" if ok else "Failed", "detail": "", "updated": time.time()})
