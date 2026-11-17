"""Posting-legitimacy signals: is this job likely a live hire, or an old / pipeline / reposted listing?

Flags, never hard-drops (the 90-day feed cutoff in config already removes the oldest). Age is measured from the first time we
or the feed saw the posting, so a repost does not reset the clock. Penalties feed the score in run_cycle.py.
"""
import re
from datetime import date

AGING_DAYS, STALE_DAYS = 30, 60          # 31-60 days = aging (-1); 61+ = stale (-2)
DUP_FLAG_AT = 3                          # same company + title open this many times -> flag (no penalty)
PIPELINE_RE = re.compile(
    r"talent (?:pool|community|network)|future (?:opportunit|opening|role|position)|always (?:hiring|looking)|"
    r"continuous(?:ly)? (?:hiring|recruit)|pipeline (?:of|for) (?:candidates|future)|evergreen|general application|"
    r"not (?:currently )?(?:hiring|open) for a specific", re.I)


def norm_title(t):
    return re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower().split(" - ")[0].split(",")[0]).strip()


def _days(iso, today):
    try:
        return (today - date.fromisoformat(iso[:10])).days
    except Exception:
        return None


def assess(j, cands, seen, today=None):
    """Returns {"adjust": int, "age": int|None, "label": fresh|aging|stale|unknown, "flags": [str], "note": str}."""
    today = today or date.today()
    flags, adjust = [], 0
    ages = [a for a in (_days(j.get("posted_at") or "", today),) if a is not None]
    # repost: same company + title + location seen earlier under a different URL
    key = (j["company"].lower(), norm_title(j["title"]), (j.get("location") or "").lower())
    firsts = [v["first_seen"] for u, v in (seen or {}).items()
              if u != j["url"] and (v.get("company", "").lower(), norm_title(v.get("title", "")), (v.get("location") or "").lower()) == key
              and v.get("location") and v.get("first_seen")]  # entries logged before locations were stored are ignored
    if firsts:
        d = _days(min(firsts), today)
        if d is not None and d > 0:
            ages.append(d)
            flags.append(f"reposted (earlier listing first seen {min(firsts)})")
    age = max(ages) if ages else None
    label = "unknown" if age is None else "fresh" if age <= AGING_DAYS else "aging" if age <= STALE_DAYS else "stale"
    adjust += {"aging": -1, "stale": -2}.get(label, 0)
    if PIPELINE_RE.search(j.get("description") or ""):
        flags.append("pipeline/evergreen language"); adjust -= 1
    nk = (j["company"].lower(), norm_title(j["title"]))
    dups = sum(1 for c in cands if (c["company"].lower(), norm_title(c["title"])) == nk)
    if dups >= DUP_FLAG_AT:
        flags.append(f"{dups} open reqs with this title (rolling hire or pipeline posting)")
    bits = [f"Legitimacy: {label}" + (f" ({age}d old)" if age is not None else "")] + flags
    return {"adjust": adjust, "age": age, "label": label, "flags": flags,
            "note": "; ".join(bits) if (label in ("aging", "stale") or flags) else ""}
