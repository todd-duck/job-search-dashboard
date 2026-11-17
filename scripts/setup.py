#!/usr/bin/env python3
"""Setup helper used by the job-search-setup skill (and runnable by hand).

  python3 scripts/setup.py --status          what is configured and what is missing
  python3 scripts/setup.py --apply FILE      merge the interview answers (JSON) into config.json + search-instructions.md
  python3 scripts/setup.py --doctor          check the machine: Python, Claude CLI, LibreOffice, folders, resume
  python3 scripts/setup.py --support-bundle  print a redacted diagnostic you can paste into a GitHub issue

Nothing here talks to the network, and nothing leaves your machine unless you paste it somewhere yourself."""
import argparse
import copy
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import settings  # noqa: E402

ROOT = settings.ROOT
DONE = os.path.join(ROOT, "data", ".setup_done")
INSTR = os.path.join(ROOT, "search-instructions.md")
INSTR_EXAMPLE = os.path.join(ROOT, "search-instructions.example.md")


def deep_merge(base, over):
    """over wins; dicts merge recursively; lists and scalars are replaced; keys starting with _ in over are ignored."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if k.startswith("_"):
            continue
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def problems(c):
    """Things that would make the search useless or confusing. Returns (errors, warnings)."""
    err, warn = [], []
    pr, t = c.get("profile", {}), c.get("targeting", {})
    if pr.get("full_name") in (None, "", "Alex Morgan", "the candidate"):
        err.append("profile.full_name is still the example (Alex Morgan) or empty")
    if not t.get("title_must_match_one"):
        err.append("targeting.title_must_match_one is empty: no job title could ever match")
    if not (c.get("sources", {}).get("ats") and any(c["sources"]["ats"].values())) and not c.get("web_queries"):
        err.append("no sources: add company job boards under sources.ats or some web_queries")
    if not t.get("domain_strong"):
        warn.append("targeting.domain_strong is empty: scoring will not reward any theme")
    master = os.path.expanduser(pr.get("resume_master", ""))
    if not master:
        warn.append("profile.resume_master is empty: application prep cannot tailor a resume")
    elif not os.path.exists(master):
        warn.append(f"profile.resume_master does not exist: {master}")
    if not t.get("home_metro_terms") and not pr.get("home_city"):
        warn.append("no home area set: only remote roles will count as a location match")
    if t.get("salary_floor", 0) <= 0:
        warn.append("salary_floor is 0: no posting will be dropped for pay")
    return err, warn


def write_profile_section(markdown):
    """Replace the '## Candidate profile' section of search-instructions.md with the interview's version."""
    src = INSTR if os.path.exists(INSTR) else INSTR_EXAMPLE
    text = open(src).read()
    m = re.search(r"(## Candidate profile\n)(.*?)(\n## Hard rules)", text, re.S)
    if not m:
        raise ValueError(f"{os.path.basename(src)} has no '## Candidate profile' section to replace")
    new = text[:m.start(2)] + markdown.strip() + "\n" + text[m.end(2):]
    new = re.sub(r"\n> This is a fictional example.*?\n", "\n", new)
    new = re.sub(r"\n{3,}", "\n\n", new)
    new = re.sub(r"^# Job Search: .*$", "# Job Search", new, count=1, flags=re.M)
    open(INSTR, "w").write(new)


def apply(path):
    answers = json.load(open(path))
    base = json.load(open(settings.PATH)) if os.path.exists(settings.PATH) else json.load(open(settings.EXAMPLE))
    md = answers.pop("profile_markdown", "")
    if answers.get("sources", {}).get("ats"):  # the user's boards replace the example's, they are not added to them
        base["sources"]["ats"] = {k: {} for k in base["sources"]["ats"]}
    if "companies" in answers.get("sources", {}).get("watch_no_api", {}):
        base["sources"]["watch_no_api"]["companies"] = {}
    merged = deep_merge(base, answers)
    err, warn = problems(merged)
    if err:
        print("Not written. Fix these first:\n  - " + "\n  - ".join(err))
        return 1
    if os.path.exists(settings.PATH):  # never lose an earlier config
        os.makedirs(os.path.join(ROOT, "data", "backups"), exist_ok=True)
        shutil.copyfile(settings.PATH, os.path.join(ROOT, "data", "backups", f"config.json.{int(time.time())}.bak"))
    json.dump(merged, open(settings.PATH, "w"), indent=2)
    if md:
        write_profile_section(md)
    elif not os.path.exists(INSTR):
        shutil.copyfile(INSTR_EXAMPLE, INSTR)
    for d in (os.path.expanduser(merged["profile"].get("applications_dir", "")),):
        if d:
            os.makedirs(d, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    open(DONE, "w").write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    print("Wrote config.json" + (" and the profile in search-instructions.md" if md else "") + ". Setup marked done.")
    for w in warn:
        print("  note:", w)
    return 0


def status():
    c = settings.load()
    done = os.path.exists(DONE)
    print("setup done:", "yes" if done else "NO (run the job-search-setup skill)")
    print("config.json:", "present" if os.path.exists(settings.PATH) else "missing (the shipped example is in use)")
    print("search-instructions.md:", "present" if os.path.exists(INSTR) else "missing")
    err, warn = problems(c)
    for e in err:
        print("  must fix:", e)
    for w in warn:
        print("  note:", w)
    n = sum(len(v) for v in c.get("sources", {}).get("ats", {}).values())
    print(f"company boards: {n}; web queries: {len(c.get('web_queries', []))}; title terms: {len(c.get('targeting', {}).get('title_must_match_one', []))}")
    return 0 if done and not err else 1


def doctor():
    ok = True

    def line(good, what, fix=""):
        nonlocal ok
        ok &= good or not fix.startswith("REQUIRED")
        print(("  ok   " if good else "  FIX  ") + what + (f"\n         {fix.replace('REQUIRED: ', '')}" if not good and fix else ""))
    v = sys.version_info
    line(v >= (3, 10), f"Python {v.major}.{v.minor}", "REQUIRED: install Python 3.10 or newer (https://www.python.org/downloads/)")
    claude = shutil.which("claude")
    line(bool(claude), "Claude Code CLI (claude)", "REQUIRED: install Claude Code (https://claude.com/claude-code) and run `claude` once to log in")
    if claude:
        try:
            out = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=20).stdout.strip()
            line(True, f"claude --version -> {out}")
        except (OSError, subprocess.TimeoutExpired):
            line(False, "claude --version did not answer", "REQUIRED: run `claude` in a terminal and finish logging in")
    line(bool(shutil.which("soffice")), "LibreOffice (soffice), used to export resume PDFs",
         "optional: install LibreOffice (macOS: brew install --cask libreoffice). Without it you get .docx files but no PDFs")
    line(os.path.exists(settings.PATH), "config.json exists", "REQUIRED: run the setup interview: open Claude Code here and type /job-search-setup")
    c = settings.load()
    err, warn = problems(c) if os.path.exists(settings.PATH) else ([], [])
    for e in err:
        line(False, e, "REQUIRED: fix in config.json, or re-run /job-search-setup")
    for w in warn:
        line(False, w, "optional")
    print("\nAll required checks passed." if ok else "\nFix the REQUIRED items above, then run this again.")
    return 0 if ok else 1


def redact(text):
    text = text.replace(os.path.expanduser("~"), "~")
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<email>", text)
    text = re.sub(r"\+?\d[\d\s().-]{8,}\d", "<number>", text)
    return re.sub(r"https?://\S+", "<url>", text)


def bundle():
    c = settings.load()

    def shape(v):
        if isinstance(v, dict):
            return {k: shape(x) for k, x in v.items() if not k.startswith("_")}
        if isinstance(v, list):
            return f"list of {len(v)}"
        return "set" if v not in ("", None, 0, False) else "empty"
    out = [f"python {platform.python_version()} on {platform.platform()}",
           "claude: " + (subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip() if shutil.which("claude") else "not found"),
           "soffice: " + ("found" if shutil.which("soffice") else "not found"),
           f"setup done: {os.path.exists(DONE)}", f"config.json present: {os.path.exists(settings.PATH)}",
           "config shape (values hidden):", json.dumps(shape(c), indent=1)]
    log = os.path.join(ROOT, "data", "cycle.log")
    if os.path.exists(log):
        out += ["last lines of data/cycle.log (redacted):", *open(log).read().splitlines()[-40:]]
    print(redact("\n".join(out)))
    print("\nReview this before you paste it into an issue. It hides your config values, emails, numbers and links, but read it anyway.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--apply", metavar="FILE")
    g.add_argument("--doctor", action="store_true")
    g.add_argument("--support-bundle", action="store_true")
    a = ap.parse_args()
    sys.exit(status() if a.status else apply(a.apply) if a.apply else doctor() if a.doctor else bundle())


if __name__ == "__main__":
    main()
