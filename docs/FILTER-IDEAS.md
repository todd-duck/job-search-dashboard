# Filter ideas

The project ships with plain, general rules: title words, location, pay floor, excluded companies, posting age, and a scoring pass that rewards the themes you name. Everything below is **not built in**. These are ideas other users have wanted. If one fits you, ask Claude to add it, then keep it only if the results get better.

How to ask: open Claude Code in this folder and paste the idea along with your own words, for example:

> Read `scripts/fetch_jobs.py` (the `prefilter` function) and `config.example.json`. Add an optional filter, off unless `config.json` turns it on, that does the following: ... Add a unit test with its own fixture and update the README. Keep the code style.

Guidelines when you do this: new behavior should be **off by default**, driven by `config.json` (never hard-coded), and covered by a test in `tests/test_core.py` that does not depend on your own settings.

## Ideas

**1. Narrow-scope companies.** Some employers sell many products, only some of which match you. Keep a posting from those companies only if it also names a term you care about (a product or technology), and skip it if its title contains a word you rule out (for example "security" for someone who is not a security specialist). Config shape: a list of companies, a list of required terms, a list of excluded title words.

**2. Adjacent role types with stricter rules.** A role you would take only under extra conditions, such as a "Customer Success Manager" title only when the posting names your technology and the pay is above a higher floor. Config shape: titles, required terms, and its own salary floors.

**3. Stretch tracks.** Titles outside your main track (for example hands-on "Platform Engineer" roles for a pre-sales person) that are let through only when the posting names several concrete tools, then scored lower and tagged so you can see them as stretch roles. Config shape: titles, required terms, required tools with a minimum count, and a score adjustment.

**4. Companies that are different on purpose.** A class of employers (for example fast-growing labs) where an on-site requirement elsewhere should lower the score instead of dropping the job. Config shape: a company list and a score penalty used in place of the normal "wrong location" drop.

**5. Lower-weight adjacent markets.** A theme that is not your core but you would consider (for example adjacent infrastructure markets): postings with at least N of those words are kept as B-tier, or A-tier when the pay is above a level you set. Config shape: a word list, a minimum hit count, and a salary level.

**6. Previously applied.** Flag (not drop) postings at companies where you already have an application folder or a logged application. The base project already flags this when it can find an earlier application folder; extend it to your own history if you keep it elsewhere.

**7. Time zone and region rules.** If you must overlap a time zone, drop remote roles that require living in another one. The base project already drops postings whose stated restriction names a region away from your home territory (see `home_territory_terms`); you can make it stricter or looser.

**8. Per-role salary floors.** A different floor for each role family (for example a higher floor for staff-level titles). Config shape: a list of title words with a floor each.

**9. Your own scoring words per angle.** Give each angle its own bonus. Today `angles.list[].terms` only picks the label, and `domain_strong` sets the score.

## Ideas for later

- A Windows-native scheduler and folder opening (see the README's Windows section).
- A second input for postings you paste in by hand.
- Import of a spreadsheet tracker.
