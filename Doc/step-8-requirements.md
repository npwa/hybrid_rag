# Step 8 Requirements: Maintenance Loop

See `README.md`'s high-level plan, step 8: "A way to detect new/changed files in
Documents and incrementally re-index them, rather than rebuilding everything each
time."

## 1. Scope & Environment

The per-stage incremental machinery already exists and is verified — Steps 1-4
(`run_ingest.py`, `run_chunk.py`, `run_index.py`) are each independently idempotent,
confirmed to only process new/changed files and skip everything else on a rerun
(`Doc/step-1-requirements.md` §8, `Doc/step-3-requirements.md` §5,
`Doc/step-4-requirements.md` §4). File deletion cascades through all three stages too:
ingestion soft-deletes a manifest row when a file disappears from disk
(`ingest/pipeline.py::run`, the `stale` set), chunking soft-deletes that file's old
chunks (`chunking/pipeline.py`, `mark_chunks_deleted_for_file`), and indexing purges
those from LanceDB/FTS5 (`indexing/pipeline.py`, `chunks_cleaned_up`).

What Step 8 actually adds is everything *around* that: chaining the three stages into
one command, running that command automatically on a schedule, and reporting what
happened each time. Confirmed decisions per the user: bash for orchestration, cron for
the daily trigger, and each run logs elapsed time plus files added/updated/removed.

## 2. Orchestration — bash

A bash script, `run_maintenance.sh`, chains the three existing entrypoints in sequence:

```bash
./run_ingest.py --config config/ingest_config.yaml
./run_chunk.py  --config config/chunk_config.yaml
./run_index.py  --config config/index_config.yaml
```

Bash is a reasonable fit here specifically because each stage is already a complete,
independent CLI tool with a meaningful exit code and its own structured summary output
— the orchestrator's job is just sequencing, exit-code checking, timing, and log
aggregation, not any data manipulation. There's no parsing/transforming of file
contents happening in the orchestrator itself, which is where bash tends to get painful.

**Fail-fast, not fail-soft.** Each stage's output is a real dependency of the next:
chunking reads what ingestion wrote to the manifest, indexing reads what chunking wrote.
Running chunking against a partially-failed ingest, or indexing against partially-failed
chunking, risks quietly indexing an incomplete or inconsistent state — worse than just
stopping and trying again on the next scheduled run. So the orchestrator checks each
stage's exit code and stops immediately on nonzero, skipping the remaining stages for
that run.

## 3. Trigger — cron, daily

A single crontab entry invokes `run_maintenance.sh` once a day, e.g.:

```cron
0 3 * * * /home/npalmass/work/hybrid_rag/run_maintenance.sh >> /home/npalmass/work/hybrid_rag/logs/maintenance_cron.log 2>&1
```

**Cron-environment gotcha to design around**: cron runs jobs with a minimal
environment — no interactive shell's `PATH`, no `.bashrc`/`.profile`, and critically, no
activated venv. `run_maintenance.sh` must not assume `source .venv/bin/activate` has
happened or that `python3`/`./run_ingest.py`'s shebang resolves to the project's venv —
it needs to invoke the venv's interpreter by absolute path
(`/home/npalmass/work/hybrid_rag/.venv/bin/python3 run_ingest.py ...`) or explicitly
`source` the venv's `activate` script itself at the top of the script, using an absolute
path, not a relative one (cron's working directory is not the script's directory unless
the script `cd`s there first).

## 4. Per-run reporting — added/updated/removed, and a real gap found

Auditing what each stage already exposes, to see what the orchestrator can just read
versus what needs a small code change first:

- **Chunking (Step 3)** already tracks genuine per-run counts in a fresh local dict each
  run (`chunking/pipeline.py::run`, the `counts` variable): `chunked` (new or changed
  this run), `unchanged`, plus `chunks_created` and `chunks_marked_deleted`. This is
  exactly the signal needed — no changes required.
- **Indexing (Step 4)** is the same pattern (`indexing/pipeline.py::run`):
  `embedded_chunks`, `chunks_cleaned_up`, etc. are per-run deltas already. No changes
  required.
- **Ingestion (Step 1) is the odd one out.** `ingest/pipeline.py::run` returns only
  `{"processed": N}` — total files walked this run, not split into new vs. updated vs.
  unchanged — and `run_ingest.py`'s printed summary comes from `manifest.status_counts()`,
  which is a *cumulative* count across every file the manifest has ever seen, not a
  per-run delta. The one per-run count that *is* already computed internally is
  deletions (`len(stale)`, logged as `"DELETED %d file(s) no longer present on disk"`)
  — it's just not returned from `run()` or included in the printed summary.

**Required code change before Step 8's logging requirement can be met accurately**:
`ingest/pipeline.py::run` needs to track and return real per-run counts — at minimum
`new_files`, `updated_files`, `unchanged_files`, and `deleted_files` (the last one
already computed, just needs exposing). Whether "new vs. updated" is already
distinguishable per-file inside the worker (it must check the file against the existing
manifest row to decide whether to reprocess at all, so the information likely already
exists at that point) or needs adding is something to confirm when this is implemented,
not assumed here.

## 5. What "the result of a run" means

Each `run_maintenance.sh` invocation logs one consolidated summary (in addition to each
stage's own existing per-stage log file) covering:

- Overall start time, end time, and total elapsed time across all three stages
- Per-stage: added / updated / removed counts, and pass/fail
- Which stage failed and why, if the run didn't complete all three

This is a fourth log, distinct from the three stages' own logs
(`ingest_config.yaml`/`chunk_config.yaml`/`index_config.yaml`'s `logs_dir`) — a
maintenance-run-level rollup, not a replacement for the detailed per-stage logs. It's
append-only — no rotation or retention policy, by explicit decision, matching how the
per-stage logs already behave.

**Resolved — reporting is email, on every completion.** Confirmed this machine already
has working outbound mail: Postfix is installed and running (`systemctl status
postfix`), configured with a real relay
(`relayhost = [192.168.1.18]:25` in `postconf -n`) rather than local-only delivery, and
`mailutils` (the `mail` command) is installed alongside it. So `run_maintenance.sh` ends
by piping the run summary through `mail -s "<subject>" "$MAINTENANCE_REPORT_EMAIL"` — no
new dependency, no new service to stand up. One email per run (success or failure), not
just on failure, so a silently-stuck cron job (e.g. cron itself misconfigured, or the
job never firing at all) is still noticeable by its absence of a daily email rather than
being invisible. Subject line carries the headline (status + duration) so it's readable
without opening the email, e.g.:

```
Subject: [hybrid-rag maintenance] OK — 4m12s — +3 ~1 -0
Subject: [hybrid-rag maintenance] FAILED at chunk stage — 1m03s
```

Body is the same consolidated summary written to the maintenance log.

**Recipient address is config, not hardcoded** — same reasoning as `source_root` in
`ingest_config.yaml`: this is a personal detail that has no place in a publishable
project. It belongs in a config file (e.g. a new `maintenance_report_email` key,
likely alongside a new `config/maintenance_config.yaml` for anything else Step 8 needs),
following the existing convention of a git-ignored real config plus a tracked
`.example.yaml` with a placeholder like `admin_user@company.com`.

## 6. Overlap protection

**Resolved.** Guard `run_maintenance.sh` with `flock` (standard on any Linux, part of
`util-linux`) around the whole run, non-blocking:

```bash
exec 200>"$LOCKFILE"
if ! flock -n 200; then
    # a previous run is still active — do not start stages on top of it
    <send failure email: "previous run still in progress">
    exit 1
fi
```

`flock` was chosen over a manual PID-file check because it's atomic (no race between
checking and creating the lock) and self-recovering — the lock is tied to the file
descriptor, so if a previous run's process died without cleaning up, the lock is
automatically released rather than requiring stale-PID detection logic. If a run is
still going when the next cron trigger fires (only plausible at much larger corpus
sizes than today's), the new invocation fails immediately without touching any of the
three stages, and — per the reporting decision above — that failure still generates the
same completion email as any other failed run, so it's never silent.

## 7. Step 8 Deliverable (handoff boundary)

- `run_maintenance.sh`: bash orchestrator — `flock`-guarded, fail-fast, chains ingest →
  chunk → index, emails a completion report on every run (success or failure)
- `config/maintenance_config.example.yaml` (tracked, placeholder recipient) +
  `config/maintenance_config.yaml` (git-ignored, real address) — following the same
  pattern as `ingest_config.yaml`
- A code change to `ingest/pipeline.py` (and `run_ingest.py`'s summary printing) to
  expose real per-run new/updated/deleted counts, matching what chunking and indexing
  already do
- A consolidated per-run maintenance log (§5), append-only, written by the orchestrator
- A documented crontab entry, with the cron-environment gotchas (§3) accounted for in
  the script itself, not left as a manual setup step someone has to remember
- Verified with a real test: touch/modify/delete a handful of files under the source
  root, run `run_maintenance.sh`, confirm the reported added/updated/removed counts
  match reality, the email arrives, and the changes are actually queryable via Step 5
  afterward — plus a deliberate second-run-while-first-still-running test to confirm the
  `flock` guard and its failure email both actually fire
