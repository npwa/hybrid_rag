# Runbook: dense search needs an ANN index

**Shown as:** the "Search scale" gauge on the Index health page ("approaching" at 50 % of the threshold,
"needs_index" at 100 %). **Ticket:** HYR-02.

## What it means
Dense search is a brute-force scan (`query/dense.py` creates no index). Measured on this machine:
38 ms at 18k chunks, 328 ms at 180k, 1.8 s at 900k. With an IVF-PQ index the 900k search took 6 ms. The
threshold (`ann_threshold_chunks`, default 200,000) is where the scan starts to dominate answer time.
Recall with an index has **not** been measured on real data.

## Check
- Index health page, or `GET /api/v1/index/summary` field `ann` (`chunks`, `threshold`, `has_ann_index`, `state`).
- Real latency: `grep "QUERY" logs/query_*.log | tail` (total seconds include generation; retrieval time is in
  the JSONL log field `retrieve_s`).

## Fix
Not automated. Follow HYR-02: create an IVF-PQ index in the indexing step, measure recall@20 against the flat
scan on the real corpus, then enable it. Until then nothing is needed below the threshold.
