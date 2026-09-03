"""txt/text/md files and README/TODO handling — §4b, §6."""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from charset_normalizer import from_path

from ingest.config import Config
from ingest.extractors import ExtractionResult

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_TAGS_LINE_RE = re.compile(r"^tags:\s*\[(.*?)\]\s*$", re.MULTILINE)


def _parse_frontmatter_tags(md_text: str) -> list[str] | None:
    """Pull the `tags: [a, b, c]` line out of convert_to_md.sh's YAML frontmatter
    (which already merges the source's `rag-tags:` header with its own auto-tags)."""
    fm_match = _FRONTMATTER_RE.match(md_text)
    if not fm_match:
        return None
    tags_match = _TAGS_LINE_RE.search(fm_match.group(1))
    if not tags_match:
        return None
    tags = [t.strip() for t in tags_match.group(1).split(",") if t.strip()]
    return tags or None


def _read_with_encoding_detection(path: Path) -> str:
    """Source files may not be UTF-8 — don't assume (§6)."""
    result = from_path(str(path)).best()
    if result is None:
        # Fall back to a lossy decode rather than failing outright.
        return path.read_bytes().decode("utf-8", errors="replace")
    return str(result)


def extract_plain_text(path: Path) -> ExtractionResult:
    try:
        content = _read_with_encoding_detection(path)
    except OSError as e:
        return ExtractionResult(status="failed", error_message=str(e))
    return ExtractionResult(status="extracted", text=content)


def extract_readme(path: Path, config: Config) -> ExtractionResult:
    if path.suffix.lower() == ".md":
        # Already-normalized Markdown — include directly, no conversion (§4b).
        try:
            content = _read_with_encoding_detection(path)
        except OSError as e:
            return ExtractionResult(status="failed", error_message=str(e))
        return ExtractionResult(status="extracted", text=content)

    return _convert_readme_via_script(path, config)


def _convert_readme_via_script(path: Path, config: Config) -> ExtractionResult:
    script = config.convert_to_md_script
    if not script.exists():
        return ExtractionResult(status="failed", error_message=f"convert_to_md.sh not found at {script}")

    with tempfile.TemporaryDirectory(prefix="readme_convert_") as tmpdir:
        tmp_input = Path(tmpdir) / path.name
        try:
            shutil.copyfile(path, tmp_input)
        except OSError as e:
            return ExtractionResult(status="failed", error_message=f"copy for conversion failed: {e}")

        try:
            proc = subprocess.run(
                [str(script), tmp_input.name],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return ExtractionResult(status="failed", error_message=f"convert_to_md.sh invocation failed: {e}")

        # Mirror the script's own suffix logic: strips a trailing ".txt" then appends ".md".
        if tmp_input.name.endswith(".txt"):
            expected_output = Path(tmpdir) / (tmp_input.name[: -len(".txt")] + ".md")
        else:
            expected_output = Path(tmpdir) / (tmp_input.name + ".md")

        if proc.returncode != 0:
            return ExtractionResult(
                status="failed",
                error_message=f"convert_to_md.sh exited {proc.returncode}: {proc.stderr.strip()[:500]}",
            )

        if not expected_output.exists():
            return ExtractionResult(
                status="failed",
                error_message=f"convert_to_md.sh reported success but {expected_output.name} was not created",
            )

        try:
            content = _read_with_encoding_detection(expected_output)
        except OSError as e:
            return ExtractionResult(status="failed", error_message=f"could not read conversion output: {e}")

    tags = _parse_frontmatter_tags(content)
    return ExtractionResult(status="extracted", text=content, tags=tags)
