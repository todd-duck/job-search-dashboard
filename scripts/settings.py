"""Where your settings come from.

config.json is yours (git-ignored, written by the setup interview). If it does not exist yet, the shipped
config.example.json is used so a fresh clone still runs. Paths in it may start with ~."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "config.json")
EXAMPLE = os.path.join(ROOT, "config.example.json")


def load():
    p = PATH if os.path.exists(PATH) else EXAMPLE
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return {}


def profile():
    """The candidate's profile with safe defaults, so a missing key never crashes a prompt."""
    pr = dict(load().get("profile", {}))
    pr["full_name"] = pr.get("full_name") or "the candidate"
    pr["current_title"] = pr.get("current_title") or "job seeker"
    pr["search_scope"] = pr.get("search_scope") or "a senior remote-US role"
    return pr


def resume_master():
    c = load()
    return os.path.expanduser(c.get("profile", {}).get("resume_master") or c.get("automation", {}).get("resume_master") or "")


def apps_dir():
    return os.path.expanduser(load().get("profile", {}).get("applications_dir") or "~/job-search/applications")


def ensure():
    """Create config.json and search-instructions.md from the shipped examples if they are missing, so a fresh clone runs
    and edits made from the dashboard have a file to change. The setup interview overwrites both with your own."""
    import shutil
    for dst, src in ((PATH, EXAMPLE), (os.path.join(ROOT, "search-instructions.md"), os.path.join(ROOT, "search-instructions.example.md"))):
        if not os.path.exists(dst) and os.path.exists(src):
            shutil.copyfile(src, dst)
    return PATH
