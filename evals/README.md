# Judge evals (advanced)

Scripts for measuring how well the scoring model extracts facts from postings. They build test cases from **your own** judged postings (`data/`), so they only make sense after you have a few hundred of them. Nothing here ships with data, and everything it generates stays in your git-ignored `data/` or in `evals/judge_facts/*.json`, which you should not commit.

Order: `build_cases.py` -> `build_pool.py` -> `label_draft.py` -> `make_review.py`.
