"""Write review.md: every real case, the drafted gold, the evidence quote, and which fields are CONTESTED
(labeler marked uncertain, or Sonnet's cached answer differs). Review the contested ones closely; the rest
are accepted unless you object. Rulings go in rulings.json (see the footer of review.md)."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import run_cycle as rc  # noqa: E402

FIELDS = ("core_match", *rc.BOOLS, "specialist_requirement", "residency_restriction")


def present(f, v):
    return bool(v) if f in ("specialist_requirement", "residency_restriction") else v


def contested(g, s):
    out = {}
    for f in FIELDS:
        why = []
        if f in g.get("uncertain", []):
            why.append("labeler unsure")
        if present(f, g[f]) != present(f, s[f]):
            why.append("differs from Sonnet cache")
        if why:
            out[f] = why
    return out


def main():
    cases = json.load(open(os.path.join(HERE, "cases_real.json")))
    drafts = json.load(open(os.path.join(HERE, "labels_draft.json")))
    lines, summary, total = [], [], 0
    import random
    flips = [c["id"] for c in cases if c["id"] in drafts and bool(rc.decide(drafts[c["id"]]["gold"], c["candidate"]["title"])["drop"])
             != bool(rc.decide(c["sonnet_cached"], c["candidate"]["title"])["drop"])]
    rest = [c["id"] for c in cases if c["id"] in drafts and c["id"] not in flips]
    spot = sorted(random.Random(3).sample(rest, 4))
    order = {i: n for n, i in enumerate(flips + spot + [r for r in rest if r not in spot])}
    cases = sorted(cases, key=lambda c: order.get(c["id"], 99))
    for c in cases:
        d = drafts.get(c["id"])
        if not d:
            continue
        g, s, j = d["gold"], c["sonnet_cached"], c["candidate"]
        cont = contested(g, s)
        total += len(cont)
        dec = rc.decide(g, j["title"])
        verdict = f"DROP ({dec['drop']})" if dec["drop"] else "KEEP"
        tag = "START HERE: flips keep/drop" if c["id"] in flips else "spot-check" if c["id"] in spot else ""
        summary.append(f"| {c['id']} | {j['company']} | {j['title'][:55]} | {c['sample_bucket']} | {verdict[:48]} | {', '.join(cont) or '-'} | {tag} |")
        lines += [f"### {c['id']} · {tag + ' · ' if tag else ''}{j['company']} — {j['title']}", f"{j['location']} · {j.get('salary') or 'no salary'} · {c['url']}", "",
                  "| field | drafted gold | evidence | flag |", "|---|---|---|---|"]
        for f in FIELDS:
            ev = (g["evidence"].get(f) or "").replace("|", "/").replace("\n", " ")[:170]
            fl = "; ".join(cont.get(f, []))
            mark = "**" if fl else ""
            lines.append(f"| {mark}{f}{mark} | `{g[f]!r}` | {ev} | {fl} |")
        lines += ["", f"Decision under this gold: **{verdict}**", ""]
    head = ["# Judge-facts eval: review the drafted gold labels", "",
            "Labels drafted by Opus 5.5 reading the FULL posting (the model under test, Sonnet, only sees a trimmed excerpt).",
            f"**{total} contested fields across {len(summary)} postings, but only {len(flips)} postings flip a keep/drop decision.**",
            f"Rule on the {len(flips)} 'START HERE' postings (they move what the pipeline does) and read the {len(spot)} 'spot-check' ones as a sanity check on the labeler. "
            "The rest are accepted as Opus-drafted and tagged unreviewed, and the report shows results both ways.", "",
            "Definitions come from the production prompt (`JUDGE_SYSTEM`). Where a definition is fuzzy, your ruling becomes the labeling policy.", "",
            "| id | company | title | bucket | decision under draft gold | contested fields | review |", "|---|---|---|---|---|---|---|", *summary, "", "---", ""]
    foot = ["---", "## How to give rulings", "",
            "Reply in chat like `r03 onsite=false; r07 core_match=partial; r12 ok` or edit `rulings.json` "
            '(`{"r03": {"onsite_or_relocation_elsewhere": false}}`). Anything you do not mention keeps the draft. '
            "Say `all ok` to accept every draft as-is."]
    open(os.path.join(HERE, "review.md"), "w").write("\n".join(head + lines + foot))
    print(f"review.md written: {len(summary)} cases, {total} contested fields")


if __name__ == "__main__":
    main()
