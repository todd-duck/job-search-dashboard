#!/usr/bin/env python3
"""Interview journey and rejection tracking, and the "why aren't we getting through?" analysis.

Every application keeps an ordered list of events in data/seen.json (seen[url]['events']): recruiter call, hiring manager, demo,
panel, anything else a company invents. Event types map to a few comparable buckets (Screen, Hiring manager, ...) so processes
that differ widely still line up. A rejection is its own record (seen[url]['rejection']): what they said, what you think the
real cause was, and the fix to try. analysis() turns all of it into drop-off points, patterns and fixes.

Usage:
  journey.py --migrate     seed events from the older funnel fields (safe to re-run)
  journey.py --analysis    print the analysis
"""
import argparse
import json
import os
import re
import sys
import zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import log_jobs as lj  # noqa: E402
import settings  # noqa: E402

BUCKETS = ["Applied", "Screen", "Hiring manager", "Technical", "Panel / Exec", "Offer"]
# (event type, bucket). Terminal events have no bucket: they end the process rather than advance it.
EVENT_TYPES = [
    ("Applied", "Applied"), ("Recruiter intro", "Screen"), ("Recruiter call", "Screen"), ("Hiring manager call", "Hiring manager"),
    ("Technical interview / demo", "Technical"), ("Take-home / presentation", "Technical"), ("Panel / onsite", "Panel / Exec"),
    ("Exec / leadership", "Panel / Exec"), ("References / background check", "Panel / Exec"), ("Offer", "Offer"),
    ("Rejected", None), ("Withdrew", None), ("No response", None), ("Other", None),
]
TYPE_BUCKET = dict(EVENT_TYPES)
TERMINAL = ("Rejected", "Withdrew", "No response")
INTERVIEWS = tuple(t for t, b in EVENT_TYPES if b and b not in ("Applied", "Offer"))  # types that get a debrief
RESULTS = ["Passed", "Waiting", "Failed", "Unknown"]
HOW_TOLD = ["Email", "Call", "Recruiter relayed it", "Silence (no reply)", "Other"]
CAUSES = [
    "Resume / level mismatch", "Missing skill or tool", "Pre-sales vs post-sales mismatch", "Compensation", "Location / territory / RTO",
    "Competing candidate (stronger match)", "Role frozen, filled or changed", "Interview performance", "Communication / culture fit",
    "No response (silence)", "Unknown / generic",
]
LEGACY_STAGE = {"Applied": "Applied", "Screen": "Recruiter screen", "Hiring manager": "Hiring manager", "Technical": "Panel / onsite",
                "Panel / Exec": "Panel / onsite", "Offer": "Offer"}
SILENT_DAYS = 21
MIN_SAMPLE = 5
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

OPTIONS = {"types": [t for t, _ in EVENT_TYPES], "interviews": list(INTERVIEWS), "results": RESULTS, "how": HOW_TOLD,
           "causes": CAUSES, "silent_days": SILENT_DAYS}


def _squash(s, n):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _date(v, field):
    v = str(v or "").strip()
    if v and not DATE_RE.fullmatch(v):
        raise ValueError(f"{field}: use YYYY-MM-DD (or leave it blank if you don't know)")
    return v


def event_clean(f):
    """Validate one event. A blank date means 'don't know'; type is the only required field."""
    t = f.get("type")
    if t not in TYPE_BUCKET:
        raise ValueError(f"type: pick one of {', '.join(TYPE_BUCKET)}")
    res = f.get("result") or ("Unknown" if t != "Applied" else "Passed")
    if res not in RESULTS:
        raise ValueError(f"result: pick one of {', '.join(RESULTS)}")
    rating = str(f.get("rating") or "").strip()
    if rating and rating not in ("1", "2", "3", "4", "5"):
        raise ValueError("rating: 1 to 5")
    e = {"date": _date(f.get("date"), "date"), "type": t, "result": res}
    for k, n in (("label", 60), ("who", 80), ("notes", 400), ("asked", 600), ("went_well", 400), ("stumbled", 400), ("resume", 120)):
        if _squash(f.get(k), n):
            e[k] = _squash(f.get(k), n)
    if rating:
        e["rating"] = int(rating)
    if t == "Other" and not e.get("label"):
        raise ValueError("Give 'Other' a short label, for example 'architecture whiteboard'.")
    return e


def _record(seen, jid):
    v = next((v for v in seen.values() if v.get("id") == str(jid)), None)
    if v is None:
        raise ValueError(f"{jid}: no such job")
    return v


def synth_events(v):
    """Events implied by the older funnel fields, so nothing recorded before this feature is lost."""
    f = v.get("funnel") or {}
    out = []
    if f.get("applied_date"):
        out.append({"date": f["applied_date"], "type": "Applied", "result": "Passed"})
    stage = f.get("stage")
    if stage in ("Recruiter screen", "Hiring manager", "Panel / onsite", "Offer"):
        out.append({"date": f.get("recruiter_date", ""), "type": "Recruiter call", "result": "Passed" if stage != "Recruiter screen" else "Unknown"})
    if stage in ("Hiring manager", "Panel / onsite", "Offer"):
        out.append({"date": "", "type": "Hiring manager call", "result": "Unknown" if stage == "Hiring manager" else "Passed"})
    if stage in ("Panel / onsite", "Offer"):
        out.append({"date": "", "type": "Panel / onsite", "result": "Unknown" if stage == "Panel / onsite" else "Passed"})
    if stage == "Offer":
        out.append({"date": f.get("outcome_date", ""), "type": "Offer", "result": "Unknown"})
    return out


def events_of(v):
    return v["events"] if "events" in v else synth_events(v)


def _sorted(events):
    """Stable sort by date; an event with no date stays where it was put, right after the one before it."""
    last, keyed = "", []
    for i, e in enumerate(events):
        last = e.get("date") or last
        keyed.append((last, i, e))
    return [e for _, _, e in sorted(keyed, key=lambda x: (x[0], x[1]))]


def furthest(events):
    """Index into BUCKETS of the furthest step reached (-1 if none)."""
    idx = [BUCKETS.index(TYPE_BUCKET[e["type"]]) for e in events if TYPE_BUCKET.get(e["type"])]
    return max(idx, default=-1)


def sync_funnel(v):
    """Keep the older funnel fields (used by the Funnel panel) in step with the events."""
    ev = events_of(v)
    f = v.setdefault("funnel", {})
    fi = furthest(ev)
    if fi >= 0:
        f["stage"] = LEGACY_STAGE[BUCKETS[fi]]
    applied = next((e["date"] for e in ev if e["type"] == "Applied" and e.get("date")), "")
    if applied and not f.get("applied_date"):
        f["applied_date"] = applied
    if any(e["type"] == "Offer" for e in ev):
        f["outcome"] = "Offer"
    elif any(e["type"] == "Withdrew" for e in ev):
        f["outcome"] = "Withdrew"
    elif v.get("rejection"):
        f["outcome"] = "Rejected"
        f["outcome_date"] = v["rejection"].get("date") or f.get("outcome_date", "")
        f.setdefault("stage", "Applied")


def add_event(jid, fields, index=None):
    """Append an event (or, with index, merge fields into an existing one: that is how a debrief gets added later)."""
    seen = lj.load_seen()
    v = _record(seen, jid)
    ev = list(events_of(v))
    if index is None:
        ev.append(event_clean(fields))
        msg = "Event added"
    else:
        if not 0 <= index < len(ev):
            raise ValueError("no such event")
        merged = {**ev[index], **{k: x for k, x in (fields or {}).items()}}
        ev[index] = {k: x for k, x in event_clean(merged).items() if x not in ("", None)}
        msg = "Event updated"
    v["events"] = _sorted(ev)
    sync_funnel(v)
    lj.save_seen(seen)
    return f"{msg} for {jid}."


def delete_event(jid, index):
    seen = lj.load_seen()
    v = _record(seen, jid)
    ev = list(events_of(v))
    if not 0 <= index < len(ev):
        raise ValueError("no such event")
    del ev[index]
    v["events"] = ev
    lj.save_seen(seen)
    return f"Event removed from {jid}."


def rejection_clean(f):
    cause = f.get("cause")
    if cause not in CAUSES:
        raise ValueError("Pick your best read of the real cause (choose 'Unknown / generic' if you can't tell).")
    how = f.get("how") or "Email"
    if how not in HOW_TOLD:
        raise ValueError(f"how told: pick one of {', '.join(HOW_TOLD)}")
    return {"date": _date(f.get("date"), "date") or lj.TODAY, "how": how, "stated": _squash(f.get("stated"), 600),
            "cause": cause, "detail": _squash(f.get("detail"), 400), "fix": _squash(f.get("fix"), 300)}


def record_rejection(jid, fields):
    """Store the rejection, add the closing event, and set the row's status to Rejected."""
    r = rejection_clean(fields)
    silence = r["how"] == "Silence (no reply)"
    short = _squash(r["stated"] or ("no answer" if silence else r["cause"]), 90).rstrip(".")
    seen = lj.load_seen()
    step_before = BUCKETS[max(furthest(events_of(_record(seen, jid))), 0)]
    res = lj.set_statuses([{"id": str(jid), "status": f"Rejected: {short}"}])
    if res.get("errors"):
        raise ValueError("; ".join(res["errors"]))
    seen = lj.load_seen()  # set_statuses/tidy write seen.json, so read it again before changing it
    v = _record(seen, jid)
    ev = list(events_of(v))
    ev.append(event_clean({"date": r["date"], "type": "No response" if silence else "Rejected", "result": "Failed",
                           "notes": r["stated"] or r["cause"]}))
    v["events"] = _sorted(ev)
    v["rejection"] = {**r, "step": step_before}
    sync_funnel(v)
    lj.save_seen(seen)
    return f"Rejection recorded for {jid} (ended after: {step_before})."


def update_rejection(jid, fields):
    """Correct the cause, detail or fix of a rejection already on file (for example after the recruiter explains)."""
    seen = lj.load_seen()
    v = _record(seen, jid)
    if not v.get("rejection"):
        raise ValueError("No rejection recorded for this job yet.")
    old = v["rejection"]
    r = rejection_clean({**old, **fields})
    v["rejection"] = {**old, **r}
    v["rejection"].pop("backfilled", None)
    lj.save_seen(seen)
    return f"Rejection details updated for {jid}."


def resume_of(v):
    """Which resume went out: set on the Applied event, else the tailored docx in the prepared application folder."""
    for e in events_of(v):
        if e["type"] == "Applied" and e.get("resume"):
            return e["resume"]
    folder = v.get("prepared")
    if folder and os.path.isdir(folder):
        docs = sorted((f for f in os.listdir(folder) if re.search(r"resume.*\.docx$", f, re.I) and not re.search(r"cover", f, re.I)), key=lambda f: -os.path.getmtime(os.path.join(folder, f)))
        if docs:
            return docs[0][:-5]
    return ""


def last_activity(v):
    dates = [e["date"] for e in events_of(v) if e.get("date")] or [(v.get("funnel") or {}).get("applied_date", "")]
    return max([d for d in dates if d], default="")


def silent_days(v, group):
    """Days of silence on an Applied row that never got past the application (None if it isn't in that state)."""
    if group != "Applied" or furthest(events_of(v)) > 0 or v.get("rejection"):
        return None
    last = last_activity(v)
    if not last:
        return None
    d = (date.today() - date.fromisoformat(last)).days
    return d if d >= SILENT_DAYS else None


def row_info(v, group):
    """What the dashboard needs per row."""
    return {"events": events_of(v), "events_synth": "events" not in v, "rejection": v.get("rejection"),
            "resume": resume_of(v), "silent": silent_days(v, group)}


# ---------------------------------------------------------------- Phase 2: why aren't we getting through?
# Requirement vocabulary: (label, regex). Matched in each posting's text and in the master resume to find what recurs and what's missing.
VOCAB = [
    ("Spanish / other language", r"\b(spanish|french|german|japanese|portuguese|mandarin|bilingual)\b"),
    ("Service mesh / Istio / Envoy", r"\b(istio|envoy|service mesh|linkerd|cilium)\b"),
    ("API gateway", r"\bapi gateways?\b"),
    ("Artifactory / artifact repos", r"\b(artifactory|nexus|artifact repositor)"),
    ("Git / GitHub / GitLab", r"\b(git|github|gitlab)\b"),
    ("Docker", r"\bdocker\b"),
    ("Terraform / IaC", r"\b(terraform|opentofu|pulumi|infrastructure as code|iac)\b"),
    ("Python / Go / scripting", r"\b(python|golang|bash scripting|scripting)\b"),
    ("On-call / SRE operations", r"\b(on-call|on call|incident response|site reliability|sre)\b"),
    ("Security / compliance", r"\b(security|compliance|soc 2|fedramp|zero trust)\b"),
    ("Observability tooling", r"\b(observability|prometheus|grafana|datadog|opentelemetry)\b"),
    ("Data / ML tooling", r"\b(spark|kafka|snowflake|databricks|mlops|machine learning)\b"),
    ("Post-sales / customer success", r"\b(post-sales|post sales|customer success|adoption|renewal)\b"),
    ("MEDDPICC / sales methodology", r"\b(meddpicc|meddicc|challenger|sandler)\b"),
    ("RFP / RFI responses", r"\b(rfps?|rfis?)\b"),
    ("Hands-on production ownership", r"\b(hands-on|production environments?|operate|operating)\b"),
    ("Years of experience (10+)", r"\b(10\+|12\+|15\+|ten|twelve) years\b"),
    ("Industry vertical depth", r"\b(financial services|healthcare|public sector|federal|telecom|retail)\b"),
]
_resume_cache = {}


def resume_text():
    """Text of the master resume (empty if it can't be read)."""
    try:
        path = settings.resume_master()
        mt = os.path.getmtime(path)
        if _resume_cache.get("k") != (path, mt):
            x = zipfile.ZipFile(path).read("word/document.xml").decode("utf8", "ignore")
            _resume_cache.update(k=(path, mt), t=re.sub(r"<[^>]+>", " ", re.sub(r"</w:p>", "\n", x)).lower())
        return _resume_cache["t"]
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return ""


def jd_text(jid):
    try:
        return open(os.path.join(lj.JD_DIR, f"{jid}.md")).read().lower()
    except OSError:
        return ""


def _terms(text):
    return {label for label, rx in VOCAB if re.search(rx, text, re.I)}


def facts(rows, seen):
    """One dict per application that got out the door (or was handed to you by a recruiter)."""
    by_id = {v["id"]: v for v in seen.values() if v.get("id")}
    out = []
    for r in rows:
        v = by_id.get(r["id"])
        if not v:
            continue
        ev = events_of(v)
        grp = r["status_group"]
        if not (v.get("rejection") or grp in ("Applied", "Interviewing", "Rejected")):
            continue  # Pass / Covered / Closed rows with no rejection record never reached a company decision
        fi = furthest(ev)
        if grp == "Interviewing":
            fi = max(fi, 1)  # an Interviewing row has had at least a conversation, even if no event is logged yet
        rej = v.get("rejection")
        offer = any(e["type"] == "Offer" for e in ev)
        sd = silent_days(v, grp)
        outcome = ("Offer" if offer else "Rejected" if rej and rej["cause"] != "No response (silence)" else "Silent" if (rej or sd) and fi <= 0
                   else "In process" if grp == "Interviewing" or fi > 0 else "Waiting")
        out.append({"id": r["id"], "company": r["company"], "role": r["role"], "tier": r.get("tier", ""), "angle": r.get("angle", ""),
                    "level": (v.get("funnel") or {}).get("level_fit", ""), "source": (r.get("funnel") or {}).get("source", ""),
                    "resume": resume_of(v) or "Not recorded", "reached": max(fi, 0), "outcome": outcome, "cause": (rej or {}).get("cause", ""),
                    "stated": (rej or {}).get("stated", ""), "detail": (rej or {}).get("detail", ""), "fix": (rej or {}).get("fix", ""),
                    "gaps": r.get("gaps", ""), "silent_days": sd, "events": len(ev)})
    return out


def analysis(rows, seen):
    fs = facts(rows, seen)
    n = len(fs)
    resume = resume_text()
    pct = lambda a, b: round(100 * a / b) if b else 0
    reached = [{"name": b, "n": sum(f["reached"] >= i for f in fs)} for i, b in enumerate(BUCKETS)]
    endings = {}
    for f in fs:
        if f["outcome"] in ("Rejected", "Silent"):
            endings.setdefault(BUCKETS[f["reached"]], {"Rejected": 0, "Silent": 0})[f["outcome"]] += 1

    def seg(key, label):
        groups = {}
        for f in fs:
            if f[key]:
                groups.setdefault(f[key], []).append(f)
        rows_ = [{"name": k, "n": len(v), "screen": sum(x["reached"] >= 1 for x in v), "hm": sum(x["reached"] >= 2 for x in v), "small": len(v) < MIN_SAMPLE}
                 for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
        return {"title": label, "rows": rows_} if len(rows_) > 1 else None

    segments = [s for s in (seg("tier", "By tier"), seg("angle", "By angle"), seg("level", "By level fit"), seg("source", "By source"),
                            seg("resume", "By resume version")) if s]
    causes = {}
    for f in fs:
        if f["cause"]:
            causes[f["cause"]] = causes.get(f["cause"], 0) + 1
    # what postings ask for vs what the master resume shows, split by whether the application moved
    tally = {}
    for f in fs:
        jd = _terms(jd_text(f["id"]))
        have = _terms(resume) if resume else set()
        moved = f["reached"] >= 1
        gap_terms = _terms(f["gaps"])
        for t in jd:
            d = tally.setdefault(t, {"term": t, "rows": 0, "moved": 0, "missing_on_resume": t not in have if resume else None, "in_gaps": 0})
            d["rows"] += 1
            d["moved"] += moved
        for t in gap_terms:
            tally.setdefault(t, {"term": t, "rows": 0, "moved": 0, "missing_on_resume": t not in _terms(resume) if resume else None, "in_gaps": 0})["in_gaps"] += 1
    gaps = sorted((d for d in tally.values() if d["rows"] >= 3 or d["in_gaps"] >= 2), key=lambda d: (-(d["missing_on_resume"] is True), -d["rows"]))[:12]
    for d in gaps:
        d["moved_pct"] = pct(d["moved"], d["rows"])
    out = {"n": n, "reached": reached, "endings": endings, "segments": segments, "causes": [{"name": k, "n": v} for k, v in sorted(causes.items(), key=lambda kv: -kv[1])],
           "gaps": gaps, "outcomes": {k: sum(f["outcome"] == k for f in fs) for k in ("Waiting", "In process", "Rejected", "Silent", "Offer")},
           "rejections": [{k: f[k] for k in ("id", "company", "role", "cause", "stated", "detail", "fix")} | {"step": BUCKETS[f["reached"]]}
                          for f in fs if f["outcome"] == "Rejected"]}
    out["insights"] = insights(fs, out, pct)
    return out


def insights(fs, a, pct):
    """Plain-language findings with a concrete next step each. Rules, not a model: cheap and repeatable."""
    ins = []
    n = a["n"]
    if n < MIN_SAMPLE:
        return [{"title": "Not enough data yet", "detail": f"{n} application{'s' if n != 1 else ''} have a journey recorded.",
                 "action": "Log events and rejections as they happen; patterns appear at 5+."}]
    screen = a["reached"][1]["n"]
    out_n = a["outcomes"]
    sent = sum(1 for f in fs if f["events"] or f["outcome"] != "Waiting")
    if pct(screen, n) < 25:
        ins.append({"title": f"Only {pct(screen, n)}% of applications reach a first conversation ({screen} of {n})",
                    "detail": "Most end at the resume screen, before anyone talks to you. That points to how the resume reads against the posting, not to interviewing.",
                    "action": "Tailor the top third of the resume to each posting's first five requirements, and compare resume versions in the table below once more are recorded."})
    sil = out_n["Silent"]
    if sil >= 3 and pct(sil, n) >= 25:
        ins.append({"title": f"{sil} applications ({pct(sil, n)}%) got no reply at all",
                    "detail": "Silence is not a rejection reason; it usually means the resume never reached a person.",
                    "action": "Apply within 3 days of posting and use 'Find intros' for a referral or hiring manager before applying cold."})
    missing = [g for g in a["gaps"] if g["missing_on_resume"] and g["rows"] >= 3]
    if missing:
        g = missing[0]
        ins.append({"title": f"'{g['term']}' shows up in {g['rows']} postings you applied to and isn't on the resume",
                    "detail": f"{g['moved_pct']}% of those applications reached a conversation. Others missing: " + (", ".join(x["term"] for x in missing[1:4]) or "none"),
                    "action": "If you have real experience, add it with a number. If you don't, decide whether to build it (a small project) or stop applying where it is required."})
    stronger = [r for r in a["rejections"] if r["cause"] == "Competing candidate (stronger match)"]
    late = [r for r in a["rejections"] if r["step"] in ("Hiring manager", "Technical", "Panel / Exec")]
    if late:
        names = ", ".join(f"{r['company']}" for r in late[:4])
        ins.append({"title": f"{len(late)} rejection{'s' if len(late) != 1 else ''} came after a real conversation ({names})",
                    "detail": "These are the most valuable data points: you passed the resume screen, so the gap is in how the fit was judged, not in getting noticed."
                              + (f" {len(stronger)} were told 'a stronger match', which is a polite non-answer." if stronger else ""),
                    "action": "Ask the recruiter one specific question: 'Which requirement was the gap?' Record the answer in the rejection's detail field, and write a debrief for every call."})
    for key, label in (("level", "level fit"), ("source", "source")):
        s = next((x for x in a["segments"] if x["title"] == f"By {label}"), None)
        if s:
            ok = [r for r in s["rows"] if not r["small"]]
            if len(ok) >= 2:
                best = max(ok, key=lambda r: r["screen"] / r["n"])
                worst = min(ok, key=lambda r: r["screen"] / r["n"])
                if best["screen"] / best["n"] - worst["screen"] / worst["n"] >= 0.2:
                    ins.append({"title": f"{label.capitalize()} matters: {best['name']} converts {pct(best['screen'], best['n'])}% vs {worst['name']} {pct(worst['screen'], worst['n'])}%",
                                "detail": f"{best['n']} vs {worst['n']} applications.", "action": f"Weight your effort toward '{best['name']}'."})
    if not ins:
        ins.append({"title": "No clear pattern yet", "detail": f"{n} applications tracked; nothing stands out.", "action": "Keep logging events and rejection reasons."})
    return ins


def _guess_cause(text):
    t = text.lower()
    if re.search(r"no answer|no response|ghost|never heard", t):
        return "No response (silence)"
    if re.search(r"rto|return to office|relocat|on-?site|territory|location", t):
        return "Location / territory / RTO"
    if re.search(r"another candidate|other candidates|others? (that )?match|better match|stronger match|closely align|more closely", t):
        return "Competing candidate (stronger match)"
    if re.search(r"frozen|filled|cancel|no longer (hiring|available)|position (has been )?closed", t):
        return "Role frozen, filled or changed"
    if re.search(r"salary|compensation|comp\b|budget", t):
        return "Compensation"
    return "Unknown / generic"


def backfill_rejections():
    """Rows already marked 'Rejected: <reason>' before this feature get a rejection record built from that text, flagged
    'backfilled' so you can correct the cause. Re-running skips rows that already have one."""
    seen = lj.load_seen()
    n = 0
    for v in seen.values():
        if not v.get("id") or v.get("rejection"):
            continue
        h = v.get("history") or []
        if not h or lj_group(h[-1][1]) != "Rejected":
            continue
        text = h[-1][1].split(":", 1)[1].strip() if ":" in h[-1][1] else ""
        cause = _guess_cause(text)
        silence = cause == "No response (silence)"
        ev = list(events_of(v))
        step = BUCKETS[max(furthest(ev), 0)]
        ev.append({"date": h[-1][0], "type": "No response" if silence else "Rejected", "result": "Failed", **({"notes": text[:400]} if text else {})})
        v["events"] = _sorted(ev)
        v["rejection"] = {"date": h[-1][0], "how": "Silence (no reply)" if silence else "Email", "stated": text[:600], "cause": cause, "detail": "", "fix": "",
                          "step": step, "backfilled": True}
        sync_funnel(v)
        n += 1
    lj.save_seen(seen)
    return f"Built rejection records for {n} rows already marked Rejected (cause guessed from the reason text; correct any that are wrong)."


def lj_group(status):
    return lj.statuses.group(status)


def migrate():
    """Seed events (and the sent-resume name) from the older funnel fields. Re-running changes nothing."""
    seen = lj.load_seen()
    n = 0
    for v in seen.values():
        if v.get("id") and "events" not in v and (v.get("funnel") or {}).get("stage"):
            v["events"] = _sorted(synth_events(v))
            n += 1
    lj.save_seen(seen)
    return f"Seeded events for {n} applications."


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--migrate", action="store_true")
    g.add_argument("--analysis", action="store_true")
    g.add_argument("--backfill", action="store_true", help="build rejection records for rows already marked Rejected")
    a = ap.parse_args()
    if a.migrate:
        print(migrate())
    elif a.backfill:
        print(backfill_rejections())
    elif a.backfill:
        print(backfill_rejections())
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import dashboard
        print(json.dumps(dashboard.load_jobs()["why_not"], indent=1))


if __name__ == "__main__":
    main()
