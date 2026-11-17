# Job Search Dashboard

A job search that runs itself, built for [Claude Code](https://claude.com/claude-code). Tell it who you are and what you want once. It then scans company job boards every day, throws out what does not fit, scores the rest, and shows you the keepers in a local dashboard. When you like a job, one click prepares a tailored resume and (optionally) a cover letter. Afterwards it tracks every application, every interview step and every rejection, and tells you why you are not getting further.

Everything runs on your computer. Your resume, tracker and settings never leave it, except for the text sent to Claude when you ask it to score or write something.

Made by ToddC ([@todd-duck](https://github.com/todd-duck)).

## What you get

| | |
|---|---|
| **Daily scan** | Pulls open roles from company job boards (Greenhouse, Lever, Ashby, Workday and more) and remote job feeds, then applies your hard rules: titles, location, pay floor, excluded companies, posting age. |
| **Scoring** | Rules give each job a score. Claude reads the survivors in batches and judges the rest (real hands-on requirement? people manager? pay and location stated?). Results are cached, so nothing is paid for twice. |
| **Dashboard** | A single local web page: filters, saved views, one-click **Apply / Pass** with reasons, keyboard shortcuts, a status light, a progress bar for runs. |
| **Application prep** | **Prepare application** writes a resume tailored to the posting, a PDF, an optional cover letter (a per-job checkbox), and keeps a copy of the job description in the folder in case the posting disappears. It never invents experience and never submits anything. |
| **Interview journey** | Log recruiter calls, hiring manager rounds, demos and panels, with debriefs. Record rejections with the real cause. **Why not?** shows where applications die and what to fix. |
| **Learns from you** | Pass reasons turn into suggested rules you accept or deny. Nothing changes without your approval. |
| **Optional skills** | Warm-intro finder (who do you know at the company), and a LinkedIn Easy Apply helper that always stops for your approval. |

## Before you start

You need:

1. **Claude Code**, installed and logged in. Run `claude` once in a terminal to confirm. A Claude plan or API credit is required; see [Cost](#cost).
2. **Python 3.10 or newer** (`python3 --version`). The project uses only the standard library, so there is nothing to `pip install`.
3. **git** to download it.
4. Optional: **LibreOffice** (macOS: `brew install --cask libreoffice`) so resumes also export as PDF.
5. Optional: Chrome with the **Claude in Chrome** extension, only for the LinkedIn and warm-intro skills.
6. Your **master resume** as a `.docx` file, if you want tailored resumes. It is the single source of truth: tailoring never adds anything that is not in it.

**Platforms.** Tested on macOS. Linux should work for everything except the daily scheduler (`scripts/schedule.sh` uses macOS launchd; use cron instead).

**Windows is not supported natively.** The project uses `bash` scripts, `lsof`, POSIX signals and `soffice` on the path, and the Claude in Chrome skills are untested there. If you are on Windows, the best route is **WSL2** (Ubuntu) with Python, git and Claude Code installed inside it. That is untested too. If you get it working, please share what you changed in a [Discussion](https://github.com/todd-duck/job-search-dashboard/discussions) or a pull request, and we will add a Windows section.

## Install (about 5 minutes)

```bash
git clone https://github.com/todd-duck/job-search-dashboard.git
cd job-search-dashboard
./install.sh
```

`install.sh` checks your machine, runs the self-tests, and offers (never forces) the optional LinkedIn skill. It installs no system software.

> Keep the folder somewhere ordinary such as `~/job-search-dashboard`. On macOS, folders under Desktop, Documents, Downloads and iCloud Drive block the daily scheduled run.

## Configure: let Claude interview you

```bash
claude
```

Then type:

```
/job-search-setup
```

Claude asks a few questions at a time and offers a suggested answer for each. When you reply "yes" it accepts the suggestion. It will ask for:

| Topic | What to have ready |
|---|---|
| **You** | Full name, current job title, city and state, path to your master resume, a folder for application files. |
| **Roles** | The titles you want (and the ones you never want), seniority words, 5 to 10 words that would make a posting a great fit, a one-line description of your ideal role. Claude turns these into your "angles" (labels that group jobs by flavor) and the definition of a strong match. |
| **Location** | Remote only, or remote plus a home area (cities near you). |
| **Pay** | Base-salary floor, OTE floor if your pay is mostly variable, and the level that earns a bonus point. |
| **Companies** | Companies to never show. Companies to watch: Claude finds and verifies each one's job board. A handful is plenty to start. |
| **Money and schedule** | How much model usage per run you are comfortable with, and whether you want a daily scheduled run. |
| **LinkedIn skill** | Only if you installed it: contact details, screening-question answers, and true years of experience per skill. |

Then it writes `config.json` and `search-instructions.md`, runs a free rules-only trial, and (if you agree) a first real search. You can see what a good set of answers looks like in [docs/EXAMPLE.md](docs/EXAMPLE.md).

Prefer to do it by hand? Copy `config.example.json` to `config.json` and `search-instructions.example.md` to `search-instructions.md`, edit them, then run `python3 scripts/setup.py --status`.

You can re-run `/job-search-setup` any time to change settings. It backs up your old `config.json` first.

## Use it

Open the dashboard:

```bash
python3 scripts/dashboard.py --launch      # opens http://127.0.0.1:8765/
python3 scripts/dashboard.py --stop        # stops it
```

A normal day:

1. **Run a search** (or let the daily schedule do it): the dashboard's *Re-run job search now* button, or `python3 scripts/run_cycle.py`. `--no-llm` runs the rules only, for free.
2. **Triage.** New jobs arrive as `New` rows with a tier: **A** (strong), **B** (good), **C** (marginal). Click **Apply** to move one to your apply list, or **Pass** to dismiss it with a reason. Passing is how it learns what you do not want.
3. **Prepare.** On a row you moved to Apply, tick **cover letter** if you want one, then click **Prepare application**. Claude works in the background and writes the files to `<your applications folder>/<company>-<role>/`: the tailored resume, a PDF, the job description (`JD.md`), and the letter if requested. Read them. You send the application yourself.
4. **Track.** Set the status to *Applied*. After each recruiter call or interview, open the row's drawer and use **Log event**. If you get a rejection, use **Record rejection** and note what you think the real reason was.
5. **Learn.** Open **Why not?** to see where applications stop, which requirements postings keep asking for that your resume lacks, and optionally one AI-written diagnosis.

Statuses: `New`, `Apply`, `Applied`, `Interviewing`, `Saved`, `Pass`, `Rejected`, `Closed`, and `Covered` (a company that takes one application for all its roles).

### Everyday commands

| Task | Command |
|---|---|
| Run a full search | `python3 scripts/run_cycle.py` |
| Rules-only run, no model cost | `python3 scripts/run_cycle.py --no-llm` |
| Check every company board still works | `python3 scripts/fetch_jobs.py --check-sources` |
| See today's report | `cat data/last-report.md` |
| Daily run at 07:30 (macOS) | `scripts/schedule.sh install 07:30` |
| Follow-ups that are due | `python3 scripts/log_jobs.py --followups` |
| What is configured / missing | `python3 scripts/setup.py --status` |
| Check your machine | `python3 scripts/setup.py --doctor` |

In Claude Code, `/job-search` also runs a cycle on request, reviews suggested rules and prepares applications.

## Your data and privacy

- All your data is in this folder and is **git-ignored**: `config.json`, `search-instructions.md`, `jobs.md`, `jobs-archive.md`, `data/`, and any `.docx`/`.pdf`. You can fork or push this project without leaking them, but **check `git status` before every push** if you have changed `.gitignore`.
- Text goes to Claude only when you ask for scoring, discovery, application prep, intros or a diagnosis. Job postings are treated as untrusted data: instructions hidden inside a posting are ignored and flagged.
- The dashboard listens on `127.0.0.1` only, and its write endpoints require a header a random web page cannot send.
- Back up `data/` and `jobs.md` yourself; they are your history.

## Cost

Scoring and discovery call Claude through your own Claude Code login, so they use your plan's usage or API credit. The defaults are small, and capped per run in `config.json` under `automation`:

| Setting | Default | What it limits |
|---|---|---|
| `judge_budget_usd` | 0.50 | Scoring the day's new postings |
| `discover_budget_usd` | 0.50 | Weekly web discovery of extra jobs |
| `discover_every_days` | 3 | How often discovery runs |

Two per-click caps live near the top of `scripts/dashboard.py`: `APPLY_BUDGET_USD` (4.00 per prepared application) and `WHY_BUDGET_USD` (1.50 per *Write a diagnosis*). Change the number to change the cap. `run_cycle.py --no-llm` costs nothing. `python3 scripts/metrics.py --report` shows where usage went.

## Optional skills

**Warm intros** (`/warm-intro`, or the dashboard's *Find intros*): looks up people at the company in your own logged-in LinkedIn and drafts notes for you to send. Read-only; it never sends anything.

**LinkedIn Easy Apply** (`optional-skills/linkedin-easy-apply`): finds Easy Apply jobs, scores them, fills the form from your answers, and stops at LinkedIn's Review screen so **you approve every submit**. It has a daily cap and stops at any warning sign.

> **Use at your own risk.** Automating LinkedIn may conflict with LinkedIn's User Agreement. Read it before you decide. Both skills are deliberately slow, read-only where they can be, and never solve CAPTCHAs. You are responsible for your account.

## Keeping it plain

The rules are general on purpose: titles, location, pay floor, excluded companies, posting age, and scoring from the themes you name. Special-case filters are not built in. [docs/FILTER-IDEAS.md](docs/FILTER-IDEAS.md) lists ideas (stricter rules for particular companies, stretch role types, and more) and how to ask Claude to add one.

## How it works

```
sources (company boards, feeds, web discovery)
   -> prefilter: titles, location, pay, age, exclusions     scripts/fetch_jobs.py
   -> rules score + Claude judges facts (cached)             scripts/run_cycle.py
   -> jobs.md + data/seen.json (your tracker)                scripts/log_jobs.py
   -> dashboard: triage, prepare, track, learn               scripts/dashboard.py
```

| Path | What it is |
|---|---|
| `config.json` | Your settings (created by setup, git-ignored). `config.example.json` is the template. |
| `search-instructions.md` | Your profile in plain English, which the scoring judge reads, plus approved Learned preferences. |
| `jobs.md` | The review queue as a readable table. |
| `data/` | Cache, history, logs, job-description copies, backups. |
| `.claude/skills/` | The `job-search`, `job-search-setup` and `warm-intro` skills. |
| `scripts/statuses.py` | The one definition of statuses, archive rules and follow-up timing. |
| `tests/` | Self-tests that use fixed fixtures, never your settings. |

## Troubleshooting

| Symptom | Try |
|---|---|
| `claude: command not found` | Install Claude Code, open a new terminal, run `claude` once to log in. |
| Setup says config is still the example | Run `/job-search-setup`, or edit `config.json` and set `profile.full_name`. |
| A scheduled run does nothing (macOS) | The folder is probably in Desktop/Documents/Downloads/iCloud. Move it to `~/job-search-dashboard`. |
| A company shows 0 jobs | Run `python3 scripts/fetch_jobs.py --check-sources`; the board name may be wrong or the company changed systems. |
| Status light is red | Click **What failed?** in the dashboard. It reads `data/cycle.log` and suggests a fix. |
| "forbidden" when clicking a button | The dashboard server is older than the page. Run `python3 scripts/dashboard.py --stop`, then `--launch`. |
| Tests fail | `python3 -m unittest discover -s tests` and open an issue with the output. |

## Getting help

- **Questions and "how do I...":** open a [GitHub Discussion](https://github.com/todd-duck/job-search-dashboard/discussions) (Q&A).
- **Install or first-run trouble:** open an issue using the *Install or setup help* template. Run `python3 scripts/setup.py --support-bundle` first and paste the output. It hides config values, emails, numbers and links, but read it before posting.
- **Bugs and ideas:** open an issue. Please never paste your resume, tracker, or real config.

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
