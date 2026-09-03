#!/usr/bin/env bash

# =============================================================================
# txt → md converter for billing and other notes
# Usage: ./convert_to_md.sh your_notes.txt
# Creates: your_notes.md
# Author: X/Claude
#
# Changes:
#   1.1  Removed trailing \" line-break markers and second-pass sed cleanup
#   1.3  Strip trailing colon from == section headings
#   1.4  Date persists across all == sections in the same date block
#   2.1  Bare email/phone lines get a labelled key (only when unlabelled)
#   2.4  Indented lines converted to Markdown list items
#   2.5  Extract rag-tags from the -*- header line
#   misc Inline " # comment" converted to em-dash on all line types
# =============================================================================

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <input.txt>"
    exit 1
fi

input="$1"
output="${input%.txt}.md"


# ----------------------------- Detect OS for date parsing -----------------------------
if [[ $(uname -s) == Darwin ]]; then
    DATE_CMD="date -j -f '%a %b %d %T %Y'"
else
    DATE_CMD="date -d"
fi


# ----------------------------- Extract title and first date for frontmatter -----------------------------
title=$(grep -m1 '^== ' "$input" | tr -d '\r' | sed 's/^== *//' | head -1 || true)
[[ -z "$title" ]] && title="Untitled Notes"

first_date=$(grep -E '^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ' "$input" | tr -d '\r' | head -1 || true)
if [[ -n "$first_date" ]]; then
    created=$($DATE_CMD "$first_date" +%Y-%m-%d 2>/dev/null || date +%Y-%m-%d)
else
    created=$(date +%Y-%m-%d)
fi

tags="[notes"
grep -qiE "medical|billing|scripps|ucsd|dermatology" "$input" && tags+=", medical, billing"
grep -qiE "lawyer|legal|court|estate|fiduciary|conservatorship" "$input" && tags+=", legal"

# ---- Extract rag-tags from the -*- header line (first line only) ----
# Matches:  -*- ... rag-tags:foo/bar/baz; ... -*-
# Tags are slash-separated and terminated by ";".  Whitespace around
# the value and individual tag names is trimmed.  The line itself is
# still suppressed from body output by the -.*-.*- filter in the loop.
rag_tags_raw=$(head -1 "$input" | tr -d '\r' \
    | grep -oiE 'rag-tags:[^;]+;' \
    | sed -E 's/rag-tags://i; s/;//' \
    | xargs || true)

if [[ -n "$rag_tags_raw" ]]; then
    IFS='/' read -ra _rtags <<< "$rag_tags_raw"
    for _t in "${_rtags[@]}"; do
        _t=$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$_t")
        [[ -n "$_t" ]] && tags+=", $_t"
    done
fi

# Deduplicate tags while preserving order ("notes" always first)
_seen=(); _deduped=""
IFS=', ' read -ra _all_tags <<< "${tags#[}"
for _tag in "${_all_tags[@]}"; do
    _tag=$(sed 's/^[[:space:]]*//; s/[[:space:]]*$//' <<< "$_tag")
    [[ -z "$_tag" ]] && continue
    _already=0
    for _s in "${_seen[@]:-}"; do [[ "$_s" == "$_tag" ]] && { _already=1; break; }; done
    if (( ! _already )); then
        _seen+=("$_tag")
        [[ -z "$_deduped" ]] && _deduped="$_tag" || _deduped+=", $_tag"
    fi
done
tags="[$_deduped]"


# ----------------------------- Write frontmatter -----------------------------
cat > "$output" <<EOF
---
title: $title
type: general_notes
created: $created
tags: $tags
---

# $title

EOF


# ----------------------------- Process the rest of the file -----------------------------
# current_date: ISO date of the current date block; persists across all == sections
#               in the same block (fix 1.4)
# pending_date: raw date string; cleared once used to emit a standalone date heading
#               for content that appears without a == section header
current_date=""
pending_date=""
in_paragraph=0
in_comment_block=0

while IFS= read -r line || [[ -n "$line" ]]; do
    line=$(tr -d '\r' <<< "$line")
    line="${line%"${line##*[![:space:]]}"}"

    [[ $line =~ ^[[:space:]]*-.*-.*- ]] && continue

    if [[ $line =~ ^[-=]{70,} ]]; then
        ((in_paragraph))     && { echo >> "$output"; in_paragraph=0; }
        ((in_comment_block)) && { echo "" >> "$output"; in_comment_block=0; }
        continue
    fi

    # Date line (e.g. "Sat Feb 21 11:50:24 2026")
    # current_date persists for the whole date block; pending_date is cleared on first use
    if [[ $line =~ ^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[[:space:]] ]]; then
        current_date=$($DATE_CMD "$line" +%Y-%m-%d 2>/dev/null || echo "")
        pending_date="$line"
        continue
    fi

    # Convert inline " # comment" to em-dash on any line type.
    # The space-hash-space pattern avoids touching URL fragment anchors (example.com#section)
    # and full-line comment lines handled below.
    if [[ ! $line == \#* ]]; then
        line=$(sed 's/ # / — /g' <<< "$line")
    fi

    # Section heading (e.g. "== My headline")
    if [[ $line == ==* ]]; then
        ((in_paragraph))     && { echo >> "$output"; in_paragraph=0; }
        ((in_comment_block)) && { echo "" >> "$output"; in_comment_block=0; }

        # Strip leading "== ", then strip trailing colon (fix 1.3)
        section=$(sed 's/^== *//' <<< "$line" | sed 's/:$//')

        # Skip the top-level document title (already used in frontmatter)
        [[ $section == "$title" ]] && continue

        echo >> "$output"
        # Use current_date (not pending_date) so date persists for all == sections
        # in the same date block (fix 1.4)
        if [[ -n "$current_date" ]]; then
            echo "## $current_date — $section" >> "$output"
        else
            echo "## $section" >> "$output"
        fi
        # Clear pending_date (the standalone-heading sentinel) but keep current_date
        pending_date=""
        echo "" >> "$output"
        continue
    fi

    # Standalone date heading: a date line followed by content with no == section
    if [[ -n "$pending_date" && -n "$line" ]]; then
        echo >> "$output"
        echo "## $current_date" >> "$output"
        echo "" >> "$output"
        pending_date=""
    fi

    # Full-line comment (e.g. "# Some note")
    if [[ $line == \#* ]]; then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        content=$(sed 's/^# *//' <<< "$line")
        if ((in_comment_block == 0)); then
            echo "> $content" >> "$output"
            in_comment_block=1
        else
            echo "> $content" >> "$output"
        fi
        continue
    fi

    if ((in_comment_block)) && [[ $line != \#* ]]; then
        echo "" >> "$output"
        in_comment_block=0
    fi

    # Status lines (DONE, PENDING, IN PROGRESS, etc.)
    if [[ $line =~ ^(DONE|PENDING|IN\ PROGRESS|BLOCKED|URGENT|TODO)([,[:space:]]|$) ]]; then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        status=$(sed -E 's/^([A-Z][A-Z ]+)([, ].*|)$/\1/' <<< "$line" | xargs)
        rest=$(sed -E "s/^${status// /\\ }[ ,]*//" <<< "$line")
        case $status in
            DONE)          emo="✅" ;;
            PENDING)       emo="⏳" ;;
            "IN PROGRESS") emo="🔄" ;;
            BLOCKED)       emo="⛔" ;;
            URGENT)        emo="🚨" ;;
            TODO)          emo="📝" ;;
            *)             emo="" ;;
        esac
        line_out="**Status: ${emo} ${status}**"
        [[ -n $rest ]] && line_out+=" — ${rest}"
        echo "${line_out}" >> "$output"
        continue
    fi

    # URL lines
    if [[ $line =~ ^https?:// || $line =~ ^www\. ]]; then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        echo "$line" >> "$output"
        continue
    fi

    # Detect indentation and strip it; used by email/phone/list handlers below
    is_indented=0
    content="$line"
    if [[ $line =~ ^[[:space:]]+[^[:space:]] ]]; then
        is_indented=1
        content=$(sed 's/^[[:space:]]*//' <<< "$line")
    fi
    list_prefix=$( ((is_indented)) && echo "- " || echo "" )

    # Email: content matches email pattern and has no existing Email: key — fix 2.1
    if [[ $content =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] && \
       [[ ! $content =~ ^[Ee]mail[[:space:]]*: ]]; then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        echo "${list_prefix}**Email:** ${content}" >> "$output"
        continue
    fi

    # Phone: content matches phone pattern and has no existing Phone: key — fix 2.1
    # Matches: 619-295-3123  (619) 295-3123  +1 619 295 3123  etc.
    if [[ $content =~ ^[+]?[0-9]{0,2}[-.]?[(]?[0-9]{3}[)]?[-.]?[0-9]{3}[-.]?[0-9]{4}$ ]] && \
       [[ ! $content =~ ^[Pp]hone[[:space:]]*: ]]; then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        echo "${list_prefix}**Phone:** ${content}" >> "$output"
        continue
    fi

    # Remaining indented lines → Markdown list items (fix 2.4)
    if ((is_indented)); then
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
        echo "- ${content}" >> "$output"
        continue
    fi

    # Key-value lines (e.g. "Name: Foo Bar")
    if [[ $line == *:* ]] && [[ ! $line =~ ^https?:// ]] && [[ ! $line =~ [0-9]:[0-9] ]]; then
        key_raw=$(cut -d: -f1 <<< "$line" | xargs)
        val=$(cut -d: -f2- <<< "$line" | sed 's/^ *//')
        if [[ $key_raw =~ ^[A-Za-z][A-Za-z0-9\ ]{1,40}$ ]] && [[ ! $key_raw =~ [0-9] ]]; then
            ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
            line_out="**${key_raw}:** ${val}"
            case $key_raw in
                TODO)   line_out="**TODO:** 📝 ${val}"   ;;
                URGENT) line_out="**URGENT:** 🚨 ${val}" ;;
            esac
            echo "${line_out}" >> "$output"
            continue
        fi
    fi

    # Plain text paragraph lines
    if [[ -n $line ]]; then
        ((in_paragraph==0)) && { echo >> "$output"; in_paragraph=1; }
        echo "$line" >> "$output"
    else
        ((in_paragraph)) && { echo >> "$output"; in_paragraph=0; }
    fi

done < "$input"


# Final cleanup
if ((in_paragraph || in_comment_block)); then
    printf "\n" >> "$output"
else
    echo "" >> "$output"
fi

echo "Converted: $input → $output"
