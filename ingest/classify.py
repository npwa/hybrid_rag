"""Classification rules — step-1-requirements.md §4.

Precedence (first match wins):
  1. Trailing '~' or '#' in the filename -> excluded (editor backup/lock files)
  2. Filename matches README* or TODO* (case-insensitive) -> readme
     (TODO-named files get identical treatment to README-named files — same
     pattern-matching, same convert_to_md.sh conversion path.)
  3. Extension in the include whitelist -> include
  4. Extension in the exclude list -> excluded
  5. Otherwise -> unclassified (§4d — logged for periodic review, never silently dropped)
"""
from __future__ import annotations

import re

from ingest.config import Config


def classify(filename: str, config: Config) -> str:
    if filename.endswith(config.exclude_suffixes):
        return "excluded"

    if re.match(config.readme_todo_pattern, filename, re.IGNORECASE):
        return "readme"

    ext = extension_of(filename)

    if ext in config.include_extensions:
        return "include"

    if ext in config.exclude_extensions:
        return "excluded"

    return "unclassified"


def extension_of(filename: str) -> str:
    """Lowercased extension without the leading dot, '' if there isn't one."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()
