"""Parse logs/maintenance.log into runs. The result of a run is decided only by its own
'=== maintenance run end:' line - never by older lines (the false-FAILED bug fixed in triage.sh)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_TS = r"(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)"
_START = re.compile(rf"^{_TS} === maintenance run start ===")
_END = re.compile(rf"^{_TS} === maintenance run end: (?P<result>OK|FAILED) in (?P<secs>\d+)s ?(?P<rest>.*?) ===")
_COUNTS = re.compile(r"\(\+(\d+) ~(\d+) -(\d+)\)")
_STAGE = re.compile(rf"^{_TS} stage (?P<stage>\w+): (?P<state>ok|failed|start)\b")


@dataclass
class MaintenanceRun:
    started: str | None
    ended: str | None = None
    result: str | None = None               # OK | FAILED | None (still running or truncated)
    seconds: int | None = None
    added: int | None = None
    changed: int | None = None
    removed: int | None = None
    detail: str = ""
    stages: dict[str, str] = field(default_factory=dict)   # stage -> ok|failed
    index_ok_at: str | None = None          # timestamp of 'stage index: ok' in this run


def parse_runs(text: str) -> list[MaintenanceRun]:
    runs: list[MaintenanceRun] = []
    cur: MaintenanceRun | None = None
    for line in text.splitlines():
        if m := _START.match(line):
            cur = MaintenanceRun(started=m["ts"])
            runs.append(cur)
        elif m := _STAGE.match(line):
            if cur is not None and m["state"] != "start":
                cur.stages[m["stage"]] = m["state"]
                if m["stage"] == "index" and m["state"] == "ok":
                    cur.index_ok_at = m["ts"]
        elif m := _END.match(line):
            if cur is None:
                cur = MaintenanceRun(started=None)
                runs.append(cur)
            cur.ended, cur.result, cur.seconds = m["ts"], m["result"], int(m["secs"])
            cur.detail = m["rest"]
            if c := _COUNTS.search(m["rest"]):
                cur.added, cur.changed, cur.removed = (int(x) for x in c.groups())
            cur = None
    return runs


def read_runs(log_path: Path) -> list[MaintenanceRun]:
    try:
        return parse_runs(log_path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return []


def last_run(runs: list[MaintenanceRun]) -> MaintenanceRun | None:
    return runs[-1] if runs else None


def last_successful_index(runs: list[MaintenanceRun]) -> str | None:
    for r in reversed(runs):
        if r.index_ok_at:
            return r.index_ok_at
    return None


def hours_since(ts: str | None, now: datetime | None = None) -> float | None:
    if not ts:
        return None
    return ((now or datetime.now()) - datetime.fromisoformat(ts)).total_seconds() / 3600
