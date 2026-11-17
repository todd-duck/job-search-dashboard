#!/usr/bin/env python3
"""Per-step time and token/cost logging for the job-search pipeline.

Library use (from the other scripts):
  from metrics import step, record_llm
  with step("fetch", sources=94):          # appends {step, seconds, ...} to data/metrics.jsonl
      ...
  record_llm("judge", usage, cost_usd, model)   # tokens + dollars for one model call

CLI:
  metrics.py --report [--runs N]    per-run table: seconds and tokens/$ by step (default last 5 runs)
  metrics.py --baseline             estimate what ONE interactive /job-search run reads (the old design)
"""
import argparse
import json
import os
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "metrics.jsonl")
RUN_ID = os.environ.get("JOBSEARCH_RUN_ID") or datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def _write(rec):
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run": RUN_ID, **rec}
    try:
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        with open(PATH, "a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # metrics must never break a run


@contextmanager
def step(name, **meta):
    t = time.monotonic()
    try:
        yield
    finally:
        _write({"step": name, "seconds": round(time.monotonic() - t, 2), **meta})


def record_llm(name, usage, cost_usd, model, seconds=None, **meta):
    usage = usage or {}
    _write({"step": name, "llm": True, "model": model, "seconds": seconds,
            "input_tokens": usage.get("input_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cost_usd": round(cost_usd or 0, 4), **meta})


def est_tokens(chars):
    return int(chars / 4)  # rough rule of thumb for English text


def report(n_runs):
    if not os.path.exists(PATH):
        print("No metrics yet (data/metrics.jsonl).")
        return
    runs = {}
    for line in open(PATH):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        runs.setdefault(r["run"], []).append(r)
    for rid in list(runs)[-n_runs:]:
        recs = runs[rid]
        print(f"\nRun {rid}")
        print(f"  {'step':<22}{'sec':>8}{'in tok':>9}{'cache':>9}{'out tok':>9}{'$':>8}")
        wrap = next((r["seconds"] for r in recs if r["step"] == "cycle_total"), None)
        tot_s = tot_c = 0
        for r in recs:
            s = r.get("seconds") or 0
            if not r["step"].endswith("_total"):
                tot_s += s
            tot_c += r.get("cost_usd", 0)
            tag = f"{r['step']}{' (' + r['model'].split('-')[1] + ')' if r.get('model') else ''}"
            print(f"  {tag:<22}{s:>8.1f}{(r.get('input_tokens', 0) + r.get('cache_write_tokens', 0)) if r.get('llm') else '':>9}{r.get('cache_read_tokens', '') if r.get('llm') else '':>9}"
                  f"{r.get('output_tokens', ''):>9}{r.get('cost_usd', ''):>8}")
        print(f"  {'TOTAL (wall)':<22}{(wrap if wrap is not None else tot_s):>8.1f}{'':>9}{'':>9}{'':>9}{tot_c:>8.4f}")


def baseline():
    """What the old interactive skill had to READ per run, from the files on disk (chars/4)."""
    def size(rel):
        p = os.path.join(ROOT, rel)
        return os.path.getsize(p) if os.path.exists(p) else 0

    cand = os.path.join(ROOT, "data", "candidates.json")
    descs = tokens_cand = 0
    if os.path.exists(cand):
        c = json.load(open(cand))["candidates"]
        descs = sum(len(j.get("description", "")) for j in c)
        tokens_cand = est_tokens(len(json.dumps(c)))
    rows = [("SKILL.md (old, 110 lines)", est_tokens(size(".claude/skills/job-search/SKILL.md"))),
            ("search-instructions.md", est_tokens(size("search-instructions.md"))),
            ("jobs.md (decisions/tidy)", est_tokens(size("jobs.md"))),
            ("candidates.json (all fields)", tokens_cand),
            ("  of which description text", est_tokens(descs))]
    print("Estimated input tokens one interactive run must read (before any tool output or reasoning):")
    for k, v in rows:
        print(f"  {k:<32}{v:>9,}")
    total = sum(v for k, v in rows if not k.startswith("  "))
    print(f"  {'SUBTOTAL':<32}{total:>9,}")
    print("  + watch-list WebFetches, 8 web searches, scoring output, and every later turn re-reading all of it.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--baseline", action="store_true")
    a = ap.parse_args()
    if a.baseline:
        baseline()
    else:
        report(a.runs)
    sys.exit(0)
