---
name: job-search-setup
description: First-run interview that turns a blank install into a working job search. Asks the user about who they are, the roles they want, where they will work, pay, companies to include or avoid, and their resume, then writes config.json and search-instructions.md, optionally installs the LinkedIn Easy Apply skill, and runs the first search. Use when the user says "set up", "configure", "get started", "/job-search-setup", or when /job-search finds no data/.setup_done.
---

# Job search setup (interview)

You are configuring a job-search pipeline for the person at the keyboard. Be a patient guide: they may be new to the terminal. Explain what you are doing in plain words before each step, one short paragraph at most. Ask a few questions at a time (never a wall of 20). Offer a suggested answer wherever you can, so "yes" is a valid reply.

**Ground rules**
- Everything stays on this machine. Do not upload their resume or answers anywhere.
- Never invent facts about them. Suggestions are drafts they confirm.
- Never apply, message, or create accounts for them.
- Run commands from the project root (the folder containing `scripts/`).
- If `data/.setup_done` already exists, say so and ask whether they want to **change a few settings** (edit just those keys) or **start over** (back up `config.json` first with `python3 scripts/setup.py --apply`, which does that automatically).

## Step 0: check the machine
Run `python3 scripts/setup.py --doctor`. Fix any REQUIRED item with the user before going on (explain each fix in a sentence; give the exact command; never install system software without their say-so). LibreOffice is optional: without it they get `.docx` resumes but no PDFs.

## Step 1: who you are (ask together)
1. Full name as it should appear on resumes and letters.
2. Current (or most recent) job title.
3. City and state where you live, and whether you are open to hybrid or in-person work near there.
4. Where is your **master resume** (a `.docx` file)? Check it exists. If they only have a PDF or no resume, say that tailoring works best from a `.docx` and offer to continue without it (note it for later).
5. Folder where application folders (tailored resume, cover letter, job description copy) should be created. Suggest `~/job-search/applications`.

## Step 2: the roles you want
Read their resume if they gave one (it stays local). Then propose, and let them correct:
- **Target titles** (`targeting.title_must_match_one`): lower-case phrases a title must contain, e.g. "solutions engineer", "sales engineer". Include common synonyms.
- **Titles to skip** (`title_skip`): words that rule a title out (junior, intern, director, ...). Start from the example and add what they say they do not want (e.g. management roles).
- **Seniority words** that earn a bonus (`seniority_bonus`).
- **Themes** (`domain_strong`, `domain_weak`): the technologies, markets or skills that make a posting a good fit. Strong = each hit adds a point; weak = tie-breakers only. Ask: "Which 5 to 10 words would you hope to see in a perfect posting?"
- A one-line **search scope** for web discovery (`profile.search_scope`), e.g. "a senior remote-US role, or hybrid in Denver".
- 3 to 6 **web queries** for discovery (`web_queries`), written the way they would search a job board.
Optional tracks, off unless they ask: `platform_roles`, `csm_roles`, `domain_infra`, `ai_lab_companies`, `k8s_only_companies`. Mention they exist; do not push them.

## Step 3: location and pay
- Remote only, or remote plus a home area? Fill `targeting.home_metro_terms` (cities/areas, lower case, ambiguous towns with the state, e.g. "georgetown, tx"), `home_territory_terms` (region words like "south central"), and `home_state` (two letters).
- Salary: the **base floor** (`salary_floor`), the **OTE floor** if pay is mostly variable (`ote_floor`), and the **bonus point** level (`salary_bonus_at`). Explain the rule: a posting is dropped only when the TOP of its stated range is below the floor; postings with no pay stated are kept.
- Citizenship or work-authorization limits only matter if the user mentions them; note them in the profile text.

## Step 4: companies
- **Never show**: `targeting.excluded_companies` (current employer, former employers they would rather not revisit, anyone they have ruled out).
- **Companies to watch**: for each company they name, find its public job board and verify it. Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs`; Lever: `https://api.lever.co/v0/postings/<slug>`; Ashby: `https://api.ashbyhq.com/posting-api/job-board/<slug>`. Use WebSearch/WebFetch to find the slug, confirm it returns jobs, then add to `sources.ats.<system>` as `"slug": "Company Name"`. Companies with no public board go in `sources.watch_no_api.companies` as `"Name": "careers URL"`. Tell them it is fine to start with only a handful and add more later (`python3 scripts/fetch_jobs.py --check-sources` tests every board).
- If they name none, keep the example boards and say they can be removed later from the dashboard's tuning panel.

## Step 5: spending and automation
Explain in plain words that scoring and discovery call Claude headlessly, and that this uses their Claude plan or API credit. Show the defaults and let them change them (`automation`): `judge_budget_usd` (per run, scoring postings), `discover_budget_usd` (web discovery), `discover_every_days`. Per-job caps in `scripts/dashboard.py` (`APPLY_BUDGET_USD` for application prep, `WHY_BUDGET_USD` for the Why not? diagnosis) can be edited there. `--no-llm` runs rules-only and costs nothing.
Ask whether they want a daily scheduled run (`scripts/schedule.sh install`, macOS launchd). Do not install it yourself; give them the command.

## Step 6: write it
1. Draft the answers as one JSON file in the scratchpad or a temp file (NOT in the project): keys `profile`, `targeting`, `scoring` (only if they changed weights), `web_queries`, `sources`, `automation`, and `profile_markdown` (the bullet list that goes under "## Candidate profile": candidate, current role, target titles, positioning themes, location, level, excluded companies, compensation rule, and any hard limits, written plainly and truthfully; the scoring judge reads it literally).
2. Show them a short summary (not the raw JSON) and ask "Does this look right?". Fix what they flag.
3. Run `python3 scripts/setup.py --apply <file>`. It validates, backs up any earlier `config.json`, writes `config.json` and the profile section, creates the applications folder, and marks setup done. If it refuses, fix what it lists.
4. Delete the temp JSON.

## Step 7: optional LinkedIn Easy Apply skill
Ask: "Do you want the optional LinkedIn Easy Apply skill? It finds and fills LinkedIn Easy Apply forms in your own Chrome and stops for your approval on every submit." If yes:
- Read them the risk note: automating LinkedIn may conflict with LinkedIn's terms; use is at their own risk; it is slow and capped on purpose.
- Confirm they have the Claude in Chrome extension and are logged in to LinkedIn.
- Install: copy `optional-skills/linkedin-easy-apply/` to `~/.claude/skills/linkedin-easy-apply/` (if that folder exists, ask before touching it; never overwrite their `config.json`).
- Configure `~/.claude/skills/linkedin-easy-apply/config.json` from `config.template.json`: fill `profile` from what you already know plus email, phone, LinkedIn URL, education (ask); `targeting` from this project's config; `screening` answers one by one (work authorization, sponsorship, expected salary, notice period, relocation, remote, commute, education, EEO preference: offer "decline to answer"); `years_of_experience` with TRUE whole numbers for each skill they name. Create `data/EXPERIENCE_ANSWERS.md` from the template, writing entries only from their resume.
- Export `resume_pdf` from their `.docx` with `soffice --headless --convert-to pdf` if LibreOffice is installed.
If no, say they can add it any time by asking you to "install the LinkedIn skill".

## Step 8: first run
1. Offer a free dry run: `python3 scripts/run_cycle.py --no-llm`. Read `data/last-report.md` and summarize in 5 lines. Explain tiers (A best, B good, C marginal) and that nothing is judged by Claude yet.
2. Offer a real run: `python3 scripts/run_cycle.py` (uses their plan; capped by `automation` budgets). Summarize the top few matches and what was dropped and why.
3. Launch the dashboard: tell them to run `python3 scripts/dashboard.py --launch` and open http://127.0.0.1:8765/. Give a 5-line tour: tabs/filters, Apply/Pass buttons, "Prepare application", the cover-letter checkbox, "Why not?" after rejections.
4. Tell them how to tune later: Pass jobs with a reason (the tool learns from Pass reasons), and re-run `/job-search-setup` any time to change settings.

## If something fails
Run `python3 scripts/setup.py --support-bundle`, tell them to read it, and, if they want help, paste it into a GitHub issue (it hides config values, emails, numbers and links).
