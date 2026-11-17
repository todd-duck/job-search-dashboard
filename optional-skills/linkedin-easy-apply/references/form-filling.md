# Filling an Easy Apply Form (Claude in Chrome)

The Easy Apply dialog has 2–6 pages: Contact info → Resume → Additional questions (1–3 pages) → Work authorization / EEO → Review.
Do one page at a time. Read the page, fill it, check it, then click Next.

## Per-page loop

1. `find` "Easy Apply dialog form fields and buttons" (or `read_page` with `filter: "interactive"` scoped to the dialog's ref). The dialog is `div[role=dialog]`, usually labeled "Apply to <Company>".
2. For each field, check the current value first. **Don't overwrite fields LinkedIn has already filled** (email, phone, and city usually come from the profile) unless they're wrong.
3. Fill with `form_input` using the element ref:
   - Text and number inputs: a plain string (`"150000"`, `"7"`).
   - `<select>`: the visible option text (`"Yes"`, `"No"`).
   - Radio groups: set the radio whose label matches to `true`.
   - Typeahead fields (city, school): `computer` `left_click` the field, `type` the text, wait about 1 second, then click the first matching suggestion. Typed text alone fails validation.
4. Click **Next** / **Review** with `computer` `left_click` on the button's ref.
5. Check for errors with `find` "inline error messages in the dialog". If any appear, fix those fields and click again. If the same field fails twice → STUCK.

## Resume page

- If LinkedIn lists previously uploaded resumes, pick the most recent one named like the user's resume file (click its card so it shows as selected).
- Otherwise use `file_upload` with `config.profile.resume_pdf` on the hidden `input[type=file]`. Never click the Upload button itself, because that opens a native file picker.
- If `file_upload` rejects the path (the folder isn't shared with the session), mark STUCK: "Resume upload needs one manual upload; LinkedIn remembers it afterward."
- For an A-tier job with a tailored resume, upload the tailored PDF from that job's folder instead.
- Cover letter upload: skip unless it's required.

## Answering screening questions

Answer from `config.json`, then `data/EXPERIENCE_ANSWERS.md`. If neither covers the question, **pause and ask the user**. Never guess.

| Question pattern | Answer source |
|---|---|
| Legally authorized to work in the US | `screening.authorized_to_work_us` |
| Require sponsorship (now or future) / visa | `screening.requires_sponsorship` |
| Expected / desired salary (numeric) | `screening.expected_base_salary` |
| Expected salary (free text) | `screening.salary_text` |
| Current salary | `screening.current_salary` = DECLINE → leave blank if optional; if required → ASK |
| Notice period / when can you start | `screening.notice_period` / `screening.start_date` |
| Willing to relocate | `screening.willing_to_relocate` |
| Comfortable commuting / working onsite at <place> | Home area → `commute_home_area`; elsewhere → `commute_outside_home_area` |
| Comfortable working remotely | `screening.remote_ok` |
| Bachelor's degree / highest education | `has_bachelors` / `highest_education` |
| "How many years of experience with X" | Closest key in `years_of_experience`. Pick the most specific matching key. If none fits honestly → ASK |
| "Do you have experience with X?" (Yes/No) | Yes only if X appears on the resume or in `years_of_experience`; otherwise ASK |
| Gender / race / veteran / disability (voluntary self-ID) | `eeo_self_identification` (choose the "decline" / "prefer not to say" option) |
| Free-text "describe / why / tell us" | `EXPERIENCE_ANSWERS.md`, tailored with the company name and one posting detail |
| Already in `screening.learned` | Use it verbatim |
| Travel %, security clearance, background/drug-test consent, non-compete, referral source, anything legal-sounding | ASK (first time), then save under `screening.learned` |

**Numeric fields that reject decimals or large values:** some "years" fields cap at 2 digits or 99. Enter integers only.

**ASK means:** stop filling, show the user the exact question, its options, and your proposed answer with the reason, then wait. After they answer, add `"<normalized question>": "<answer>"` to `screening.learned` in config.json so the question doesn't come up again.

## Review page (submit_mode = review)

Stop here. Don't click Submit. Run `get_page_text` on the dialog and show the user a compact summary:

```
[3/8] Acme Cloud: Senior Solutions Engineer (Remote US) · Score 9 · A-tier
Resume: Resume.pdf
Answers:
  Years Kubernetes → 7
  Expected salary → 150000
  Sponsorship → No
  Why Acme? → "I've spent my career in technical pre-sales…" (NEW, not in answer bank)
Submit? (yes / edit <field> / skip)
```

- **yes** → click "Submit application". Confirm the "Application sent" / "Your application was sent" message, close the dialog (Dismiss / Done), and log it.
- **edit** → click Back to the right page, change the field, and return to Review.
- **skip** → close the dialog with Dismiss, then choose **Discard** (don't save it as a draft). Log it as Skipped.

## Things that break

- **"Continue applying" / "Save this application?"** modal: you hit Dismiss by mistake. Click Continue unless you're skipping.
- **Job page shows "Apply" (external) instead of "Easy Apply":** skip it and log `External`.
- **"Applied X days ago" badge on the job page:** skip it and log `Duplicate`.
- **"You've reached the Easy Apply application limit for today" / "We limit how often…":** STOP the whole run.
- **Login wall / checkpoint / CAPTCHA:** STOP and ask the user to handle it in the browser. Never try to solve a CAPTCHA.
