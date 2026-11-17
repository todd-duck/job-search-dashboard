"""Build the pool of real postings the judge-facts eval draws from.

Two sources, no model calls:
  1. data/jd/*.md          postings that survived the filters (saved when they were logged)
  2. a re-fetch of the boards behind judgments.json URLs we have no text for (these include the
     postings the judge DROPPED, which is where the rare positives live)

Output: evals/judge_facts/pool.json  {url: {job fields..., "cached": <Sonnet facts, used for sampling only>}}
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fetch_jobs as fj  # noqa: E402


def from_jd_files():
    out = {}
    for p in glob.glob(os.path.join(ROOT, "data", "jd", "*.md")):
        t = open(p, encoding="utf-8").read()
        m = re.match(r"# (.+?) — (.+?)\n\n(https?://\S+)\n\nLocation: (.*?)\s*\nSalary: (.*?)\s*\nPosted: (.*?)\s*\n\n(.*)", t, re.S)
        if not m:
            continue
        company, title, url, loc, sal, posted, desc = m.groups()
        out[url] = {"company": company, "title": title, "url": url, "location": loc,
                    "salary": "" if sal.lower() in ("not stated", "unknown", "") else sal,
                    "posted_at": None if posted == "unknown" else posted, "description": desc.strip(),
                    "remote": "remote" in loc.lower(), "source": "jdfile", "origin": "jd-file"}
    return out


def refetch(missing, cfg):
    blob = " ".join(missing).lower()
    tasks = []
    for label, fn, arg in fj.plan_sources(cfg):
        tenant = str(arg).split("/")[0].split(".")[0].lower()
        if len(tenant) > 2 and tenant in blob:
            tasks.append((label, fn, arg))
    print(f"re-fetching {len(tasks)} boards", file=sys.stderr)
    results, failures = fj.run(tasks, workers=6)
    found = {}
    for label, jobs in results.items():
        for j in jobs:
            if j.get("url") in missing:
                found[j["url"]] = {**j, "origin": "refetched"}
    print(f"re-fetched {len(found)}/{len(missing)}; board failures: {failures}", file=sys.stderr)
    return found


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    cached = json.load(open(os.path.join(ROOT, "data", "judgments.json")))
    pool = from_jd_files()
    missing = {u for u in cached if u not in pool}
    pool.update(refetch(missing, cfg))
    for u, j in pool.items():
        j["cached"] = (cached.get(u) or {}).get("facts")
    pool = {u: j for u, j in pool.items() if j.get("cached")}
    json.dump(pool, open(os.path.join(HERE, "pool.json"), "w"), indent=1, ensure_ascii=False)
    print(f"pool: {len(pool)} postings with text and a cached judgment")


if __name__ == "__main__":
    main()
