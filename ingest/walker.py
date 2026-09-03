"""Recursive file walk over the source root — §3.

Symlinks are never followed (hard rule — avoids loops / escaping the source
tree) and are always logged, regardless of the hidden-file config toggle.
Hidden files/directories (dotfiles) are pruned by default, configurable.
"""
from __future__ import annotations

import dataclasses
import logging
import os
from pathlib import Path
from typing import Iterator

from ingest.config import Config

log = logging.getLogger("ingest")


@dataclasses.dataclass
class WalkEntry:
    abs_path: Path
    rel_path: str


def _is_hidden(name: str) -> bool:
    return name.startswith(".")


def walk(config: Config, on_symlink=None) -> Iterator[WalkEntry]:
    """Yields WalkEntry for every regular file under config.source_root.

    on_symlink(abs_path) is called for every symlink encountered (file or dir)
    so the caller can log it; symlinks are always skipped, never followed.

    A directory os.walk cannot list (permission denied, etc.) is logged and
    skipped rather than silently dropped or aborting the whole walk (§3).
    """
    root = config.source_root

    def _onerror(err: OSError) -> None:
        log.warning("DIR_PERMISSION_ERROR %s: %s", err.filename, err)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_onerror):
        dirnames.sort()
        kept_dirs = []
        for d in dirnames:
            full = Path(dirpath) / d
            try:
                is_link = full.is_symlink()
            except OSError as e:
                log.warning("DIR_PERMISSION_ERROR %s: %s", full, e)
                continue
            if is_link:
                if on_symlink:
                    on_symlink(full)
                continue
            if config.exclude_hidden and _is_hidden(d):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in sorted(filenames):
            full = Path(dirpath) / fname
            try:
                is_link = full.is_symlink()
            except OSError as e:
                log.warning("FILE_PERMISSION_ERROR %s: %s", full, e)
                continue
            if is_link:
                if on_symlink:
                    on_symlink(full)
                continue
            if config.exclude_hidden and _is_hidden(fname):
                continue

            rel = full.relative_to(root).as_posix()
            yield WalkEntry(abs_path=full, rel_path=rel)
