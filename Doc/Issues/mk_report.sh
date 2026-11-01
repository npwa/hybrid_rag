#!/usr/bin/env bash
# Build status_summary.md from the HYR-*.md tickets in this folder.
# Usage: Doc/Issues/mk_report.sh [OUTFILE]      (default: status_summary.md next to this script)
# Sections: Open, Fixed (waiting for verification), Closed, each sorted by severity. A ticket needs "# HYR-NN: title", "- **Severity:** ..." and "- **Status:** ..." lines (optional "- **Component:** ...").
# Status words: Open -> unresolved; Fixed -> its own "waiting for verification" section; Closed/Resolved/
# Verified/Won't fix/Duplicate -> closed (listed at the bottom). Anything else is shown as unresolved.
set -eu
cd "$(dirname "${BASH_SOURCE[0]}")"
OUT="${1:-status_summary.md}"
TMP=$(mktemp); trap 'rm -f "$TMP"' EXIT

field() { sed -n -E "s/^- \*\*$2:\*\* *//p" "$1" | head -1; }

for f in HYR-*.md; do
  id="${f%.md}"
  title=$(head -1 "$f" | sed -E 's/^# *HYR-[0-9]+: *//')
  sev=$(field "$f" Severity); st=$(field "$f" Status); comp=$(field "$f" Component)
  sevw=$(sed -E 's/[ (].*//' <<<"$sev"); sevw=${sevw:-Unknown}
  case "$(tr 'A-Z' 'a-z' <<<"$sevw")" in critical) rank=0;; high) rank=1;; medium) rank=2;; low-medium) rank=3;; low) rank=4;; *) rank=5;; esac
  case "$(tr 'A-Z' 'a-z' <<<"$st")" in
    open*) grp=1; state="Open";;
    fixed*) grp=2; state="Fixed, to verify";;
    closed*|resolved*|verified*|"won't fix"*|duplicate*) grp=3; state="Closed";;
    *) grp=1; state="Open?";;
  esac
  note=$(sed -E 's/^[A-Za-z][A-Za-z ]*(\(|;|,|$)/\1/; s/^[(;, ]+//; s/\)$//' <<<"$st" | awk '{print (length($0) > 110) ? substr($0, 1, 107) "..." : $0}')
  esc() { sed 's/|/\\|/g' <<<"$1"; }
  # sort key: group, severity rank, id
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$grp" "$rank" "$id" "$sevw" "$state" "$(esc "$title")" "$(esc "${note:--}")" "$(esc "${comp:--}")" >> "$TMP"
done
sort -t$'\t' -k1,1n -k2,2n -k3,3 -o "$TMP" "$TMP"

count() { awk -F'\t' -v g="$1" '$1==g' "$TMP" | wc -l; }
total=$(wc -l < "$TMP"); n_open=$(count 1); n_fix=$(count 2); n_closed=$(count 3)
top=$(awk -F'\t' '$1<3' "$TMP" | sort -t$'\t' -k2,2n | head -1 | cut -f4)

rows() { awk -F'\t' -v g="$1" '$1==g {printf "| [%s](%s.md) | %s | %s | %s |\n", $3, $3, $4, $6, $7}' "$TMP"; }

{
  echo "# Issue status summary"
  echo
  echo "Generated $(date '+%Y-%m-%d %H:%M') by \`Doc/Issues/mk_report.sh\` from the ticket files in this folder. Do not edit by hand."
  echo
  echo "## Overview"
  echo
  echo "- $total tickets: **$n_open open**, **$n_fix fixed and waiting for verification**, **$n_closed closed**."
  [ -n "$top" ] && echo "- Highest severity still open or unverified: **$top**."
  echo "- By severity (open and to-verify): $(awk -F'\t' '$1<3 {c[$2 SUBSEP $4]++} END {for (k in c) {split(k, p, SUBSEP); print p[1] "\t" p[2] " " c[k]}}' "$TMP" | sort -n | cut -f2 | paste -sd, - | sed 's/,/, /g')."
  echo "- \"Fixed, waiting for verification\" means the change exists but the ticket's acceptance check has not been recorded as passed; set its status to Closed once it has."
  echo
  echo "## Open (most severe first)"
  echo
  echo "| ID | Severity | Title | Note |"
  echo "|---|---|---|---|"
  rows 1
  echo
  echo "## Fixed, waiting for verification"
  echo
  if [ "$n_fix" -eq 0 ]; then echo "None."; else
    echo "| ID | Severity | Title | Note |"; echo "|---|---|---|---|"; rows 2
  fi
  echo
  echo "## Closed"
  echo
  if [ "$n_closed" -eq 0 ]; then echo "None yet."; else
    echo "| ID | Severity | Title | Note |"; echo "|---|---|---|---|"; rows 3
  fi
} > "$OUT"
echo "wrote $(pwd)/$OUT ($total tickets: $n_open open, $n_fix to verify, $n_closed closed)"
