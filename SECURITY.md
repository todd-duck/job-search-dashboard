# Security

## Reporting a vulnerability

Please report security problems privately, not in a public issue or discussion.

Use GitHub's private reporting: open the **Security** tab of this repository and choose **Report a vulnerability**.

Include what you found, how to reproduce it, and what an attacker could do with it. This is a one-person hobby project, so expect a reply within about a week.

## How the project is built to stay safe

- **Local only.** The dashboard listens on `127.0.0.1` and refuses requests whose `Host` header isn't a loopback name, which blocks DNS-rebinding attacks. Changes need a custom `X-Dashboard` header, so other websites can't send them from your browser.
- **Your data stays on your machine.** Your profile, resume, tracker and search results are git-ignored. The tool talks to public job-board APIs and to your own Claude Code install, and to nothing else.
- **No third-party packages.** Everything uses the Python standard library, so there are no dependencies to patch.
- **Nothing is applied for you.** The core tool never submits an application. The optional LinkedIn skill stops at LinkedIn's Review screen and waits for your approval.

## Things to know

- Job postings are untrusted text that Claude reads. The tool is built to treat them as data, but if you add your own prompts, don't tell Claude to follow instructions found in a posting.
- `python3 scripts/setup.py --support-bundle` hides config values, emails, numbers and links, but it can still show company or role names from your run log. Read it before you paste it anywhere.
- Don't expose the dashboard to a network (for example by changing the bind address or forwarding the port). It has no login.
