#!/usr/bin/env python3
"""Warm-intro finder storage and drafts. The LinkedIn searching itself is done by Claude in the candidate's own browser (see
.claude/skills/warm-intro/SKILL.md); this script validates and stores what it finds and writes DRAFT notes. It never sends anything.

  intros.py --queue              Apply/Applied rows that have no intro search yet
  intros.py --save ID file.json  validate + store results for row ID (file from the skill)
  intros.py --show ID            print stored contacts and draft notes for row ID
"""
import argparse
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_jobs as lj  # noqa: E402
import settings  # noqa: E402

DIR = os.path.join(lj.ROOT, "data", "intros")
LI_RE = re.compile(r"^https://www\.linkedin\.com/in/[A-Za-z0-9%_-]+/?$")
ROLES = ("hiring_manager", "peer", "recruiter")
PROOF = settings.profile().get("proof_line", "")  # one true, measurable line from the candidate's resume (config.json profile.proof_line)


def _s(v, n=160):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def clean_person(p):
    url = _s(p.get("url"), 200).split("?")[0]
    if not LI_RE.match(url):
        raise ValueError(f"not a LinkedIn profile URL: {url[:60]}")
    role = p.get("role") if p.get("role") in ROLES else "peer"
    mutuals = []
    for m in (p.get("mutuals") or [])[:6]:
        murl = _s(m.get("url"), 200).split("?")[0]
        if m.get("name") and (not murl or LI_RE.match(murl)):
            mutuals.append({"name": _s(m["name"], 80), "url": murl})
    return {"name": _s(p.get("name"), 80), "title": _s(p.get("title"), 160), "url": url, "degree": _s(p.get("degree"), 4),
            "location": _s(p.get("location"), 80), "role": role, "mutuals": mutuals, "mutual_count": int(p.get("mutual_count") or len(mutuals))}


def path(jid):
    return os.path.join(DIR, f"{jid}.json")


def load(jid):
    try:
        return json.load(open(path(jid)))
    except (OSError, ValueError):
        return None


def save(jid, data):
    rows = {r["ID"]: r for r in lj.table_rows(lj.read_jobs())}
    arch = os.path.join(lj.ROOT, "jobs-archive.md")
    if jid not in rows and os.path.exists(arch):
        rows.update({r["ID"]: r for r in lj.parse_jobs(open(arch).read())[0]})
    if jid not in rows:
        raise ValueError(f"{jid}: no such job")
    people = [clean_person(p) for p in (data.get("people") or [])][:25]
    out = {"id": jid, "company": rows[jid]["Company"], "role": rows[jid]["Role"], "searched": date.today().isoformat(),
           "company_linkedin_id": _s(data.get("company_linkedin_id"), 20), "people": people, "note": _s(data.get("note"), 300)}
    os.makedirs(DIR, exist_ok=True)
    lj.atomic_write(path(jid), json.dumps(out, indent=1))
    return f"Saved {len(people)} contacts for {jid} ({out['company']})."


def drafts(d, applied=False):
    """Draft notes from stored contacts. Every draft is for the candidate to read, edit and send themselves."""
    if not d:
        return []
    co, role = d["company"], d["role"]
    did = "I applied for" if applied else "I'm applying for"
    out = []
    people = d["people"]
    for p in [p for p in people if p["degree"] == "1st" and p["role"] != "hiring_manager"][:3]:  # already connected: the warmest path
        pf = p["name"].split()[0]
        out.insert(0, {"to": p["name"], "kind": "Ask a 1st-degree connection at the company for a referral or a quick chat (warmest path)",
                       "text": f"Hi {pf}, hope you're doing well. {did} the {role} role at {co} and thought of you. Could I get your read on the team, "
                               f"and if you think I'm a fit, would you be willing to put in a referral? Happy to send my resume and a short summary."})
    hms = [p for p in people if p["role"] == "hiring_manager"]
    for h in hms[:2]:
        first = h["name"].split()[0] if h["name"] else "there"
        out.append({"to": h["name"], "kind": "Connection note to the likely hiring manager (LinkedIn limit: 300 characters)",
                    "text": f"Hi {first}, {did} the {role} role at {co}." + (f" {PROOF}" if PROOF else "")
                            + " Would value a few minutes if you're open to it."[:300]})
        for m in h["mutuals"][:2]:
            mf = m["name"].split()[0]
            out.append({"to": m["name"], "kind": f"Ask a shared connection for an intro to {h['name']}",
                        "text": f"Hi {mf}, {did} the {role} role at {co} and noticed you know {h['name']}, who leads the team. "
                                f"Would you be comfortable making a quick intro, or tell me if you'd rather not? Happy to send a two-line blurb to forward."})
    for p in [p for p in people if p["role"] in ("peer", "recruiter")][:3]:
        if p["mutuals"]:
            pf = p["name"].split()[0]
            out.append({"to": p["name"], "kind": "Low-pressure question to someone on the team",
                        "text": f"Hi {pf}, I'm looking at the {role} role at {co}. I'd value your view of the team and what the work is really like. "
                                f"Could I ask you two or three questions?"})
    return out


def queue():
    seen = lj.load_seen()
    by_id = {v["id"]: v for v in seen.values() if v.get("id")}
    out = []
    for r in lj.table_rows(lj.read_jobs()):
        g = r["Status"].split(":")[0].split("(")[0].strip()
        if g in ("Apply", "Applied") and not load(r["ID"]):
            out.append({"id": r["ID"], "company": r["Company"], "role": r["Role"], "status": g})
    return out


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--queue", action="store_true")
    g.add_argument("--save", nargs=2, metavar=("ID", "FILE"))
    g.add_argument("--show")
    a = ap.parse_args()
    if a.queue:
        for q in queue():
            print(f"{q['id']} | {q['company']} | {q['role']} | {q['status']}")
    elif a.save:
        print(save(a.save[0], json.load(open(a.save[1]))))
    else:
        d = load(a.show)
        if not d:
            sys.exit(f"{a.show}: no intro search yet")
        print(f"{d['company']} - {d['role']} (searched {d['searched']})")
        for p in d["people"]:
            print(f"  [{p['role']}] {p['name']} - {p['title']} ({p['degree']}) {p['url']}  via: {', '.join(m['name'] for m in p['mutuals']) or '-'}")
        for x in drafts(d):
            print(f"\n--> {x['to']}: {x['kind']}\n{x['text']}")


if __name__ == "__main__":
    main()
