import { useState } from "react";
import { api } from "../api";
import { useLoad } from "../hooks";
import { fmtAge, fmtInt, fmtMs, fmtPct, fmtTime } from "../format";
import { Stat } from "../components/Stat";
import { TimeToToolChart } from "../components/TimeToToolChart";

const FLAG_LABEL: Record<string, string> = {
  mcp_connect_failure: "MCP connect failure", tool_removed_by_policy: "Tool removed by policy", looks_like_tool_call: "Tool call written as text",
  host_gap: "VM was frozen", provider_preflight_failed: "Ollama preflight failed", agent_failed: "Agent failed before reply",
  tool_start_without_desktop_call: "Tool started, desktop saw nothing",
};
const BAD = new Set(["mcp_connect_failure", "tool_removed_by_policy", "looks_like_tool_call", "tool_start_without_desktop_call", "agent_failed"]);

export function ToolCalls() {
  const [days, setDays] = useState(30);
  const q = useLoad(() => api.toolcalls(days), [days]);
  const d = q.data;

  if (q.error) return <section className="card"><p className="error" role="alert">Could not load tool-call data: {q.error}</p></section>;
  if (!d) return <section className="card" aria-busy="true">Loading tool-call data…</section>;
  if (!d.available) {
    return (
      <section className="card" aria-labelledby="h-tc">
        <h2 id="h-tc">Tool-call monitor</h2>
        <p role="alert" className="error">{d.detail}</p>
        <p className="muted">The logs live on the bot VM and are copied by <code>{d.sources.pull_script}</code> (read-only, run it from cron or by hand).</p>
      </section>
    );
  }
  const t = d.totals!;
  const rate = t.turns ? (100 * t.tool_starts) / t.turns : null;
  const stale = d.sources.age_hours != null && d.sources.age_hours > 36;

  return (
    <>
      <section className="card" aria-labelledby="h-tc">
        <div className="head-row">
          <h2 id="h-tc">Tool-call monitor</h2>
          <label>Period{" "}
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {[7, 14, 30, 90].map((n) => <option key={n} value={n}>last {n} days</option>)}
            </select>
          </label>
        </div>
        <p className="muted">
          Does the agent model really call <code>ask_documents</code>, how long does it take to start, and does the desktop see the request?
          Data: OpenClaw logs copied from the bot VM ({d.sources.files} file{d.sources.files === 1 ? "" : "s"}, covering {fmtTime(d.coverage?.first)} to {fmtTime(d.coverage?.last)}),
          matched with the desktop's own query log.
        </p>
        {stale && <div className="banner bad" role="alert">The newest copied log is {fmtAge(d.sources.age_hours)}. Run <code>scripts/pull_agent_logs.sh</code>; the VM clears /tmp when it reboots, so older history can be lost.</div>}
        <div className="stats">
          <Stat label="Agent turns" value={fmtInt(t.turns)} sub={`${fmtInt(t.tool_starts)} started the tool`} />
          <Stat label="Real tool-call rate" value={fmtPct(rate)} sub="turns where the tool was started" tone={rate != null && rate >= 90 ? "good" : "warn"} />
          <Stat label="Tool call written as text" value={fmtInt(t.looks_like_tool_call)} sub="model printed the call instead of making it" tone={t.looks_like_tool_call ? "bad" : "good"} />
          <Stat label="Seen by the desktop" value={`${fmtInt(t.matched)} / ${fmtInt(t.tool_starts)}`} sub={t.agent_starts_without_desktop_call ? `${t.agent_starts_without_desktop_call} started but never arrived` : "every start reached the MCP server"} tone={t.agent_starts_without_desktop_call ? "bad" : "good"} />
          <Stat label="Time to tool" value={fmtMs(d.time_to_tool_ms?.p50)} sub={`median; p95 ${fmtMs(d.time_to_tool_ms?.p95)}, max ${fmtMs(d.time_to_tool_ms?.max)}`} />
        </div>
      </section>

      {d.flags && d.flags.length > 0 && (
        <section className="card" aria-labelledby="h-flags">
          <h2 id="h-flags">Needs a look</h2>
          <ul className="flags">
            {d.flags.slice(0, 12).map((f, i) => (
              <li key={i}>
                <span className={`pill ${BAD.has(f.kind) ? "bad" : ""}`}>{FLAG_LABEL[f.kind] ?? f.kind}</span>{" "}
                <span className="muted">{fmtTime(f.ts)} · {f.model}</span> — {f.detail}
                {f.turns_without_tool_after ? <> ({f.turns_without_tool_after} later turn(s) had no tool call)</> : null}
              </li>
            ))}
          </ul>
          <p className="muted small">Runbooks: <code>Doc/Runbooks/tool-never-called.md</code>, <code>Doc/Runbooks/mcp-server-down.md</code>.</p>
        </section>
      )}

      <section className="card" aria-labelledby="h-models">
        <h2 id="h-models">By agent model</h2>
        <div className="tablewrap">
          <table aria-label="Tool calls by model">
            <thead><tr><th>Model</th><th>Turns</th><th>Tool started</th><th>Rate</th><th>Written as text</th><th>Time to tool (median / p95)</th></tr></thead>
            <tbody>
              {d.models!.map((m) => (
                <tr key={m.model}>
                  <td><code>{m.model}</code></td><td className="num">{fmtInt(m.turns)}</td><td className="num">{fmtInt(m.tool_starts)}</td>
                  <td className="num">{m.tool_rate == null ? "–" : fmtPct(100 * m.tool_rate)}</td>
                  <td className="num">{fmtInt(m.looks_like)}</td>
                  <td className="num">{fmtMs(m.time_to_tool_ms.p50)} / {fmtMs(m.time_to_tool_ms.p95)}</td>
                </tr>
              ))}
              {d.models!.length === 0 && <tr><td colSpan={6} className="muted">No agent turns in this period.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card" aria-labelledby="h-chart">
        <h2 id="h-chart">Time to tool</h2>
        <TimeToToolChart samples={d.time_to_tool_samples ?? []} />
      </section>

      <section className="card" aria-labelledby="h-days">
        <h2 id="h-days">By day: agent side against desktop side</h2>
        <div className="tablewrap">
          <table aria-label="Tool calls by day">
            <thead><tr><th>Day</th><th>Model(s)</th><th>Turns</th><th>Tool started</th><th>Written as text</th><th>Desktop MCP requests</th><th>Matched</th><th>Started, not seen</th><th>MCP connect failures</th></tr></thead>
            <tbody>
              {d.by_day!.map((r) => (
                <tr key={r.day} className={r.agent_starts_without_desktop_call || r.mcp_connect_failures ? "row-bad" : ""}>
                  <td>{r.day}</td><td className="small">{r.models.map((m) => m.replace("ollama/", "")).join(", ") || "–"}</td>
                  <td className="num">{r.turns}</td><td className="num">{r.tool_starts}</td><td className="num">{r.looks_like_tool_call}</td>
                  <td className="num">{r.desktop_mcp_calls}</td><td className="num">{r.matched}</td>
                  <td className="num">{r.agent_starts_without_desktop_call}</td><td className="num">{r.mcp_connect_failures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small">
          “Matched” pairs a tool start with a desktop request that began within {20} s of it. Desktop counts need the structured query log (since milestone M1),
          so earlier days show no desktop requests ({d.jsonl_days_with_mcp_records ?? 0} day(s) in this period have one); on those days a start is confirmed by any logged query at that time{t.matched_by_time_only ? ` (${t.matched_by_time_only} start(s) matched this way)` : ""}.
          Desktop: {fmtInt(d.desktop?.calls)} MCP requests, median {d.desktop?.total_s.p50 ?? "–"} s, p95 {d.desktop?.total_s.p95 ?? "–"} s.
        </p>
      </section>
    </>
  );
}
