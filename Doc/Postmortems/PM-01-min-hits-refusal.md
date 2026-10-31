# PM-01: A valid single-source answer was refused by the relevance gate

**Date:** 2026-09-06 (commit `cc4c4d9`). **Severity:** Medium (wrong refusals, no data loss).

## Summary
The relevance gate required at least 2 dense hits closer than distance 0.7 (`relevance_min_hits: 2`). A real question whose
answer lives in one document ("when did I last fly to Palo Alto") was answered with "I couldn't find anything relevant".

## Impact
Any question answered by a single document could be refused. Found on one question; the number of refused questions before the
fix was not recorded.

## Timeline
- Step 5 build: the gate was calibrated on a handful of CLI queries (table in `step-5-requirements.md` §2a); all passed.
- Signal integration: "last flew to Palo Alto" returned the refusal. Distances were 0.57, 0.85, 0.90, so only one hit was under 0.7.
- Same day: `relevance_min_hits` set to 1. A second miss ("Thule Evolution 1800 sold price", 0.72, just over 0.7) led to
  `relevance_distance_threshold` 0.85.

## Detection
By a person, through Signal. The CLI tests had not covered single-source answers or terse list-style documents.

## Root cause
The gate was tuned on too few and too similar examples. A genuine single-source match (0.57) is *further* than a coincidental
false lead (Mozart, 0.49), so no distance rule separates them, and requiring two hits discarded true single-source answers.
Terse documents (lists, prices) also embed further from a natural-language question than prose does.

## Fix
`min_hits=1`, `distance_threshold=0.85` (both in `config/query_config.yaml`). Generation itself declines when the excerpts do
not support an answer, so a few false passes cost one model call but do not produce wrong answers.

## Prevention
- Gold question set (`scripts/run_gold_set.py`): real questions with the documents that must be found; run it before changing any
  gate setting. Lowering `min_hits` back to 2 makes it fail.
- Query explorer shows the verdict for one question and what it would be with other `min_hits` values.
- Query analytics: a rising "no relevant result" share is the early signal.
