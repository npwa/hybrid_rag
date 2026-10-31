# Runbook: questions get "I couldn't find anything relevant"

**Shown as:** Query analytics "No relevant result" rate rising, the "No relevant result" tab; Signal replies that nothing relevant was found.

## What it means
The relevance gate refused: fewer than `relevance_min_hits` (1) dense hits were closer than `relevance_distance_threshold` (0.85), and
general-knowledge fallback is off. Production did not call the language model. The reasons are almost always one of: the document is
not indexed, the question is worded very differently from the document (terse list-style files embed far from questions), or the
settings are too tight (see `Doc/Postmortems/PM-01-min-hits-refusal.md`).

## Check
1. Paste the question into the **Query explorer**: the verdict card shows nearest distance, hits and what other `min_hits` would do.
2. Is the document indexed? Index health, "Problem files": filter by name; a failed or skipped file cannot be found.
3. Did it work before? Run `scripts/run_gold_set.py`; a failure on a known question points at a settings or index change.
4. Recently added files only appear after the daily maintenance run (`stale-index.md`).

## Fix
- Missing or failed file: fix the cause in `index-failure-causes.md`, re-run maintenance.
- Wording: ask with words the document uses; consider adding a gold question for it.
- Settings: change `relevance_distance_threshold` only after the gold set shows no regression in either direction.
