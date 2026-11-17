"""Step 1 of the judge-facts eval: pick real postings and rebuild the candidate dicts the judge sees.

Sampling is stratified on Sonnet's CACHED facts, but only to make sure rare cases are present. The cached
facts are never used as gold (that would only measure whether the model agrees with itself).

Output: evals/judge_facts/cases_real.json
"""
import copy
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import fetch_jobs as fj  # noqa: E402
import run_cycle as rc  # noqa: E402

N_REAL = 40
# (label, predicate on cached facts, how many to take). Rare things first so they are not crowded out.
QUOTAS = [
    ("clearance", lambda f: f["clearance_required"], 2),
    ("pure-ml", lambda f: f["pure_ml_or_backend"], 2),
    ("residency", lambda f: bool(f["residency_restriction"]), 3),
    ("onsite", lambda f: f["onsite_or_relocation_elsewhere"], 5),
    ("specialist", lambda f: bool(f["specialist_requirement"]), 5),
    ("post-sales", lambda f: f["post_sales"], 4),
    ("core-none", lambda f: f["core_match"] == "none", 3),
    ("core-infra", lambda f: f["core_match"] == "infra", 3),
    ("core-strong", lambda f: f["core_match"] == "strong", 9),
    ("core-partial", lambda f: f["core_match"] == "partial", 8),
]


def enrich(job, cfg):
    """Run the real prefilter on one job with every drop rule relaxed, so we get its derived fields
    (strong_hits, territory, salary_parsed, prescore...) exactly as production computes them."""
    c = copy.deepcopy(cfg)
    t = c["targeting"]
    # words_re([]) matches everything, so "off" means a token that cannot occur; the must-match is the title's first word
    t.update(title_skip=["zzz-never-matches"], excluded_companies=[], k8s_only_companies=[], staffing_agencies=[],
             title_must_match_one=[re.match(r"\w+", job["title"]).group(0)], salary_floor=0, ote_floor=0)
    j = copy.deepcopy(job)
    j.setdefault("remote", "remote" in (j.get("location") or "").lower())
    j["source"] = j["source"] if j.get("source") in fj.ATS_SOURCES else "greenhouse"
    j["posted_at"] = None
    j.pop("cached", None)
    j.pop("origin", None)
    kept, reasons, _ = fj.prefilter([j], c, 99999)
    return (kept[0] if kept else None), reasons


def main():
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    fj.load_seen = lambda cfg: (set(), set())  # "already seen" must not hide eval postings
    pool = json.load(open(os.path.join(HERE, "pool.json")))
    rng = random.Random(7)
    urls = sorted(pool)
    rng.shuffle(urls)
    chosen, tags = [], {}
    for label, pred, n in QUOTAS:
        got = [u for u in urls if pred(pool[u]["cached"]) and u not in tags][:n]
        for u in got:
            tags[u] = label
            chosen.append(u)
    # top up to N_REAL with anything not yet chosen
    for u in urls:
        if len(chosen) >= N_REAL:
            break
        if u not in tags:
            tags[u] = "filler"
            chosen.append(u)
    chosen = chosen[:N_REAL]

    cases, dropped = [], []
    for u in chosen:
        cand, reasons = enrich(pool[u], cfg)
        if cand is None:
            dropped.append((u, reasons))
            continue
        cases.append({"id": f"r{len(cases) + 1:02d}", "url": u, "kind": "real", "sample_bucket": tags[u],
                      "origin": pool[u]["origin"], "candidate": cand, "digest": rc.digest(0, cand),
                      "sonnet_cached": pool[u]["cached"]})
    json.dump(cases, open(os.path.join(HERE, "cases_real.json"), "w"), indent=1, ensure_ascii=False, default=str)
    print(f"{len(cases)} real cases built; {len(dropped)} dropped by prefilter: {dropped}")
    from collections import Counter
    print(Counter(c["sample_bucket"] for c in cases))


if __name__ == "__main__":
    main()
