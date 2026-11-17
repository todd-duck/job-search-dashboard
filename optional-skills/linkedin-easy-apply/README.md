# linkedin-easy-apply (optional skill)

Finds LinkedIn Easy Apply jobs for your target roles, scores them, fills each application from your resume-derived config, and **stops at LinkedIn's Review screen so you approve every submit**.

- Needs Claude Code with the **Claude in Chrome** extension, and you logged in to LinkedIn in that Chrome profile.
- Installed by `./install.sh` in the main project (it asks first). Configured by the `/job-search-setup` interview, or by copying `config.template.json` to `config.json` and editing it.
- Your personal data lives in `config.json`, `data/`, and `assets/`, all git-ignored.
- **Use at your own risk.** Automating LinkedIn may conflict with LinkedIn's User Agreement. Read it. The skill is deliberately slow and capped (`daily_cap`), never solves CAPTCHAs, and stops at the first warning sign.
- Entry point: `SKILL.md`. Invoke with `/linkedin-easy-apply`.
