import { useState } from "react";
import { api, type Health } from "../api";
import { useLoad } from "../hooks";
import { fmtInt, fmtPct, fmtTime } from "../format";
import { Stat } from "../components/Stat";
import { TypeBars } from "../components/TypeBars";
import { AnnGauge } from "../components/AnnGauge";
import { FailuresTable, type Filters } from "../components/FailuresTable";

export function IndexHealth({ health }: { health: Health | null }) {
  const summary = useLoad(api.summary, []);
  const runs = useLoad(() => api.runs(8), []);
  const [filters, setFilters] = useState<Filters>({ cause: "", extension: "", status: "", q: "" });
  const s = summary.data;
  const m = health?.maintenance;

  if (summary.error) return <section className="card"><p className="error" role="alert">Could not load the index summary: {summary.error}</p></section>;
  if (!s) return <section className="card" aria-busy="true">Loading index summary…</section>;
  const g = s.outcome_groups;

  return (
    <>
      {m?.stale && (
        <div className="banner bad" role="alert">
          <b>The index looks stale.</b> Last successful index {fmtTime(m.last_successful_index)}; threshold {m.stale_after_hours} h
          {m.last_run?.result === "FAILED" ? "; the last maintenance run FAILED" : ""}.
          Run <code>scripts/triage.sh 5</code>; runbook: <code>Doc/Runbooks/stale-index.md</code>.
        </div>
      )}

      <section className="card" aria-labelledby="h-files">
        <h2 id="h-files">Files</h2>
        <div className="stats">
          <Stat label="Files seen" value={fmtInt(s.files_total)} sub={`${fmtInt(g.skipped)} excluded or skipped`} />
          <Stat label="Indexed" value={fmtInt(g.indexed)} sub={`${fmtPct(s.percent_indexed)} of ${fmtInt(s.attempted)} attempted`} tone="good" />
          <Stat label="Failed" value={fmtInt(g.failed)} sub={`${fmtPct(s.percent_failed)} of attempted`} tone={g.failed ? "bad" : "good"} />
          <Stat label="Needs attention" value={fmtInt(g.needs_attention)} sub="encrypted, empty, near-empty" tone={g.needs_attention ? "warn" : "good"} />
          <Stat label="Chunks" value={fmtInt(s.chunks_total)} sub={Object.entries(s.chunks_by_embedding_status).map(([k, v]) => `${fmtInt(v)} ${k}`).join(", ")} />
        </div>
        <p className="muted">“Attempted” excludes files the rules skip on purpose (excluded types, editor backups).
          Indexed includes {fmtInt(s.files_by_status["ocr_low_confidence"] ?? 0)} files whose OCR confidence is low.</p>
      </section>

      <div className="two">
        <section className="card" aria-labelledby="h-maint">
          <h2 id="h-maint">Maintenance</h2>
          {m?.last_run ? (
            <p>
              Last run <span className={`pill ${m.last_run.result === "OK" ? "good" : "bad"}`}>{m.last_run.result}</span>{" "}
              ended {fmtTime(m.last_run.ended)} in {m.last_run.seconds}s
              {m.last_run.added != null && <> (+{m.last_run.added} added, ~{m.last_run.changed} changed, −{m.last_run.removed} removed)</>}
            </p>
          ) : <p className="muted">No maintenance runs logged yet.</p>}
          {runs.data && runs.data.items.length > 0 && (
            <div className="tablewrap"><table aria-label="Recent maintenance runs">
              <thead><tr><th>Ended</th><th>Result</th><th>Time</th><th>+ / ~ / −</th></tr></thead>
              <tbody>
                {runs.data.items.map((r, i) => (
                  <tr key={i}><td>{fmtTime(r.ended)}</td><td><span className={`pill ${r.result === "OK" ? "good" : "bad"}`}>{r.result ?? "?"}</span></td>
                    <td className="num">{r.seconds ?? "–"}s</td><td className="num">{r.added ?? "–"} / {r.changed ?? "–"} / {r.removed ?? "–"}</td></tr>
                ))}
              </tbody>
            </table></div>
          )}
        </section>
        <section className="card" aria-labelledby="h-ann">
          <h2 id="h-ann">Search scale</h2>
          <AnnGauge ann={s.ann} />
        </section>
      </div>

      <section className="card" aria-labelledby="h-types">
        <h2 id="h-types">Files by type</h2>
        <TypeBars rows={s.files_by_type} />
      </section>

      <section className="card" aria-labelledby="h-causes">
        <h2 id="h-causes">Why files did not index cleanly</h2>
        <div className="tablewrap"><table aria-label="Problems by cause">
          <thead><tr><th>Cause</th><th>Files</th><th>Ticket</th><th title="Section in Doc/Runbooks/index-failure-causes.md">Id</th><th></th></tr></thead>
          <tbody>
            {s.problems_by_cause.map((c) => (
              <tr key={c.cause}>
                <td>{c.label}</td><td className="num">{fmtInt(c.count)}</td><td>{c.ticket ?? "–"}</td>
                <td><code title={c.runbook}>{c.cause}</code></td>
                <td><button onClick={() => { setFilters({ cause: c.cause, extension: "", status: "", q: "" }); document.getElementById("h-files-list")?.scrollIntoView(); }}>Show files</button></td>
              </tr>
            ))}
            {s.problems_by_cause.length === 0 && <tr><td colSpan={5} className="muted">No problem files.</td></tr>}
          </tbody>
        </table></div>
      </section>

      <section className="card" aria-labelledby="h-files-list">
        <h2 id="h-files-list">Problem files</h2>
        <FailuresTable causes={s.problems_by_cause} filters={filters} onFilters={setFilters} />
      </section>
    </>
  );
}
