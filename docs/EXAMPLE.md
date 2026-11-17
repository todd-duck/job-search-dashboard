# A worked example (fictional)

This is what a good setup looks like, so you can see what to give the interview and what comes out. **Alex Morgan is not a real person**, and nothing here is a recommendation for your own settings.

## The person

Alex is a Senior Solutions Engineer (a pre-sales technical role) at a mid-size observability company, based in Austin, TX, with 12 years of experience. Alex wants a similar role at a company that sells to platform and SRE teams, works remotely or near Austin, and will not take less than $150K base.

## What Alex tells the interview

| Question | Alex's answer |
|---|---|
| Titles you want | Solutions Engineer, Sales Engineer, Solutions Architect, Customer Success Engineer, Technical Account Manager |
| Titles you never want | Anything junior or intern; director, VP or other management; account executive, SDR |
| Words that make a posting great | observability, OpenTelemetry, Kubernetes, cloud-native, SRE, DevOps, AWS, Azure, GCP, AI infrastructure |
| Ideal role in one line | "A senior remote-US pre-sales role, or hybrid in Austin" |
| Home area | Austin, Round Rock, Cedar Park, Pflugerville, Leander (state: TX) |
| Pay | Base floor $150K; OTE floor $200K; bonus point at $180K base |
| Never show | Alex's current employer and two former employers |
| Watch these companies | A handful of observability and platform vendors. Claude finds and verifies each job board |
| Model spend | Keep the defaults ($0.50 judge, $0.50 discovery) |

Why these answers work: titles are concrete phrases a posting would really contain; the theme words come from what appears in postings Alex would love; the pay rule is a number, not "competitive"; the exclusions are named.

## What it writes

`config.json` (excerpt):

```json
"profile": {"full_name": "Alex Morgan", "current_title": "Senior Solutions Engineer",
            "search_scope": "a senior remote-US (or Austin, TX) role",
            "resume_master": "~/job-search/resume/AlexMorgan-Resume-Master.docx",
            "applications_dir": "~/job-search/applications"},
"targeting": {"title_must_match_one": ["solutions engineer", "sales engineer", "solutions architect", "..."],
              "salary_floor": 150000, "ote_floor": 200000, "salary_bonus_at": 180000,
              "home_metro_terms": ["austin", "round rock", "cedar park"], "home_state": "TX"}
```

`search-instructions.md` gets a plain-English profile the scoring judge reads, for example:

> - Candidate: Alex Morgan, based in Austin, TX.
> - Target job titles: Solutions Engineer, Sales Engineer, Solutions Architect...
> - Compensation: hard floor $150K base. A posting is dropped only when the TOP of its stated base range is below $150K...

## What the first runs look like

1. `python3 scripts/run_cycle.py --no-llm` (free): fetches boards, applies the hard rules, logs rules-scored rows. The report says how many postings were fetched, how many were dropped and why (wrong title, outside the pay floor, excluded company, too old, not remote or near home), and how many were kept.
2. `python3 scripts/run_cycle.py` (uses model credit): Claude reads the survivors, and each gets a tier. A typical early report: a few hundred postings fetched, a dozen or two kept, one to five in tier A.

## What a day with it looks like

- Morning: a few new rows. Alex clicks **Pass** with a reason on two ("territory is Pacific time", "mostly post-sales") and **Apply** on one.
- Alex ticks **cover letter** on the Apply row and clicks **Prepare application**. A few minutes later the folder `~/job-search/applications/examplecorp-SrSE/` holds a tailored resume, its PDF, `JD.md` and a one-page letter. Alex reads them, changes a sentence, and applies on the company site.
- Alex sets the row to *Applied*. Two weeks later a recruiter calls: **Log event** (recruiter call, debrief: "asked about OpenTelemetry collectors; I stumbled on sampling"). A month later a rejection arrives: **Record rejection**, cause "missing a requirement", fix "build a small OpenTelemetry demo".
- After a dozen applications, **Why not?** shows most losses happen at the hiring-manager step and that "OpenTelemetry" is a requirement in 40% of postings Alex applies to.

## Making it your own

- Start with the same shape of answers, with your own field's words. If your field is not pre-sales, change the titles and theme words; everything else works the same way. The setup interview writes the scoring profile in your field's language.
- Start narrow, then widen. It is easier to add titles and boards after seeing real results than to wade through noise.
