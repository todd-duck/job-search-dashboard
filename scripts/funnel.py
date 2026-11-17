#!/usr/bin/env python3
"""Where do jobs disappear? Reads data/funnel.jsonl and the rejected table in data/jobsearch.db (written by fetch_jobs.py).

Usage:
  funnel.py             funnel by run + unique rejections by reason + near-miss titles
  funnel.py --titles N  show the top N near-miss titles per reason (default 25)
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Titles that look like customer-facing technical roles even though a filter rejected them.
NEAR = re.compile(r"solution|sales eng|customer (success|eng|arch)|technical (account|success|solution|specialist)|"
                  r"pre-?sales|field (eng|cto)|forward.deployed|architect|consultant|enablement|specialist|partner eng|"
                  r"value (eng|consult)|\bse\b|\bsa\b|\btam\b", re.I)
POST = re.compile(r"customer success|technical account|\btam\b|customer eng|support eng|technical success", re.I)


def load(name, default):
    try:
        return json.load(open(os.path.join(DATA, name)))
    except (OSError, ValueError):
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--titles", type=int, default=25)
    a = ap.parse_args()

    runs = [json.loads(l) for l in open(os.path.join(DATA, "funnel.jsonl"))] if os.path.exists(os.path.join(DATA, "funnel.jsonl")) else []
    print("== Funnel by run (fetched -> candidates; top drop reasons) ==")
    for r in runs[-10:]:
        top = ", ".join(f"{k} {v}" for k, v in sorted(r["dropped"].items(), key=lambda x: -x[1])[:4])
        print(f"{r['ts'][:16]}  {r['fetched']:>6} -> {r['candidates']:>3}   failed sources {r['failed_sources']}   {top}")
    if not runs:
        print("(no runs recorded yet; the next search records one)")

    rows = store.rejected(DATA)
    if not rows:
        return
    print(f"\n== Unique rejected postings on file: {len(rows)} ==")
    by = collections.Counter(v["reason"] for v in rows)
    for k, n in by.most_common():
        print(f"{n:>6}  {k}")

    for reason in ("title", "title skip word"):
        rows = [v for v in rows if v["reason"] == reason and NEAR.search(v["title"])]
        pre = [v for v in rows if not POST.search(v["title"])]
        post = [v for v in rows if POST.search(v["title"])]
        print(f"\n== '{reason}' rejections that still look customer-facing: {len(rows)} (pre-sales-ish {len(pre)}, post-sales-ish {len(post)}) ==")
        c = collections.Counter(v["title"].strip() for v in rows)
        for t, n in c.most_common(a.titles):
            cos = sorted({v["company"] for v in rows if v["title"].strip() == t})
            print(f"{n:>4}  {t[:70]}  [{', '.join(cos[:3])}{'...' if len(cos) > 3 else ''}]")

    loc = [v for v in rows if v["reason"].startswith("location") and re.search(r"solutions? (eng|arch)|sales eng|customer success|technical account", v["title"], re.I)]
    print(f"\n== In-scope titles dropped for location: {len(loc)} ==")
    for v in sorted(loc, key=lambda v: v["company"])[:a.titles]:
        print(f"  {v['company'][:22]:22} {v['title'][:50]:50} {v['location'][:30]}")

    sal = [v for v in rows if v["reason"] == "salary below floor"]
    print(f"\n== Dropped for salary below floor: {len(sal)} ==")
    for v in sal[:a.titles]:
        print(f"  {v['company'][:22]:22} {v['title'][:60]}")


if __name__ == "__main__":
    main()
