# HYR-05: Stale "do not re-attempt" line in step-5 requirements on main

- **Severity:** Low
- **Status:** Open
- **Component:** `Doc/step-5-requirements.md` (main) vs. branch `alternate`

## Impact
Documentation only. `main`'s step-5 doc contains a line saying not to re-attempt
an approach that was later investigated and documented on `alternate` (§5c-5j,
including §5f). A reader of `main` gets out-of-date guidance. The slide deck
cites only §5, §5a and §5b so that it stays consistent with `main`.

## Description
The `alternate` branch (commits `f74848a`, `25180be`) holds the extended
step-5 sections plus supporting code and scripts (metrics, benchmark and
live-agent tests). It has not been merged, so `main` and `alternate` disagree.

## Proposed fix
Choose one:
- **A:** Merge `alternate` into `main` after review (brings code changes too).
- **B:** Change the stale line on `main` to a short pointer to §5f on
  `alternate`, leaving the branch unmerged.
If A, update the deck's speaker notes to cite the new sections.

## Acceptance
`main`'s step-5 doc no longer contradicts the findings on `alternate`.
