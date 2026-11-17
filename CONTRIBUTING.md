# Contributing

Thanks for helping. Issues and pull requests are welcome.

## Ground rules

- **Never include personal data.** No resumes, trackers, real `config.json`, application folders, tokens, or screenshots of your dashboard with real companies in a bug report. Use the fictional example (Alex Morgan) or invent values.
- Run the tests before opening a PR: `python3 -m unittest discover -s tests`. The tests use `tests/fixture_config.json`, never your own settings. A test must not depend on anyone's `config.json`.
- Keep it standard-library Python (3.10+). No new runtime dependencies without a good reason.
- Match the surrounding code's style, naming and comment density.
- The pipeline never applies, messages or creates accounts on a person's behalf without an explicit approval step. Changes that weaken that will not be merged.

## Reporting a problem

Run `python3 scripts/setup.py --support-bundle`, read the output, and paste it into the issue. Say what you did, what you expected, and what happened.

## Making changes

- Settings belong in `config.json` (documented in `config.example.json`), not hard-coded. Identity, locations and company names must never appear in code or skills.
- New features that change what gets searched should be off by default, like `platform_roles` and `csm_roles`.
- Update `README.md` and the relevant `SKILL.md` when behavior changes.
