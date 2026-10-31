#!/usr/bin/env python3
"""Generate a deterministic, entirely fictional demo dataset for the operator console.

Output (default ./demo_data, git-ignored) mirrors the real working directory layout:
  manifest.db            files + chunks + FTS5 (same schema as ingest/manifest.py)
  lancedb/               table "chunks" with 768-d hashed bag-of-words vectors (console/demo_embed.py; NOT semantic)
  logs/maintenance.log   history with an old FAILED run followed by OK runs
  logs/query_*.log       text query logs in the real format, plus query_*.jsonl (same events)
  logs/agent/            OpenClaw-style JSON-lines logs + config-summary.json, consistent with the query logs
                         (a model change after 7 days, an MCP outage, text-instead-of-tool-call turns: SYNTHETIC;
                         the milestone 'model_response_received' and the WARN record carrying the looks-like text are invented)

Nothing here derives from real documents, paths, queries or phone numbers (tests check).
Same --seed gives byte-identical manifest content, which tests rely on.

Usage: scripts/make_synthetic_data.py [--out demo_data] [--seed 20261030] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.manifest import ChunkRecord, FileRecord, open_manifest  # noqa: E402

EPOCH = datetime(2026, 10, 1, 8, 0, 0)       # fixed "now" base so output is reproducible
NOW = datetime(2026, 10, 30, 21, 0, 0)

# Fictional corpus: folder -> (extension mix, topic words used to write chunk text)
FOLDERS = {
    "Gadgets/Manuals": (["pdf", "pdf", "txt"], ["widget", "calibration", "firmware", "torque", "warranty", "reset", "battery"]),
    "Gadgets/Receipts": (["pdf", "png", "jpg"], ["invoice", "receipt", "paid", "quantity", "subtotal", "shipping"]),
    "Garden/Plans": (["docx", "xlsx", "txt"], ["trellis", "compost", "irrigation", "raised bed", "mulch", "seedlings"]),
    "Travel/Trips": (["pdf", "html", "txt"], ["itinerary", "ferry", "booking", "luggage", "museum", "timetable"]),
    "Hobby/Notes": (["txt", "html", "md"], ["sketch", "palette", "workshop", "chisel", "varnish", "template"]),
    "Network/Setup": (["txt", "pdf"], ["router", "gateway", "subnet", "dhcp", "backup", "firewall", "switch"]),
}
FAIL_KINDS = [  # (error_message template, extension, weight, ocr_confidence)
    ("OCR produced no text", "png", 6, None),
    ("OCR produced no text", "jpg", 5, None),
    ("[Errno 13] Permission denied: '{path}'", "pdf", 3, None),
    ("PDF is damaged: cannot open document", "pdf", 1, None),
    ("OCR confidence {conf} below failure threshold 40.0", "pdf", 3, None),
    ("[Errno 13] Permission denied: '{path}'", "docx", 1, None),
]
QUESTIONS = [
    "how do I reset the demo widget", "when does the ferry to the island leave",
    "what is the warranty period for the model A gadget", "which seedlings go in the raised bed",
    "what is the subnet of the guest network", "how much was the shipping on the last invoice",
    "where did I store the firewall backup", "which museum is on the itinerary",
    "what torque for the widget bracket", "how do I calibrate the sensor",
    "demo router external address", "list the compost schedule",
]
MODELS = ["ollama/qwen2.5:14b-instruct", "ollama/qwen3.6:35b-a3b"]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _sha(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def make_manifest(out: Path, rng: random.Random) -> list[dict]:
    """Returns the list of chunk dicts (with vectors added later) for the vector store."""
    db = out / "manifest.db"
    chunks_out: list[dict] = []
    n_files = 0
    with open_manifest(db) as m:
        m.ensure_fts5("chunks_fts")
        for folder, (exts, words) in FOLDERS.items():
            for i in range(rng.randint(14, 22)):
                n_files += 1
                ext = rng.choice(exts)
                name = f"{rng.choice(words).replace(' ', '-')}-{n_files:03d}.{ext}"
                rel = f"{folder}/{name}"
                fid = _sha("file", rel)
                mtime = _iso(EPOCH + timedelta(hours=rng.randint(0, 600)))
                roll = rng.random()
                ocr = ext in ("pdf", "png", "jpg") and rng.random() < 0.3
                conf = round(rng.uniform(55, 96), 1) if ocr else None
                status = "ocr_extracted" if ocr else "extracted"
                if roll > 0.97:
                    status = "ocr_low_confidence"; conf = round(rng.uniform(40.5, 52), 1); ocr = True
                m.upsert(FileRecord(
                    file_id=fid, abs_path=f"/demo/Documents/{rel}", rel_path=rel, filename=name, extension=ext,
                    size_bytes=rng.randint(2_000, 900_000), mtime=mtime, content_hash=_sha("c", rel),
                    category="include", status=status, ocr_used=ocr, ocr_confidence=conf,
                    tags=["notes"] if ext in ("txt", "md") else None, last_processed=mtime))
                for ci in range(rng.randint(2, 5)):
                    text = " ".join(rng.choice(words) + ("" if rng.random() < 0.8 else ".") for _ in range(rng.randint(40, 90)))
                    text = f"Demo document {name}. {text}"
                    cid = _sha("chunk", fid, str(ci))
                    m.insert_chunk(ChunkRecord(
                        chunk_id=cid, file_id=fid, chunk_index=ci, text=text, char_start=ci * 800,
                        char_end=ci * 800 + len(text), source_content_hash=_sha("c", rel), rel_path=rel,
                        category="include", extension=ext, ocr_used=ocr, ocr_confidence=conf,
                        embedding_status="embedded", created_at=mtime))
                    chunks_out.append(dict(chunk_id=cid, file_id=fid, rel_path=rel, category="include", extension=ext,
                                           tags="", sheet_name="", ocr_used=bool(ocr), ocr_confidence=conf or 0.0, text=text))
                    m.fts5_insert_batch("chunks_fts", [dict(chunk_id=cid, text=text, rel_path=rel, tags=None)])
        # failures, skipped, excluded, encrypted, lock files, empty
        total_w = sum(k[2] for k in FAIL_KINDS)
        for i in range(60):
            n_files += 1
            pick, acc = rng.uniform(0, total_w), 0
            for tmpl, ext, w, _ in FAIL_KINDS:
                acc += w
                if pick <= acc:
                    break
            rel = f"Scans/Batch{rng.randint(1, 4)}/scan-{n_files:03d}.{ext}"
            fid = _sha("file", rel)
            conf = round(rng.uniform(0, 39), 1)
            err = tmpl.format(path=f"/demo/Documents/{rel}", conf=conf)
            m.upsert(FileRecord(file_id=fid, abs_path=f"/demo/Documents/{rel}", rel_path=rel, filename=rel.rsplit("/", 1)[1],
                                extension=ext, size_bytes=rng.randint(1_000, 400_000), mtime=_iso(EPOCH),
                                content_hash=None, category="include", status="failed", error_message=err,
                                last_processed=_iso(EPOCH + timedelta(days=rng.randint(0, 29)))))
        for i in range(8):
            n_files += 1
            rel = f"Garden/Plans/~$plan-{i}.docx"
            m.upsert(FileRecord(file_id=_sha("file", rel), abs_path=f"/demo/Documents/{rel}", rel_path=rel,
                                filename=f"~$plan-{i}.docx", extension="docx", size_bytes=162, mtime=_iso(EPOCH),
                                content_hash=None, category="include", status="failed",
                                error_message="python-docx: file is not a zip file (Office lock file)", last_processed=_iso(EPOCH)))
        for status, count, cat in (("skipped", 40, "excluded"), ("encrypted", 3, "include"), ("empty", 2, "include")):
            for i in range(count):
                n_files += 1
                rel = f"Other/{status}/file-{i:03d}.bin"
                m.upsert(FileRecord(file_id=_sha("file", rel), abs_path=f"/demo/Documents/{rel}", rel_path=rel,
                                    filename=f"file-{i:03d}.bin", extension="bin", size_bytes=rng.randint(100, 5000),
                                    mtime=_iso(EPOCH), content_hash=None, category=cat, status=status, last_processed=_iso(EPOCH)))
        m.commit()
    return chunks_out


def make_vectors(out: Path, rows: list[dict], rng: random.Random) -> None:
    import lancedb
    import pyarrow as pa
    from console.demo_embed import DIM as dim, embed_text      # words -> vectors, so demo queries find demo chunks
    data = [{**r, "vector": embed_text(r["text"])} for r in rows]
    schema = pa.schema([
        ("chunk_id", pa.string()), ("vector", pa.list_(pa.float32(), dim)), ("file_id", pa.string()),
        ("rel_path", pa.string()), ("category", pa.string()), ("extension", pa.string()), ("tags", pa.string()),
        ("sheet_name", pa.string()), ("ocr_used", pa.bool_()), ("ocr_confidence", pa.float64()), ("text", pa.string()),
    ])
    db = lancedb.connect(str(out / "lancedb"))
    db.create_table("chunks", data=data, schema=schema, mode="overwrite")


def make_maintenance_log(out: Path, rng: random.Random) -> None:
    lines = []
    # day 0: failed run, then a retry that succeeds, then regular daily-ish runs
    runs = [(NOW - timedelta(days=35, hours=-1), False)] + [(NOW - timedelta(days=d, hours=-1), True) for d in (34, 20, 6, 0)]
    for start, ok in runs:
        t = start
        lines.append(f"{_iso(t)} === maintenance run start ===")
        if not ok:
            lines.append(f"{_iso(t + timedelta(seconds=1))} === maintenance run end: FAILED in 1s (no ingest result) ===")
            lines.append(f"{_iso(t + timedelta(seconds=1))} REPORT subject: [hybrid-rag maintenance] FAILED at ingest stage — 1s")
            continue
        a, c, d = rng.randint(1, 20), rng.randint(0, 6), 0
        lines.append(f"{_iso(t + timedelta(seconds=4))} stage ingest: ok (4s) added={a} changed={c} removed={d}")
        lines.append(f"{_iso(t + timedelta(seconds=5))} stage chunk: ok (0s) stage=chunk elapsed=0.2 chunked={a + c} unchanged=1300 chunks_created={(a + c) * 5} chunks_marked_deleted=0 failed=0")
        lines.append(f"{_iso(t + timedelta(seconds=9))} stage index: ok (4s) stage=index elapsed=2.2 embedded_chunks={(a + c) * 5} chunks_cleaned_up=0 embed_batch_failures=0")
        lines.append(f"{_iso(t + timedelta(seconds=9))} === maintenance run end: OK in 9s (+{a} ~{c} -{d}) ===")
        lines.append(f"{_iso(t + timedelta(seconds=9))} REPORT subject: [hybrid-rag maintenance] OK — 9s — +{a} ~{c} -{d}")
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "maintenance.log").write_text("\n".join(lines) + "\n")


def make_activity(out: Path, rng: random.Random, sources_pool: list[str]) -> None:
    """Query logs (text + JSONL) and the matching OpenClaw agent logs for 14 days.

    Story the demo tells: days 1-7 the agent model is a small one that often writes a tool call as text instead of
    calling it; from day 8 a larger model is used and almost every turn calls the tool; one day the MCP server was down
    for part of the morning (connect failure, agent starts the tool, the desktop never sees a request)."""
    logs = out / "logs"
    agent = logs / "agent"
    agent.mkdir(parents=True, exist_ok=True)
    SMALL, BIG = MODELS
    days = [(NOW - timedelta(days=13 - d)).date() for d in range(14)]
    outage_day = days[10]

    def rec(sub, msg, when, level="INFO"):
        return json.dumps({"0": json.dumps({"subsystem": sub}), "1": msg,
                           "_meta": {"hostname": "demo-bot", "date": (when + timedelta(hours=7)).strftime("%Y-%m-%dT%H:%M:%S.000Z"), "logLevelName": level},
                           "time": when.strftime("%Y-%m-%dT%H:%M:%S.000-07:00")})

    run_n = 0
    for d_i, day in enumerate(days):
        model = SMALL if d_i < 7 else BIG
        text_lines, jsonl_lines, agent_lines = [], [], []
        t0 = datetime(day.year, day.month, day.day, 6, 55, 0)
        agent_lines.append(rec("gateway", "gateway ready", t0))
        agent_lines.append(rec("gateway", f"agent model: {model} (thinking=medium, fast=off)", t0))
        if day == outage_day:
            agent_lines.append(rec("agent/embedded", 'MCP: failed to start server "hybrid-rag": connect ECONNREFUSED 192.0.2.10:8200', t0 + timedelta(minutes=1), "ERROR"))
            agent_lines.append(rec("gateway/health", "host timing gap detected: process was frozen ~32123198ms; restarting channels when idle and refreshing health", t0 + timedelta(minutes=2), "WARN"))
        if day == days[12]:
            agent_lines.append(rec("memory", "memory sync failed (automatic candidates): Memory sync aborted: embedding provider is unavailable", t0 + timedelta(minutes=3), "WARN"))
        events = []
        for _ in range(rng.randint(3, 8)):
            t = datetime(day.year, day.month, day.day, rng.randint(7, 22), rng.randint(0, 59), rng.randint(0, 59))
            kind = rng.random()
            caller = rng.choices(["mcp", "cli", "http"], weights=[70, 20, 10])[0]
            events.append((t, rng.choice(QUESTIONS), kind, caller))
        for t, q, kind, caller in sorted(events):
            secs = round(rng.choice([0.4, 0.7, 2.0, 6.0, 6.5, 14.2, 41.0]), 2)
            srcs = rng.sample(sources_pool, 8)
            if kind < 0.15:
                outcome, err = "no_relevant", None
                text_lines.append(f"{_iso(t)} INFO     QUERY '{q}' -> not relevant, fallback disabled")
                secs = round(rng.uniform(0.05, 0.4), 2); srcs = []
            elif kind < 0.2:
                outcome, err = "error", "embedding failed: could not reach Ollama at http://localhost:11434: timed out"
                text_lines.append(f"{_iso(t)} WARNING  QUERY_EMBED_FAILED '{q}': could not reach Ollama at http://localhost:11434: timed out")
                secs = 60.0; srcs = []
            else:
                outcome, err = "answered", None
                text_lines.append(f"{_iso(t)} INFO     QUERY '{q}' -> 8 sources, {secs}s [{', '.join(srcs)}]")
                text_lines.append(f"{_iso(t)} INFO     QUERY '{q}' fusion detail: {srcs[0]} branch=dense+sparse rrf=0.03279 dense(rank=1,dist=0.70) sparse(rank=1,bm25=-27.7); {srcs[1]} branch=dense rrf=0.01613 dense(rank=2,dist=0.79)")
                text_lines.append(f"{_iso(t)} INFO     QUERY '{q}' generation: 24 tokens in 0.23s (104.4 tok/s)")
            jsonl_lines.append(json.dumps({
                "schema": 1, "ts": _iso(t), "query": q, "caller": caller, "outcome": outcome, "error": err, "n_sources": len(srcs),
                "sources": [{"rel_path": x, "chunk_id": _sha("c", x), "branch": "dense+sparse" if i == 0 else "dense", "rrf_score": 0.03 - i * 0.001,
                             "dense_rank": i + 1, "dense_distance": 0.7 + i * 0.01, "sparse_rank": 1 if i == 0 else None, "sparse_bm25": -27.7 if i == 0 else None}
                            for i, x in enumerate(srcs)],
                "total_s": secs, "embed_s": 0.04, "retrieve_s": round(min(secs, 0.2), 3), "gen_s": round(max(secs - 0.25, 0), 3) if outcome == "answered" else None,
                "gen_tokens": None, "tok_per_s": None, "distance_threshold": 0.85, "min_hits": 1}))
            if caller != "mcp":
                continue
            run_n += 1
            run_id = f"demo-run-{run_n:04d}"
            start = t - timedelta(seconds=secs)
            if day == outage_day and t.hour < 12:
                # tool started by the agent but the request never reached the desktop: drop the desktop record again
                text_lines = [l for l in text_lines if not (l.startswith(_iso(t)) and f"'{q}'" in l)]
                jsonl_lines.pop()
            if d_i < 7 and rng.random() < 0.35:                    # small model writes the call as text
                agent_lines.append(rec("auto-reply/agent-turn-timing", {"runId": run_id, "sessionKey": "agent:main:main", "milestone": "model_response_received", "totalMs": rng.randint(4000, 20000)}, start))
                agent_lines.append(rec("agent/embedded", {"runId": run_id, "message": LOOKS_LIKE_TEXT}, start, "WARN"))
                text_lines = [l for l in text_lines if not (l.startswith(_iso(t)) and f"'{q}'" in l)]
                jsonl_lines.pop()
                continue
            ttt = rng.choice([3200, 5400, 9800, 21000, 50248]) if d_i >= 7 else rng.choice([7000, 14000, 33000])
            agent_lines.append(rec("auto-reply/agent-turn-timing", {
                "runId": run_id, "sessionKey": "agent:main:main", "milestone": "tool_execution_started", "totalMs": ttt,
                "spans": [{"name": "fallback_prepare_harness", "durationMs": 0, "elapsedMs": 6}]}, start - timedelta(seconds=0.6)))
        if day == days[9]:
            agent_lines.append(rec("gateway", "[cron:demo] This automation uses ollama/qwen3.6:35b-a3b but the local provider preflight failed at http://192.0.2.10:11434. Last error: Local provider preflight exceeded its configured 2500ms deadline | request timed out", t0 + timedelta(minutes=4), "WARN"))
        agent_lines.sort(key=lambda l: json.loads(l)["time"])
        text_lines.sort()
        (logs / f"query_{day.isoformat()}.log").write_text("\n".join(text_lines) + ("\n" if text_lines else ""))
        (logs / f"query_{day.isoformat()}.jsonl").write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""))
        (agent / f"openclaw-{day.isoformat()}.log").write_text("\n".join(agent_lines) + "\n")
    (agent / "config-summary.json").write_text(json.dumps({
        "mcp_url": "http://192.0.2.10:8200/mcp", "mcp_enabled": True, "tools_allow_has_tool": True,
        "sandbox_alsoAllow_has_tool": True, "primary_model": BIG}, indent=1) + "\n")


LOOKS_LIKE_TEXT = "Assistant reply looks like a tool call, but no structured tool invocation was emitted"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="demo_data")
    ap.add_argument("--seed", type=int, default=20261030)
    ap.add_argument("--force", action="store_true", help="replace an existing output directory")
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        if not args.force:
            print(f"{out} exists; use --force to replace it", file=sys.stderr)
            return 1
        shutil.rmtree(out)
    out.mkdir(parents=True)
    rng = random.Random(args.seed)
    chunks = make_manifest(out, rng)
    make_vectors(out, chunks, rng)
    make_maintenance_log(out, rng)
    make_activity(out, rng, sorted({c["rel_path"] for c in chunks}))
    print(f"wrote demo dataset to {out}: {len(chunks)} chunks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
