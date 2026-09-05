"""Relevance gate for the opt-in general-knowledge fallback.

RRF's fused score (query/fusion.py) is rank-based, not magnitude-based — it always
happily returns a top-K even when nothing in the corpus is actually relevant (a fused
"best of a bad lot" still gets a normal-looking score). To detect "the knowledge base
genuinely has nothing on this," this looks at the *raw* dense-search distances before
fusion, since those have an interpretable absolute scale.

Calibrated empirically against this corpus (not guessed) — a single top-1 distance
threshold alone is unreliable: an off-topic query can coincidentally land one
short/generic chunk at a deceptively low distance (seen with a real "who was Mozart"
test: top-1 distance 0.49, better than some genuinely relevant queries), while a chunk
that's part of a real topical cluster tends to have *several* results clustered under
the threshold, not just one outlier. Requiring at least `min_hits` results under
`distance_threshold` reproduced the correct answer on every query tested:

    query                                    distances (top 3)      hits<0.7   verdict
    "adjusted gross income 2024"             0.58, 0.60, 0.60        3         relevant
    "who monitors the home alarm system"     0.65, 0.65, 0.79        2         relevant
    "who was wolfgang amadeus mozart"        0.49, 0.91, 0.97        1         NOT relevant
    "how many moons does jupiter have"       0.91, 0.92, 0.93        0         NOT relevant
"""
from __future__ import annotations


def has_relevant_results(dense_results: list[dict], distance_threshold: float, min_hits: int) -> bool:
    hits = sum(1 for r in dense_results if r["_distance"] < distance_threshold)
    return hits >= min_hits
