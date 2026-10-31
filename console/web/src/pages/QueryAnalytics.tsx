import { useState } from "react";
import { api } from "../api";
import type { QueryRow } from "../api";
import { useLoad } from "../hooks";
import { fmtInt, fmtPct, fmtTime } from "../format";
import { Stat } from "../components/Stat";
import { LatencyPerDay, QueriesPerDay } from "../components/QueryCharts";

const KINDS = [
  { id: "slow", label: "Slowest" },
  { id: "no_result", label: "No relevant result" },
  { id: "error", label: "Errors" },
] as const;

const secs = (s: number | null | undefined) => (s == null ? "–" : s >= 10 ? `${s.toFixed(0)} s` : `${s.toFixed(1)} s`);

function QueryTable({ kind, days }: { kind: string; days: number }) {
  const q = useLoad(() => api.queryList(kind, days), [kind, days]);
  if (q.error) return <p className="error" role="alert">Could not load: {q.error}</p>;
  if (!q.data) return <p aria-busy="true">Loading…</p>;
  const rows: QueryRow[] = q.data.items;
  return (
    <>
      <div className="tablewrap">
        <table aria-label={`Queries: ${kind}`}>
          <thead><tr><th>When</th><th>Question</th><th className="num">Time</th><th>Caller</th><th>{kind === "error" ? "Error" : "Sources"}</th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="nowrap">{fmtTime(r.ts)}</td>
                <td>{r.query}</td>
                <td className="num">{secs(r.total_s)}</td>
                <td>{r.caller ?? "–"}</td>
                <td className="small">{kind === "error" ? r.error : r.n_sources === 0 ? <span className="muted">none</span> : r.sources.join(", ") + (r.n_sources > r.sources.length ? ` … (+${r.n_sources - r.sources.length})` : "")}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="muted">None in this period.</td></tr>}
          </tbody>
        </table>
      </div>
      {q.data.total > rows.length && <p className="muted small">Showing {rows.length} of {q.data.total}.</p>}
    </>
  );
}

export function QueryAnalytics() {
  const [days, setDays] = useState(30);
  const [kind, setKind] = useState<string>("slow");
  const q = useLoad(() => api.queryStats(days), [days]);
  const d = q.data;

  if (q.error) return <section className="card"><p className="error" role="alert">Could not load query statistics: {q.error}</p></section>;
  if (!d) return <section className="card" aria-busy="true">Loading query statistics…</section>;
  if (!d.available) {
    return (
      <section className="card" aria-labelledby="h-qa">
        <h2 id="h-qa">Query analytics</h2>
        <p className="muted">No query logs were found in this period. The query engine writes <code>logs/query_YYYY-MM-DD.log</code> and <code>.jsonl</code>.</p>
      </section>
    );
  }
  const t = d.totals, r = d.rates;
  return (
    <>
      <section className="card" aria-labelledby="h-qa">
        <div className="head-row">
          <h2 id="h-qa">Query analytics</h2>
          <label>Period{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[7, 14, 30, 90].map((n) => <option key={n} value={n}>last {n} days</option>)}
            </select>
          </label>
        </div>
        <p className="muted">
          What people ask, how long answers take and how often nothing relevant is found. {d.coverage.days_with_data} day(s) of logs
          ({fmtTime(d.coverage.first)} to {fmtTime(d.coverage.last)}); {d.coverage.jsonl_days} with the structured log, {d.coverage.text_days} text-only
          (text-only days have no caller information).
          {t.system_queries > 0 && <> {fmtInt(t.system_queries)} automatic “### Task:” prompt(s) from Open WebUI are left out of every number below.</>}
        </p>
        {d.masked && <div className="banner warn" role="status">Privacy mode is on: question text and file names are replaced by short codes. The same question always gets the same code.</div>}
        <div className="stats">
          <Stat label="Questions" value={fmtInt(t.queries)} sub={Object.entries(d.by_caller).map(([k, v]) => `${v} ${k}`).join(", ")} />
          <Stat label="Typical time" value={secs(d.latency_s.p50)} sub={`median; 95th percentile ${secs(d.latency_s.p95)}, slowest ${secs(d.latency_s.max)}`} />
          <Stat label="No relevant result" value={fmtPct(r.no_relevant)} sub={`${t.by_outcome.no_relevant} question(s) the gate refused`} tone={r.no_relevant != null && r.no_relevant > 15 ? "warn" : undefined} />
          <Stat label="Errors" value={fmtPct(r.error)} sub={`${t.by_outcome.error} failed (embedding, generation, timeout)`} tone={t.by_outcome.error ? "bad" : "good"} />
          <Stat label={`Slow (≥ ${d.slow_seconds} s)`} value={fmtPct(r.slow)} sub={`${t.slow} of ${t.timed} timed questions`} tone={r.slow != null && r.slow > 10 ? "warn" : undefined} />
          <Stat label="Without sources" value={fmtPct(r.zero_sources)} sub="refused, general knowledge or failed" />
        </div>
      </section>

      <section className="card" aria-labelledby="h-vol"><h2 id="h-vol">Questions per day</h2><QueriesPerDay days={d.by_day} /></section>
      <section className="card" aria-labelledby="h-lat"><h2 id="h-lat">Time per day</h2><LatencyPerDay days={d.by_day} slow={d.slow_seconds} />
        <p className="muted small">Total seconds from question to answer for answered and general-knowledge questions. Generation speed (median): {d.tok_per_s == null ? "not recorded" : `${d.tok_per_s} tokens/s`}.</p></section>

      <section className="card" aria-labelledby="h-list">
        <h2 id="h-list">Questions worth a look</h2>
        <div role="tablist" aria-label="Kind of question" className="tabs">
          {KINDS.map((k) => (
            <button key={k.id} role="tab" aria-selected={kind === k.id} className={kind === k.id ? "tab active" : "tab"} onClick={() => setKind(k.id)}>{k.label}</button>
          ))}
        </div>
        <QueryTable kind={kind} days={days} />
        <p className="muted small">“No relevant result”: nothing scored close enough, so the assistant declined (see the Query explorer to see why). Runbook: <code>Doc/Runbooks/</code>.</p>
      </section>

      <section className="card" aria-labelledby="h-rec">
        <h2 id="h-rec">Recurring questions</h2>
        <div className="tablewrap">
          <table aria-label="Recurring questions">
            <thead><tr><th>Question</th><th className="num">Asked</th><th className="num">No relevant result</th><th className="num">Errors</th><th>Last</th></tr></thead>
            <tbody>
              {d.top_queries.map((x, i) => (<tr key={i}><td>{x.query}</td><td className="num">{x.count}</td><td className="num">{x.no_relevant}</td><td className="num">{x.errors}</td><td className="nowrap">{fmtTime(x.last_seen)}</td></tr>))}
              {d.top_queries.length === 0 && <tr><td colSpan={5} className="muted">No question was asked more than once.</td></tr>}
            </tbody>
          </table>
        </div>
        {d.masked ? <p className="muted small">Common words are hidden in privacy mode.</p> : (
          <p className="terms" aria-label="Common words">
            {d.top_terms.length === 0 ? <span className="muted">No word appears in more than one question.</span> :
              d.top_terms.map((x) => <span key={x.term} className="pill">{x.term} · {x.queries}</span>)}
          </p>
        )}
      </section>
    </>
  );
}
