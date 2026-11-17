#!/usr/bin/env python3
"""LinkedIn Saved jobs: import the list the browser worker read, then read each posting and score it with the normal rules.

  saved.py --import data/linkedin_saved.json   add new Saved rows (skips anything already tracked)
  saved.py --score [--limit N]                  read + score every Saved row that has no score yet
  saved.py --all FILE                           import, then score

LinkedIn's public posting endpoint supplies the job text (no login, one request per job, paced). Read-only: nothing is applied to or changed on LinkedIn.
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_jobs as fj  # noqa: E402
import log_jobs as lj  # noqa: E402
import run_cycle as rc  # noqa: E402
import settings  # noqa: E402

ROOT = lj.ROOT
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
CLOSED_RE = re.compile(r"no longer accepting applications|job is no longer available|this job has expired", re.I)
SAVED_SOURCE = "linkedin-saved"


def view_url(jid):
    return f"https://www.linkedin.com/jobs/view/{jid}/"


MODES = {"R": "Remote", "H": "Hybrid", "O": "On-site"}


def import_list(rows, log=print):
    """rows: [{'id', 'mode' (R/H/O, optional)}] or with 'title'/'company'/'location'. Adds those not already tracked as Saved rows
    (reading each new posting's title, company and location from its public page). Returns the number added."""
    seen = lj.load_seen()
    keys = {v.get("key") for v in seen.values() if v.get("key")}
    logged = []
    for r in rows:
        url = view_url(r["id"])
        if url in seen:
            continue
        if not (r.get("title") and r.get("company")):
            post = fetch_posting(r["id"])
            time.sleep(1.0)
            if not post or not post.get("title"):
                log(f"  {r['id']}: could not read the posting, skipped this time")
                continue
            r = {**r, "title": post["title"], "company": post["company"], "location": post["location"]}
        mode = MODES.get(r.get("mode", ""), "")
        if mode and mode.lower() not in r.get("location", "").lower():
            r["location"] = f"{r.get('location', '')} ({mode})".strip()
        key = fj.norm_key(r["company"], r["title"])
        if key in keys:
            continue
        keys.add(key)
        logged.append({"key": key, "url": url, "company": r["company"], "title": r["title"], "location": r.get("location", ""),
                       "angle": "", "score": None, "tier": "", "salary": "", "posted_at": "", "source": SAVED_SOURCE,
                       "source_label": SAVED_SOURCE, "status": "Saved",
                       "why": "Saved on your LinkedIn Job Tracker. Not yet scored: the posting has not been read.",
                       "gaps": "Unscored: no posting read yet, so salary, theme and legitimacy are unchecked."})
    if not logged:
        return 0
    path = os.path.join(ROOT, "data", "tmp_saved.json")
    json.dump({"logged": logged, "dropped": []}, open(path, "w"))
    try:
        lj.add(path)
    finally:
        os.remove(path)
    return len(logged)


def fetch_posting(jid):
    """-> {'text','salary','closed'} from LinkedIn's public posting page; None when it can't be read."""
    req = urllib.request.Request(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{jid}", headers={"User-Agent": UA, "Accept-Language": "en-US"})
    try:
        raw = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return {"closed": True, "text": "", "salary": ""} if e.code in (404, 410) else None
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', raw, re.S)
    text = ""
    if m:
        body = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", m.group(1))
        text = re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
    sal = re.search(r'compensation__salary[^>]*>\s*([^<]+?)\s*<', raw)
    pick = lambda pat: html.unescape((re.search(pat, raw) or [None, ""])[1]).strip()
    return {"text": text, "salary": html.unescape(sal.group(1)) if sal else "", "closed": bool(CLOSED_RE.search(raw)) or not text,
            "title": pick(r'top-card-layout__title[^>]*>\s*([^<]+)'), "company": pick(r'topcard__org-name-link[^>]*>\s*([^<]+)'),
            "location": pick(r'topcard__flavor--bullet[^>]*>\s*([^<]+)')}


def _unscored():
    seen = lj.load_seen()
    rows = {r["ID"]: r for r in lj.table_rows(lj.read_jobs())}
    out = []
    for url, v in seen.items():
        r = rows.get(v.get("id"))
        if r and v.get("source_label") == SAVED_SOURCE and r["Status"].startswith("Saved") and r["Score"].strip() in ("—", ""):
            out.append({"id": v["id"], "url": url, "company": v["company"], "title": v["title"], "location": v.get("location", ""),
                        "li_id": re.search(r"/view/(\d+)", url).group(1)})
    return sorted(out, key=lambda x: x["id"])


def score_saved(limit=60, log=print):
    cfg = settings.load()
    auto = {**rc.DEFAULTS, **cfg.get("automation", {})}
    sc = cfg["scoring"]
    todo = _unscored()[:limit]
    updates, judged, notes = {}, [], {"closed": 0, "unreadable": 0}
    real_load_seen = fj.load_seen
    fj.load_seen = lambda c: (set(), set())  # these rows are already in seen.json; score them anyway
    try:
        for t in todo:
            post = fetch_posting(t["li_id"])
            time.sleep(1.2)
            if post is None:
                notes["unreadable"] += 1
                log(f"  {t['id']} {t['company']}: could not read the posting, left unscored")
                continue
            if post["closed"]:
                notes["closed"] += 1
                updates[t["id"]] = {"id": t["id"], "score": "—", "status": "Closed: posting no longer on LinkedIn",
                                    "why": "Saved on your LinkedIn Job Tracker.", "gaps": "LinkedIn no longer shows this posting (closed or removed)."}
                continue
            lj.save_jd(t["id"], {"company": t["company"], "title": t["title"], "url": t["url"], "location": t["location"], "salary": post["salary"]}, post["text"])
            j = fj.job("greenhouse", t["company"], t["title"], t["location"], t["url"], date.today().isoformat(), post["text"], salary=post["salary"])
            kept, reasons, _ = fj.prefilter([j], cfg, 3650)
            if not kept:
                why = ", ".join(reasons) or "filtered"
                updates[t["id"]] = {"id": t["id"], "score": "0 (C)", "why": "Saved on your LinkedIn Job Tracker.",
                                    "gaps": f"Fails the search rules: {why}. Read the posting first if you still want it."}
                continue
            j = kept[0]
            j["description"] = j["description"][:6000]
            if j["prescore"]["tier"] == "C":  # no theme from your profile: the daily run drops these too
                updates[t["id"]] = {"id": t["id"], "score": f"{j['prescore']['points']} (C)", "salary": fj.salary_label(j) or "—",
                                    "why": "Saved on your LinkedIn Job Tracker.",
                                    "gaps": "None of your profile themes appear in the posting, so the search rules score it C."}
                continue
            j["_id"] = t["id"]
            ok, locnote = rc.location_ok(j)
            if not ok:
                updates[t["id"]] = {"id": t["id"], "score": "0 (C)", "why": "Saved on your LinkedIn Job Tracker.",
                                    "gaps": "Location unconfirmed: it is not clearly remote US or in your home area."}
                continue
            judged.append(j)
        if judged:
            profile = open(os.path.join(ROOT, "search-instructions.md")).read()
            res = {}
            for i in range(0, len(judged), auto["judge_batch"]):
                part, note = rc.judge(judged[i:i + auto["judge_batch"]], profile, auto, False)
                res.update(part)
                log("  " + note)
            for j in judged:
                e = res.get(j["url"])
                if not e:
                    log(f"  {j['_id']} {j['company']}: no model judgment, left unscored")
                    continue
                r = rc.resolve(e, j["title"])
                pts = j["prescore"]["points"] + r["adjust"]
                if r["drop"]:
                    updates[j["_id"]] = {"id": j["_id"], "score": f"{pts} (C)", "angle": r["angle"], "salary": fj.salary_label(j),
                                         "why": r["why"], "gaps": f"Would be dropped: {r['drop']}. {r['gaps']}"}
                    continue
                if j["strong_hits"]:
                    tier = "A" if pts >= sc["a_tier"] else "B" if pts >= sc["b_tier"] else "C"
                else:
                    tier = "C"
                gaps = " ".join(x for x in (rc.det_gaps(j, locnote), r["gaps"]) if x)
                updates[j["_id"]] = {"id": j["_id"], "score": f"{pts} ({tier})", "angle": r["angle"], "salary": fj.salary_label(j) or "—",
                                     "why": r["why"] or "; ".join(j["prescore"]["breakdown"]), "gaps": rc.clean(rc.dedupe_sentences(gaps), 600)}
    finally:
        fj.load_seen = real_load_seen
    if updates:
        lj.update_scored(list(updates.values()))
        lj.tidy(quiet=True)
    return {"scored": len(updates), "closed": notes["closed"], "unreadable": notes["unreadable"], "remaining": len(_unscored())}


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--import", dest="imp")
    g.add_argument("--score", action="store_true")
    g.add_argument("--all")
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()
    if a.imp or a.all:
        data = json.load(open(a.imp or a.all))
        print(f"Added {import_list(data['rows'] if isinstance(data, dict) else data)} Saved rows.")
    if a.score or a.all:
        print(score_saved(a.limit))


if __name__ == "__main__":
    main()
