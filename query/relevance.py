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
the threshold, not just one outlier.

    query                                    distances (top 3)      hits<0.7   verdict
    "adjusted gross income 2024"             0.58, 0.60, 0.60        3         relevant
    "who monitors the home alarm system"     0.65, 0.65, 0.79        2         relevant
    "who was wolfgang amadeus mozart"        0.49, 0.91, 0.97        1         NOT relevant (false lead)
    "how many moons does jupiter have"       0.91, 0.92, 0.93        0         NOT relevant
    "last flew to Palo Alto"                 0.57, 0.85, 0.90        1         relevant (real, single-source)
    "Thule Evolution 1800 sale price"        0.72, 0.87, 0.87        0         relevant (terse/list-style doc)

An initial `min_hits=2` correctly rejected the Mozart false lead, but it also rejects
any real fact that only lives in one chunk of the corpus — exactly the Palo Alto case
above, where the top-1 distance (0.57) is a genuine match but nothing else in the
corpus corroborates it. No distance-based rule can cleanly tell these two apart: the
Mozart false lead's top-1 (0.49) is actually *closer* than Palo Alto's true top-1
(0.57). Given that, `min_hits=1` is the safer choice — the asymmetry matters more than
the ambiguity: a false negative here refuses a real answer outright, while a false
positive only costs one extra generation call, which already declines correctly when
the retrieved excerpts don't substantiate an answer (confirmed above: Mozart still
gets "I don't know" even after passing this gate). So the gate stays a fast-path
optimization for the clearly-nothing-relevant case (Jupiter's moons: 0 hits), not the
last line of defense against hallucination — that job belongs to generation itself.

Even with `min_hits=1`, `distance_threshold=0.7` was still too tight: the Thule case
above is a real, single-chunk answer (a terse listing — dimensions, bullet points, a
bare "$400 ... SOLD DONE" — with no full-sentence prose to embed closely against a
natural-language question) landing at 0.72, just over the cutoff. Across every real
match measured so far (0.49 low end for a false lead aside, 0.49-0.72 for genuine
matches) versus every genuinely-nothing-relevant case (0.91+), there's a wide, safe gap
between 0.72 and 0.91 — so `distance_threshold` was raised to **0.85**, comfortably
inside that gap. This still correctly rejects Jupiter's moons (0.91) while no longer
false-negatives on terse/list-style source documents.
"""
from __future__ import annotations


def has_relevant_results(dense_results: list[dict], distance_threshold: float, min_hits: int) -> bool:
    hits = sum(1 for r in dense_results if r["_distance"] < distance_threshold)
    return hits >= min_hits
