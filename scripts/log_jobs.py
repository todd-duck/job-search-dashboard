#!/usr/bin/env python3
"""Keep jobs.md and data/seen.json in sync.

Usage:
  log_jobs.py --add data/scored.json   add scored jobs to jobs.md (newest first) + mark everything seen
  log_jobs.py --decisions              print rows whose Status changed since the last run, then remember them
  log_jobs.py --suggest "text"         add a line under '## Pending suggestions'
  log_jobs.py --runlog "notes"         append this run's counts (from data/candidates.json) to data/run-log.md
  log_jobs.py --reconcile              close New/Apply rows whose posting vanished from its feed; backfill sources
  log_jobs.py --set 012 "Pass: reason" change one row's Status (same as the dashboard's Save); tidies afterwards
  log_jobs.py --note 012 "text"        add a dated note to a job (shown in jobs.md details and the dashboard)
  log_jobs.py --followed-up 012        record a follow-up (resets that job's follow-up clock, adds a note)
  log_jobs.py --followups              list Applied/Interviewing jobs due for a follow-up
  log_jobs.py --apply-queue            list Apply jobs and whether their application folder / JD are ready
  log_jobs.py --prepared 012 PATH      record the application folder prepared for a job
  log_jobs.py --tidy                   regroup jobs.md into Active / Archive and move old archived rows to jobs-archive.md

--tidy also works alongside any other command (e.g. --decisions --tidy) and runs after it.
The dashboard (scripts/dashboard.py) runs the same tidy().

scored.json shape:
  {"logged":  [{"key","url","company","title","location","angle","score","tier","salary",
                "posted_at","source","why","gaps"}],
   "dropped": [{"key","url","company","title","reason"}]}
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import step  # noqa: E402
import settings  # noqa: E402
import statuses  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(ROOT, "jobs.md")
SEEN = os.path.join(ROOT, "data", "seen.json")
RUNLOG = os.path.join(ROOT, "data", "run-log.md")
ARCHIVE = os.path.join(ROOT, "jobs-archive.md")
JD_DIR = os.path.join(ROOT, "data", "jd")
CONFIG = os.path.join(ROOT, "config.json")
os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)  # a fresh clone has no data folder yet
TODAY = date.today().isoformat()

HEADER = "| ID | Found | Company | Role | Location (as posted) | Angle | Score | Salary | Status | Link |"
SEP = "| :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- | :-- |"
TEMPLATE = f"""# Job Search Pipeline

Change **Status** from `New` to `Apply`, `Pass: <reason>`, `Applied`, `Interviewing`, `Rejected`, or `Closed`.
Your Pass reasons are what the next run learns from, so a few words help.

## Queue

{HEADER}
{SEP}

## Details

## Pending suggestions

"""


def atomic_write(path, text):
    """Write via temp file + rename so a crash or a concurrent reader never sees a half-written file."""
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


TAM_TAG_RE = re.compile(r"\btechnical (?:account (?:manager|engineer)|success manager)\b", re.I)


def role_cell(title):
    """Technical Account Manager roles get a visible [TAM] tag so they stand apart from SE/SA and professional-services rows."""
    t = cell(title)
    return f"[TAM] {t}" if TAM_TAG_RE.search(t) and not t.startswith("[TAM]") else t


def cell(s):
    return str(s or "").replace("|", "/").replace("\n", " ").strip()


def load_seen():
    return json.load(open(SEEN)) if os.path.exists(SEEN) else {}


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    atomic_write(SEEN, json.dumps(seen, indent=1, sort_keys=True))


def read_jobs():
    if not os.path.exists(JOBS) or HEADER not in open(JOBS).read():
        return TEMPLATE
    return open(JOBS).read()


def table_rows(md):
    """Rows of the Queue table as dicts."""
    cols = [c.strip() for c in HEADER.strip("|").split("|")]
    rows = []
    for line in md.split("\n"):
        if line.startswith("| ") and not line.startswith(("| ID", "| :--")):
            vals = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(vals) == len(cols):
                rows.append(dict(zip(cols, vals)))
    return rows


def next_id(md):
    archived = table_rows(open(ARCHIVE).read()) if os.path.exists(ARCHIVE) else []
    ids = [int(r["ID"]) for r in table_rows(md) + archived if r["ID"].isdigit()]
    return max(ids, default=0) + 1


def add(path):
    with step("log_add"):
        return _add(path)


def _add(path):
    data = json.load(open(path))
    md = read_jobs()
    seen = load_seen()
    n = next_id(md)
    rows, details = [], []
    seen_keys = {v.get("key") for v in seen.values() if v.get("key")}
    cpath = os.path.join(ROOT, "data", "candidates.json")
    descs = {c["url"]: c.get("description", "") for c in json.load(open(cpath))["candidates"]} if os.path.exists(cpath) else {}
    for j in sorted(data.get("logged", []), key=lambda j: -int(j.get("score") or 0)):
        if j["url"] in seen or (j.get("key") and j["key"] in seen_keys):
            print(f"  skip (already logged): {j['company']} — {j['title']}")
            continue
        jid = f"{n:03d}"
        n += 1
        rows.append("| " + " | ".join([
            jid, TODAY, cell(j["company"]), role_cell(j["title"]), cell(j["location"]), cell(j.get("angle")),
            f"{j.get('score')} ({j.get('tier')})" if j.get("score") is not None else "—", cell(j.get("salary")) or "—", j.get("status", "New"), f"[link]({public_url(j)})",
        ]) + " |")
        details.append(
            f"### {jid} · {j['company']} — {j['title']}\n"
            f"- **Why it fits:** {j.get('why', '')}\n"
            f"- **Gaps / red flags:** {j.get('gaps') or 'None noted'}\n"
            f"- **Posted:** {j.get('posted_at') or 'unknown'} · **Source:** {j.get('source', '')} · {j['url']}\n")
        if j.get("description") or descs.get(j["url"]):
            save_jd(jid, j, j.get("description") or descs.get(j["url"], ""))
        seen[j["url"]] = {"key": j.get("key"), "first_seen": TODAY, "status": j.get("status", "New"), "id": jid,
                          "company": j["company"], "title": j["title"], "location": j.get("location", ""),
                          "source_label": j.get("source_label") or j.get("source", "")}
    for j in data.get("dropped", []):
        seen.setdefault(j["url"], {"key": j.get("key"), "first_seen": TODAY, "status": f"Dropped: {j.get('reason', '')}",
                                   "company": j.get("company", ""), "title": j.get("title", ""),
                                   "location": j.get("location", "")})
    if rows:
        md = md.replace(SEP + "\n", SEP + "\n" + "\n".join(rows) + "\n", 1)
        md = md.replace("## Details\n", "## Details\n\n" + "\n".join(details), 1)
    atomic_write(JOBS, md)
    save_seen(seen)
    tidy(quiet=True)
    print(f"Added {len(rows)} rows to jobs.md; marked {len(data.get('dropped', []))} dropped jobs as seen.")


def decisions():
    md = read_jobs()
    seen = load_seen()
    by_id = {v.get("id"): (url, v) for url, v in seen.items() if v.get("id")}
    changed = []
    for r in table_rows(md):
        url, v = by_id.get(r["ID"], (None, None))
        if v is None or r["Status"] == v.get("status"):
            continue
        changed.append(f"{r['ID']} | {r['Company']} | {r['Role']} | {r['Angle']} | {r['Score']} | "
                       f"{v.get('status')} -> {r['Status']}")
        v["status"] = r["Status"]
    save_seen(seen)
    statuses = {}
    for r in table_rows(md):
        k = r["Status"].split(":")[0].strip()
        statuses[k] = statuses.get(k, 0) + 1
    print("Pipeline:", ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())) or "empty")
    print(f"Changed since last run ({len(changed)}):")
    print("\n".join(changed) if changed else "  none")


def set_status(md, jid, status):
    """Rewrite the Status cell of one Queue row."""
    out = []
    for line in md.split("\n"):
        if line.startswith(f"| {jid} |"):
            cells = line.strip().strip("|").split("|")
            cells[8] = f" {status} "
            line = "|" + "|".join(cells) + "|"
        out.append(line)
    return "\n".join(out)


def reconcile():
    """Close New/Apply rows whose posting disappeared from its feed (data from fetch_jobs.py's posting_check)."""
    pc = json.load(open(os.path.join(ROOT, "data", "candidates.json"))).get("posting_check", {})
    md, seen = read_jobs(), load_seen()
    for url, label in pc.get("live", {}).items():
        if url in seen and not seen[url].get("source_label", "").count(":"):
            seen[url]["source_label"] = label  # backfill so future runs can tell when it's gone
    closed = []
    gone = pc.get("gone", [])
    if len(gone) > 5:  # a feed hiccup, not a real mass-closing: do nothing and say so
        print(f"WARNING: {len(gone)} postings look gone at once; not closing any (probable feed glitch). Re-run later.")
        gone = []
    for url in gone:
        v = seen.get(url)
        if not v or v.get("status") not in ("New", "Apply") or not v.get("id"):
            continue
        status = f"Closed: posting removed {TODAY}"
        md = set_status(md, v["id"], status)
        v["status"] = status
        closed.append(f"{v['id']} {v.get('company')} — {v.get('title')}")
    atomic_write(JOBS, md)
    save_seen(seen)
    if closed:
        tidy(quiet=True)
    print(f"Live postings checked: {len(pc.get('live', {}))}; closed {len(closed)}" + (":" if closed else "."))
    for c in closed:
        print("  " + c)


# ---------- Active / Archive ----------

COLS = [c.strip() for c in HEADER.strip("|").split("|")]
DETAIL_RE = re.compile(r"^### (\d{3}) · .*?(?=^#{2,3} |^<details|^</details>|\Z)", re.M | re.S)


def jobs_cfg():
    c = json.load(open(CONFIG)).get("jobs_file", {}) if os.path.exists(CONFIG) else {}
    # Status rules live in statuses.py; config.json may still override these three keys if it names them.
    return {"archive_statuses": c.get("archive_statuses", statuses.archived_groups()),
            "active_order": c.get("active_order", statuses.ACTIVE_ORDER),
            "archive_file_after_days": c.get("archive_file_after_days", 30),
            "followup_days": c.get("followup_days", statuses.followup_days())}


_PAGE_INDEX = {}


def _slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def public_url(j):
    """Some ATS boards list postings through their API but don't serve the pages (Cursor's Ashby board 404s; the real pages live on
    cursor.com/careers). config sources.public_job_pages maps a source label to its real page pattern; the link is only swapped
    when the guessed slug is actually on that company's careers index, otherwise the feed's own URL stays."""
    rule = (json.load(open(CONFIG)).get("sources", {}).get("public_job_pages", {}) if os.path.exists(CONFIG) else {}).get(j.get("source_label", ""))
    if not rule:
        return j["url"]
    if rule["index"] not in _PAGE_INDEX:
        try:
            import urllib.request
            html = urllib.request.urlopen(urllib.request.Request(rule["index"], headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
            _PAGE_INDEX[rule["index"]] = set(re.findall(r'href="' + re.escape(urllib.parse.urlparse(rule["pattern"]).path.rsplit("/", 1)[0]) + r'/([a-z0-9-]+)"', html))
        except Exception:  # noqa: BLE001  a failed lookup must never block logging
            _PAGE_INDEX[rule["index"]] = set()
    slug = _slugify(j["title"])
    return rule["pattern"].format(slug=slug) if slug in _PAGE_INDEX[rule["index"]] else j["url"]


def save_jd(jid, j, description):
    """Keep the posting text so the Apply handoff (resume-tailor) has it even after the posting closes."""
    if not description:
        return
    os.makedirs(JD_DIR, exist_ok=True)
    open(os.path.join(JD_DIR, f"{jid}.md"), "w").write(
        f"# {j['company']} — {j['title']}\n\n{j['url']}\n\nLocation: {j.get('location', '')}  \n"
        f"Salary: {j.get('salary') or 'not stated'}  \nPosted: {j.get('posted_at') or 'unknown'}\n\n{description}\n")


# ---------- notes ----------

NOTE_RE = re.compile(r"^  - \[(\d{4}-\d{2}-\d{2})\] (.*)$", re.M)


def block_re(jid):
    return re.compile(rf"^### {re.escape(jid)} · .*?(?=^#{{2,3}} |^<details|^</details>|\Z)", re.M | re.S)


def get_notes(block):
    return [{"date": d, "text": t} for d, t in NOTE_RE.findall(block or "")]


def with_notes(block, notes):
    base = [l for l in block.rstrip("\n").split("\n") if not NOTE_RE.match(l) and l.strip() != "- **Notes:**"]
    if notes:
        base += ["- **Notes:**"] + [f"  - [{n['date']}] {n['text']}" for n in notes]
    return "\n".join(base) + "\n\n"


def edit_notes(jid, fn):
    """Apply fn(notes) -> notes to job jid's detail block in jobs.md or jobs-archive.md."""
    for path in (JOBS, ARCHIVE):
        if not os.path.exists(path):
            continue
        text = open(path).read()
        m = block_re(jid).search(text)
        if m:
            new = with_notes(m.group(0), fn(get_notes(m.group(0))))
            open(path, "w").write(text[:m.start()] + new + text[m.end():].lstrip("\n"))
            return True
    return False


def add_note(jid, text, when=None):
    text = cell(text)
    if not text:
        raise ValueError("empty note")
    if not edit_notes(jid, lambda ns: ns + [{"date": when or TODAY, "text": text}]):
        raise ValueError(f"{jid}: no such job")
    return f"Note added to {jid}."


def delete_note(jid, index):
    def drop(ns):
        if not 0 <= index < len(ns):
            raise ValueError("no such note")
        return ns[:index] + ns[index + 1:]
    if not edit_notes(jid, drop):
        raise ValueError(f"{jid}: no such job")
    return f"Note removed from {jid}."


# ---------- follow-ups ----------

def days_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def status_since(v, fallback=""):
    """Date this job's status last changed: the last entry of v['history'] (legacy: v['status_date'])."""
    v = v or {}
    h = v.get("history")
    return (h[-1][0] if h else v.get("status_date")) or fallback


def fold_legacy_status(v):
    """Turn the old tidy_status / status_date pair into the first v['history'] entry, so no date is lost."""
    h = v.setdefault("history", []) if ("tidy_status" in v or "status_date" in v) else v.get("history", [])
    if not h and v.get("tidy_status"):
        h.append([v.get("status_date") or TODAY, v["tidy_status"]])
    v.pop("tidy_status", None)
    v.pop("status_date", None)
    if "history" in v and not v["history"]:
        del v["history"]
    return v.get("history", [])


def note_status(v, status):
    """Append [date, status] to v['history'] when the status differs from the last entry."""
    h = fold_legacy_status(v) or v.setdefault("history", [])
    if not h or h[-1][1] != status:
        h.append([TODAY, status])
        del h[:-50]


def followup_info(rows, seen):
    """{id: {'due': bool, 'days': n, 'since': date, 'after': n}} for statuses listed in followup_days."""
    cfg = jobs_cfg()
    by_id = {v["id"]: v for v in seen.values() if v.get("id")}
    out = {}
    for r in rows:
        group = r["Status"].split(":")[0].split("(")[0].strip()
        after = cfg["followup_days"].get(group)
        if after is None:
            continue
        v = by_id.get(r["ID"]) or {}
        since = max(status_since(v, r["Found"]), v.get("followed_up") or "")
        days = days_between(since, TODAY)
        out[r["ID"]] = {"due": days >= after, "days": days, "since": since, "after": after, "status": group}
    return out


def followups(quiet=False):
    rows = table_rows(read_jobs())
    info = followup_info(rows, load_seen())
    due = [(r, info[r["ID"]]) for r in rows if info.get(r["ID"], {}).get("due")]
    if not quiet:
        print(f"Follow-ups due: {len(due)}")
        for r, i in due:
            print(f"  {r['ID']} | {r['Company']} | {r['Role']} | {i['status']} {i['days']} days (since {i['since']})")
    return due


def followed_up(jid):
    seen = load_seen()
    v = next((v for v in seen.values() if v.get("id") == jid), None)
    if v is None:
        raise ValueError(f"{jid}: no such job")
    v["followed_up"] = TODAY
    save_seen(seen)
    add_note(jid, "Followed up")
    tidy(quiet=True)
    return f"Recorded follow-up for {jid}; its clock restarts today."


# ---------- Apply handoff ----------

def apps_dir():
    return settings.apps_dir()


def company_slug(company):
    return re.sub(r"[^a-z0-9]+", "", company.lower().split(" (")[0])


APP_SNAPSHOT = os.path.join(ROOT, "data", "app_folders.json")


def app_folders():
    """(applications dir, folder names). When the directory can't be read (a scheduled launchd job is blocked from
    ~/Desktop by macOS privacy rules), fall back to the last snapshot taken by an interactive run."""
    d = apps_dir()
    try:
        names = sorted(f for f in os.listdir(d) if os.path.isdir(os.path.join(d, f)))
        atomic_write(APP_SNAPSHOT, json.dumps(names))
        return d, names
    except (OSError, TypeError):
        try:
            return d, json.load(open(APP_SNAPSHOT))
        except (OSError, ValueError):
            return d, []


def existing_folders(company):
    slug = company_slug(company)
    d, names = app_folders()
    if not d or not slug:
        return []
    return sorted(os.path.join(d, f) for f in names if re.sub(r"[^a-z0-9]+", "", f.lower().split("-")[0]) == slug)


def apply_queue(quiet=False):
    seen = load_seen()
    by_id = {v["id"]: (u, v) for u, v in seen.items() if v.get("id")}
    out = []
    for r in table_rows(read_jobs()):
        if r["Status"].split(":")[0].split("(")[0].strip() != "Apply":
            continue
        url, v = by_id.get(r["ID"], ("", {}))
        jd = os.path.join(JD_DIR, f"{r['ID']}.md")
        out.append({"id": r["ID"], "company": r["Company"], "role": r["Role"], "tier": r["Score"], "url": url,
                    "prepared": v.get("prepared"), "jd": jd if os.path.exists(jd) else None,
                    "cover_letter": letter_wanted(v, r["Score"]), "has_letter": bool(letter_file(v.get("prepared"))),
                    "existing_folders": existing_folders(r["Company"])})
    if not quiet:
        print(f"Apply queue: {len(out)}")
        for a in out:
            print(f"  {a['id']} | {a['company']} | {a['role']} | {a['tier']} | prepared: {a['prepared'] or 'no'} | "
                  f"JD saved: {'yes' if a['jd'] else 'no'} | existing folders: {', '.join(a['existing_folders']) or 'none'} | {a['url']}")
    return out


def letter_wanted(v, score_cell=""):
    """Write a cover letter for this application? The checkbox (seen[...]['cover_letter']) decides; with no choice made, A-tier rows get one."""
    if isinstance(v.get("cover_letter"), bool):
        return v["cover_letter"]
    return "(A)" in str(score_cell)


def letter_file(folder):
    """The cover letter in an application folder (a .docx or .pdf with 'CoverLetter' in its name), or None."""
    if folder and os.path.isdir(folder):
        for f in sorted(os.listdir(folder)):
            if re.search(r"cover.?letter", f, re.I) and f.lower().endswith((".docx", ".pdf")):
                return os.path.join(folder, f)
    return None


def set_cover_letter(jid, on):
    seen = load_seen()
    v = next((v for v in seen.values() if v.get("id") == str(jid)), None)
    if v is None:
        raise ValueError(f"{jid}: no such job")
    v["cover_letter"] = bool(on)
    save_seen(seen)
    return f"Cover letter {'will be written' if on else 'will not be written'} for {jid}."


def copy_jd(jid, folder):
    """Keep a copy of the job description in the application folder (as JD.md), so it survives the posting being taken down.
    Never overwrites a JD.md already there. Returns 'copied', 'exists' or a reason it couldn't."""
    src = os.path.join(JD_DIR, f"{jid}.md")
    if not folder or not os.path.isdir(folder):
        return "no folder"
    dst = os.path.join(folder, "JD.md")
    if os.path.exists(dst):
        return "exists"
    if not os.path.exists(src):
        return "no saved JD for this row"
    shutil.copyfile(src, dst)
    return "copied"


def backfill_jds():
    """Copy the saved JD into every prepared application folder that doesn't have one yet."""
    seen = load_seen()
    out = {}
    for v in seen.values():
        if v.get("id") and v.get("prepared"):
            out[v["id"]] = copy_jd(v["id"], v["prepared"])
    n = sum(r == "copied" for r in out.values())
    left = {k: r for k, r in out.items() if r not in ("copied", "exists")}
    return f"JD copied into {n} folder{'s' if n != 1 else ''}." + (f" Couldn't for: {', '.join(f'{k} ({r})' for k, r in sorted(left.items()))}." if left else "")


def mark_prepared(jid, folder):
    seen = load_seen()
    v = next((v for v in seen.values() if v.get("id") == jid), None)
    if v is None:
        raise ValueError(f"{jid}: no such job")
    v["prepared"] = folder
    save_seen(seen)
    add_note(jid, f"Application folder prepared: {folder}")
    jd = copy_jd(jid, folder)
    return f"Marked {jid} prepared: {folder}" + ("" if jd in ("copied", "exists") else f" (job description not copied: {jd})")


# ---------- application funnel (where do applications die?) ----------
FUNNEL_STAGES = ["Applied", "Recruiter screen", "Hiring manager", "Panel / onsite", "Offer"]
FUNNEL_OUTCOMES = ["Active", "Rejected", "Withdrew", "Offer"]
FUNNEL_SOURCES = ["Company site", "LinkedIn", "Referral", "Recruiter inbound", "Other"]
FUNNEL_LEVELS = ["Below my level", "Matches my level", "Above my level (stretch)"]
FUNNEL_ENUMS = {"stage": FUNNEL_STAGES, "outcome": FUNNEL_OUTCOMES, "source": FUNNEL_SOURCES, "level_fit": FUNNEL_LEVELS}
FUNNEL_MONEY = ("quote_lo", "quote_hi", "band_lo", "band_hi")  # dollars
FUNNEL_DATES = ("applied_date", "recruiter_date", "outcome_date")


def funnel_clean(fields):
    """Whitelist + validate. '' clears a field. Money may be given as 190 (= $190K) or 190000."""
    out = {}
    for k, v in (fields or {}).items():
        if v is None or v == "":
            out[k] = ""
        elif k in FUNNEL_ENUMS:
            if v not in FUNNEL_ENUMS[k]:
                raise ValueError(f"{k}: '{v}' is not one of {', '.join(FUNNEL_ENUMS[k])}")
            out[k] = v
        elif k in FUNNEL_MONEY:
            try:
                n = float(str(v).replace("$", "").replace(",", "").lower().rstrip("k")) * (1000 if str(v).lower().strip().endswith("k") else 1)
            except ValueError:
                raise ValueError(f"{k}: '{v}' is not a number")
            n = n * 1000 if n < 1000 else n
            if not 20000 <= n <= 2000000:
                raise ValueError(f"{k}: {v} is outside a plausible salary")
            out[k] = int(n)
        elif k in FUNNEL_DATES:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v)):
                raise ValueError(f"{k}: use YYYY-MM-DD")
            out[k] = str(v)
        elif k == "notes":
            out[k] = re.sub(r"\s+", " ", str(v)).strip()[:400]
        else:
            raise ValueError(f"unknown funnel field '{k}'")
    return out


def set_funnel(jid, fields):
    """Merge validated fields into seen[...]['funnel'] for row jid. Rejecting/withdrawing needs a stage reached."""
    clean = funnel_clean(fields)
    seen = load_seen()
    v = next((v for v in seen.values() if v.get("id") == str(jid)), None)
    if v is None:
        raise ValueError(f"{jid}: no such job")
    f = {**v.get("funnel", {}), **clean}
    if f.get("outcome") in ("Rejected", "Withdrew") and not f.get("stage"):
        raise ValueError("Pick the furthest stage you reached before marking Rejected/Withdrew.")
    v["funnel"] = {k: x for k, x in f.items() if x not in ("", None)}
    save_seen(seen)
    return f"Funnel details saved for {jid}."


def stamp_applied(ids):
    """First time a row becomes Applied, remember the date (feeds 'days after posting')."""
    seen = load_seen()
    changed = False
    for v in seen.values():
        if v.get("id") in ids and v.get("prepared"):
            copy_jd(v["id"], v["prepared"])  # last chance to keep the posting text before it can be taken down
        if v.get("id") in ids and not v.get("funnel", {}).get("applied_date"):
            v.setdefault("funnel", {})["applied_date"] = TODAY
            v["funnel"].setdefault("stage", "Applied")
            changed = True
    if changed:
        save_seen(seen)


def parse_jobs(md):
    """-> rows (dicts), details {id: markdown block}, pending-suggestion lines."""
    details = {m.group(1): m.group(0).rstrip() + "\n" for m in DETAIL_RE.finditer(md)}
    sugg = []
    if "## Pending suggestions" in md:
        sugg = [l for l in md.split("## Pending suggestions", 1)[1].split("\n") if l.startswith("- ")]
    return table_rows(md), details, sugg


def row_line(r):
    return "| " + " | ".join(r[c] for c in COLS) + " |"


def is_archived(status, cfg):
    return any(status.lower().startswith(s.lower()) for s in cfg["archive_statuses"])


def score_num(r):
    m = re.match(r"\d+", r["Score"])
    return int(m.group(0)) if m else 0


def table(rows):
    return "\n".join([HEADER, SEP] + [row_line(r) for r in rows])


def render_jobs(active, archived, details, sugg, cfg, due=()):
    days = cfg["archive_file_after_days"]
    arch_names = " / ".join(cfg["archive_statuses"])
    out = [
        "# Job Search Pipeline", "",
        "Change **Status** from `New` to `Apply`, `Pass: <reason>`, `Applied`, `Interviewing`, `Rejected`, or `Closed`. "
        "`Covered: by #<id>` marks another posting at a company that takes one application per candidate.",
        "Your Pass reasons are what the next run learns from, so a few words help.",
        f"Rows starting with {arch_names} move to **Archive** on the next tidy, and to `jobs-archive.md` after {days} days.",
        "Tidy runs at the start of every search, with `python3 scripts/log_jobs.py --tidy`, or from the dashboard "
        "(`python3 scripts/dashboard.py`).", "",
    ]
    if due:
        out += [f"## Follow-ups due ({len(due)})", ""]
        out += [f"- **{r['ID']} · {r['Company']}** — {r['Role']}: {i['status']} {i['days']} days (since {i['since']}). "
                f"Mark it followed up in the dashboard or `log_jobs.py --followed-up {r['ID']}`." for r, i in due] + [""]
    out += [
        f"## Active ({len(active)})", "", table(active), "",
        f"## Archive ({len(archived)})", "",
        "<details>",
        f"<summary>{arch_names} jobs from the last {days} days (click to expand)</summary>", "",
        table(archived), "", "</details>", "",
        "## Details", "",
    ]
    out += [details[r["ID"]] for r in active if r["ID"] in details]
    arch_details = [details[r["ID"]] for r in archived if r["ID"] in details]
    if arch_details:
        out += ["<details>", "<summary>Archived job details</summary>", ""] + arch_details + ["</details>", ""]
    out += ["## Pending suggestions"] + sugg + [""]
    return "\n".join(out)


def write_archive_file(moved, details):
    """Merge rows moved out of jobs.md into jobs-archive.md (newest first, no duplicates)."""
    old_rows, old_details, _ = parse_jobs(open(ARCHIVE).read()) if os.path.exists(ARCHIVE) else ([], {}, [])
    have = {r["ID"] for r in old_rows}
    rows = [r for r in moved if r["ID"] not in have] + old_rows
    det = {**old_details, **{r["ID"]: details[r["ID"]] for r in moved if r["ID"] in details}}
    render_archive_file(rows, det)


def render_archive_file(rows, det):
    body = ["# Job Search Archive", "",
            "Jobs moved out of jobs.md after sitting in its Archive section. The dashboard searches these too.", "",
            table(rows), "", "## Details", ""] + [det[r["ID"]] for r in rows if r["ID"] in det]
    atomic_write(ARCHIVE, "\n".join(body) + "\n")


def tidy(quiet=False):
    """Regroup jobs.md: Active (by status, then score) and a collapsed Archive (Pass/Closed).
    Archived rows older than archive_file_after_days (counted from when their status changed) go to jobs-archive.md."""
    cfg = jobs_cfg()
    md, seen = read_jobs(), load_seen()
    rows, details, sugg = parse_jobs(md)
    by_id = {v["id"]: v for v in seen.values() if v.get("id")}
    for r in rows:  # remember when each row's status last changed (separate from 'status', which --decisions owns)
        v = by_id.get(r["ID"])
        if v is not None:
            note_status(v, r["Status"])
    for v in seen.values():  # rows that live only in jobs-archive.md keep their dates too
        fold_legacy_status(v)
    changed_on = lambda r: status_since(by_id.get(r["ID"]), r["Found"])

    order = [s.lower() for s in cfg["active_order"]]
    rank = lambda r: order.index(r["Status"].split(":")[0].strip().lower()) if r["Status"].split(":")[0].strip().lower() in order else len(order)
    active = sorted([r for r in rows if not is_archived(r["Status"], cfg)], key=lambda r: (rank(r), -score_num(r), r["ID"]))
    archived = sorted([r for r in rows if is_archived(r["Status"], cfg)], key=lambda r: (changed_on(r), r["ID"]), reverse=True)

    cutoff = (date.today() - timedelta(days=cfg["archive_file_after_days"])).isoformat()
    moved = [r for r in archived if changed_on(r) <= cutoff]
    keep = [r for r in archived if changed_on(r) > cutoff]
    if moved:
        write_archive_file(moved, details)
    info = followup_info(active, seen)
    due = [(r, info[r["ID"]]) for r in active if info.get(r["ID"], {}).get("due")]
    atomic_write(JOBS, render_jobs(active, keep, details, sugg, cfg, due))
    save_seen(seen)
    msg = (f"Tidied jobs.md: {len(active)} active, {len(keep)} archived"
           + (f"; moved {len(moved)} to jobs-archive.md" if moved else "")
           + (f"; {len(due)} follow-up{'s' if len(due) != 1 else ''} due" if due else "") + ".")
    if not quiet:
        print(msg)
    return msg


STATUS_CHOICES = statuses.CHOICES


def clean_status(status):
    """Normalize what the dashboard/CLI sends: 'Pass' + reason -> 'Pass: reason'; no pipes or newlines."""
    status = cell(status)
    if not status:
        raise ValueError("empty status")
    if not statuses.is_valid(status):
        raise ValueError(f"unknown status '{status}' (use one of {', '.join(STATUS_CHOICES)})")
    return status


def company_key(name):
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


OPEN_GROUPS = statuses.OPEN


def plan_cover(jid, primary=None):
    """Companies that take one application per candidate: choose the posting to apply to and cover the rest.
    Returns (primary_row, changes, covered_rows). The primary is `primary` if given, else a row already Apply/Applied/Interviewing,
    else the highest-scoring New/Saved row at the company."""
    rows = table_rows(read_jobs())
    me = next((r for r in rows if r["ID"] == str(jid)), None)
    if me is None:
        raise ValueError(f"{jid}: no such job in jobs.md")
    grp = lambda r: statuses.group(r["Status"])
    same = [r for r in rows if company_key(r["Company"]) == company_key(me["Company"]) and grp(r) in OPEN_GROUPS]
    if primary:
        prim = next((r for r in same if r["ID"] == str(primary)), None)
        if prim is None:
            raise ValueError(f"{primary} isn't an open posting at {me['Company']}")
    else:
        stage = {"Interviewing": 0, "Applied": 1, "Apply": 2}
        started = sorted([r for r in same if grp(r) in stage], key=lambda r: (stage[grp(r)], -score_num(r), r["ID"]))
        prim = started[0] if started else sorted(same, key=lambda r: (-score_num(r), r["ID"]))[0]
    # With an explicit primary (you know which one actually went through) rows marked Apply/Applied by mistake are covered too;
    # an auto-picked primary only ever covers postings you haven't acted on.
    coverable = statuses.COVER_EXPLICIT if primary else statuses.COVER_AUTO
    sib = [r for r in same if r["ID"] != prim["ID"] and grp(r) in coverable]
    changes = ([{"id": prim["ID"], "status": "Apply"}] if statuses.GROUPS[grp(prim)]["triage"] else []) + \
              [{"id": r["ID"], "status": f"Covered: by #{prim['ID']}"} for r in sib]
    return prim, changes, sib


def set_statuses(changes):
    """changes = [{'id': '012', 'status': 'Pass: too post-sales'}]. Edits jobs.md (or jobs-archive.md; a row
    restored to an active status there moves back into jobs.md), then tidies. Doesn't touch seen['status'],
    so --decisions still reports these as the candidate's decisions for the learning step."""
    cfg = jobs_cfg()
    md = read_jobs()
    arch = open(ARCHIVE).read() if os.path.exists(ARCHIVE) else ""
    in_md = {r["ID"] for r in table_rows(md)}
    a_rows, a_det, _ = parse_jobs(arch) if arch else ([], {}, [])
    in_arch = {r["ID"]: r for r in a_rows}
    done, errors, restored = [], [], []
    cur = {r["ID"]: r["Status"] for r in table_rows(md)}
    cur.update({k: r["Status"] for k, r in in_arch.items()})
    for c in changes:
        jid = str(c.get("id", "")).strip()
        try:
            status = clean_status(c.get("status"))
        except ValueError as e:
            errors.append(f"{jid}: {e}")
            continue
        why_not = statuses.transition_error(cur.get(jid, ""), status)
        if why_not:
            errors.append(f"{jid}: {why_not}")
            continue
        if jid in in_md:
            md = set_status(md, jid, status)
        elif jid in in_arch:
            in_arch[jid]["Status"] = status
            if not is_archived(status, cfg):
                restored.append(jid)
        else:
            errors.append(f"{jid}: no such job")
            continue
        done.append(f"{jid} -> {status}")
    if restored:  # bring rows back from jobs-archive.md into jobs.md
        md = md.replace(SEP + "\n", SEP + "\n" + "\n".join(row_line(in_arch[i]) for i in restored) + "\n", 1)
        md = md.replace("## Details\n", "## Details\n\n" + "".join(a_det.get(i, "") for i in restored), 1)
    if arch and (restored or any(d.split(" ")[0] in in_arch for d in done)):
        keep = [r for r in a_rows if r["ID"] not in restored]
        render_archive_file(keep, a_det)
    atomic_write(JOBS, md)
    stamp_applied({d.split(" ")[0] for d in done if statuses.stamps_applied(d.split(" -> ", 1)[1])})
    msg = tidy(quiet=True)
    summary = (f"Saved {len(done)} status change{'s' if len(done) != 1 else ''}"
               + (f", restored {len(restored)} from the archive file" if restored else "") + ". " + msg)
    return {"saved": done, "errors": errors, "message": summary}


def update_scored(updates):
    """updates: [{'id', 'score' ('9 (A)'), 'angle', 'salary', 'why', 'gaps', 'status' (optional)}]. Rewrites those jobs.md rows
    and their detail lines in place (used when a Saved row gets scored after its posting was read)."""
    md = read_jobs()
    by_id = {u["id"]: u for u in updates}
    out = []
    for line in md.split("\n"):
        m = re.match(r"\| (\d{3}) \|", line)
        if m and m.group(1) in by_id:
            u = by_id[m.group(1)]
            cells = line.strip().strip("|").split("|")
            for idx, key in ((5, "angle"), (6, "score"), (7, "salary"), (8, "status")):
                if u.get(key):
                    cells[idx] = f" {cell(u[key])} "
            line = "|" + "|".join(cells) + "|"
        out.append(line)
    md = "\n".join(out)
    for jid, u in by_id.items():
        for label, key in (("Why it fits", "why"), ("Gaps / red flags", "gaps")):
            if u.get(key) is not None:
                md = re.sub(rf"(^### {jid} · .*?^- \*\*{re.escape(label)}:\*\* )[^\n]*$", lambda m: m.group(1) + cell(u[key]), md, count=1, flags=re.M | re.S)
    atomic_write(JOBS, md)
    return len(by_id)


def suggest(line):
    md = read_jobs()
    md = md.rstrip("\n") + f"\n- [{TODAY}] {line.strip()}\n"
    atomic_write(JOBS, md)
    print("Added suggestion.")


RUNLOG_HEADER = ("| Date | Fetched | Candidates | Logged by source | Failed sources | Notes |\n"
                 "| :-- | :-- | :-- | :-- | :-- | :-- |\n")


def runlog(notes):
    """One row per run. 'Logged by source' shows which feeds produce jobs worth logging, to prune or add sources."""
    cpath, spath = os.path.join(ROOT, "data", "candidates.json"), os.path.join(ROOT, "data", "scored.json")
    c = json.load(open(cpath))
    by_source = {}
    if os.path.exists(spath) and os.path.getmtime(spath) >= os.path.getmtime(cpath):  # this run's scoring
        for j in json.load(open(spath)).get("logged", []):
            src = j.get("source_label") or j.get("source") or "?"
            by_source[src] = by_source.get(src, 0) + 1
    if not os.path.exists(RUNLOG):
        atomic_write(RUNLOG, "# Run log\n\n" + RUNLOG_HEADER)
    log = open(RUNLOG).read()
    if "Logged by source" not in log:  # migrate the older 5-column table
        old = [l.strip().strip("|").strip().split(" | ") for l in log.split("\n") if l.startswith("| 20")]
        rows = ["| " + " | ".join(c[:3] + ["—"] + c[3:]) + " |" for c in old]
        atomic_write(RUNLOG, "# Run log\n\n" + RUNLOG_HEADER + "".join(r + "\n" for r in rows))
    with open(RUNLOG, "a") as f:
        f.write(f"| {TODAY} | {c['total_fetched']} | {len(c['candidates'])} | "
                f"{cell(', '.join(f'{k} {v}' for k, v in sorted(by_source.items()))) or '0'} | "
                f"{cell(', '.join(c['failures'])) or '—'} | {cell(notes)} |\n")
    print("Run logged.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--add")
    g.add_argument("--decisions", action="store_true")
    g.add_argument("--suggest")
    g.add_argument("--runlog")
    g.add_argument("--reconcile", action="store_true")
    g.add_argument("--set", nargs=2, metavar=("ID", "STATUS"))
    g.add_argument("--note", nargs=2, metavar=("ID", "TEXT"))
    g.add_argument("--followed-up", metavar="ID")
    g.add_argument("--followups", action="store_true")
    g.add_argument("--apply-queue", action="store_true")
    g.add_argument("--prepared", nargs=2, metavar=("ID", "FOLDER"))
    g.add_argument("--jd-backfill", action="store_true", help="copy the saved JD into prepared application folders that lack JD.md")
    ap.add_argument("--tidy", action="store_true", help="regroup jobs.md (runs after any other command given)")
    a = ap.parse_args()
    if not (a.add or a.decisions or a.reconcile or a.suggest or a.runlog or a.set or a.note or a.followed_up
            or a.followups or a.apply_queue or a.prepared or a.jd_backfill or a.tidy):
        ap.error("give a command, e.g. --tidy")
    if a.add:
        add(a.add)
    elif a.decisions:
        decisions()
    elif a.reconcile:
        reconcile()
    elif a.suggest:
        suggest(a.suggest)
    elif a.runlog:
        runlog(a.runlog)
    elif a.set:
        r = set_statuses([{"id": a.set[0], "status": a.set[1]}])
        print(r["message"])
        for e in r["errors"]:
            print("  error:", e)
    elif a.note:
        print(add_note(*a.note))
    elif a.followed_up:
        print(followed_up(a.followed_up))
    elif a.followups:
        followups()
    elif a.apply_queue:
        apply_queue()
    elif a.prepared:
        print(mark_prepared(*a.prepared))
    elif a.jd_backfill:
        print(backfill_jds())
    if a.tidy:
        tidy()
