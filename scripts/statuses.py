"""The one place that defines what a job status is.

Every status is "<Group>" or "<Group>: reason" (also "<Group> (reason)"). The group decides everything else: whether the
row is still open, whether it archives, when it needs a follow-up, whether it asks for a reason, and what funnel stamps it.
log_jobs.py, dashboard.py and the dashboard page (via /api/jobs `status_meta`) read these tables instead of keeping their own
lists, so adding a status means adding one line here."""

# Display order for the Status dropdown. Group rules are in GROUPS below.
CHOICES = ["New", "Saved", "Apply", "Applied", "Interviewing", "Rejected", "Pass", "Closed", "Covered"]

GROUPS = {
    #                open   archived  follow-up days  asks for a reason  funnel stamp  triage buttons
    "Interviewing": dict(open=True,  archived=False, followup=7,    reasoned=False, stamps_applied=True,  triage=False),
    "Applied":      dict(open=True,  archived=False, followup=10,   reasoned=False, stamps_applied=True,  triage=False),
    "Apply":        dict(open=True,  archived=False, followup=None, reasoned=False, stamps_applied=False, triage=False),
    "New":          dict(open=True,  archived=False, followup=None, reasoned=False, stamps_applied=False, triage=True),
    "Saved":        dict(open=True,  archived=False, followup=None, reasoned=False, stamps_applied=False, triage=True),
    "Covered":      dict(open=False, archived=True,  followup=None, reasoned=True,  stamps_applied=False, triage=False),
    "Rejected":     dict(open=False, archived=True,  followup=None, reasoned=True,  stamps_applied=True,  triage=False),
    "Pass":         dict(open=False, archived=True,  followup=None, reasoned=True,  stamps_applied=False, triage=False),
    "Closed":       dict(open=False, archived=True,  followup=None, reasoned=True,  stamps_applied=False, triage=False),
}
assert set(CHOICES) == set(GROUPS)

ACTIVE_ORDER = ["Interviewing", "Applied", "Apply", "New"]  # how active rows sort in jobs.md (anything else after these)
# Postings you may still act on; the companies-take-one-application logic works over these.
OPEN = tuple(g for g in CHOICES if GROUPS[g]["open"])
# Which siblings an "apply once, cover the rest" click may cover: only untouched ones, or (explicit primary) also mistaken Applied ones.
COVER_AUTO = ("New", "Saved")
COVER_EXPLICIT = ("New", "Saved", "Apply", "Applied")


def group(status):
    """'Pass: too post-sales' -> 'Pass'; 'Pass (salary)' -> 'Pass'."""
    return str(status or "").split(":")[0].split("(")[0].strip()


def is_valid(status):
    return group(status) in GROUPS


def archived_groups():
    return [g for g in CHOICES if GROUPS[g]["archived"]]


def followup_days():
    return {g: GROUPS[g]["followup"] for g in CHOICES if GROUPS[g]["followup"]}


def stamps_applied(status):
    return GROUPS.get(group(status), {}).get("stamps_applied", False)


def transition_error(old, new):
    """None if old -> new is allowed, else why not. Deliberately small: you can always undo a mistake."""
    if group(new) == "Covered" and group(old) == "Interviewing":
        return "can't cover a posting you're interviewing for"
    return None


def meta():
    """What the dashboard page needs to behave like the server."""
    return {"choices": CHOICES, "open": list(OPEN), "archived": archived_groups(), "order": ACTIVE_ORDER,
            "reasoned": [g for g in CHOICES if GROUPS[g]["reasoned"]], "triage": [g for g in CHOICES if GROUPS[g]["triage"]],
            "cover_auto": list(COVER_AUTO), "cover_explicit": list(COVER_EXPLICIT)}
