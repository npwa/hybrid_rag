# HYR-02: Dense search has no ANN index (brute-force scan)

- **Severity:** Medium (latent; no impact at current corpus size)
- **Status:** Open
- **Component:** `query/dense.py`, indexing step (LanceDB)

## Impact
None today: about 18k chunks searches in 38 ms. Measured brute-force latency
grows linearly: 328 ms at 180k chunks and 1.8 s at 900k. Past roughly 200k
chunks, dense search becomes the dominant retrieval cost. The design target
(1M documents / 500 GB, about 5-20M chunks) is far beyond that.

## Description
`query/dense.py` calls `tbl.search(vector).limit(limit)` and no code creates a
vector index, so LanceDB does a flat scan. A benchmark with IVF-PQ gave 6 ms at
900k chunks (build time 37 s). Recall with the index has not been measured on
real data. `Doc/step-4-requirements.md` §7 documents these numbers.

## Proposed fix
1. Add index creation (IVF-PQ) to the indexing/maintenance step, triggered when
   the row count passes a threshold (about 100-200k chunks), and rebuilt after large
   ingests.
2. Measure recall@20 against the flat scan on the real corpus and tune
   `nprobes`/`refine_factor` before enabling it by default.
3. Re-check memory use against the 62 GB RAM limit if the corpus grows toward
   the design target.

## Acceptance
Query latency stays under about 50 ms for dense search at 1M chunks, with
recall@20 within an agreed margin of the flat scan.
