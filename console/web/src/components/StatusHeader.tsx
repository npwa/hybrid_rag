import type { Health } from "../api";
import { fmtAge, fmtTime } from "../format";

function Pill({ label, state }: { label: string; state: string }) {
  const kind = state === "up" || state === "ok" || state === "OK" ? "good" : state.startsWith("n/a") ? "neutral" : "bad";
  return <span className={`pill ${kind}`}><b>{label}</b> {state}</span>;
}

export function StatusHeader({ health, error }: { health: Health | null; error: string | null }) {
  if (error) return <div className="status bad-bar" role="alert">Cannot reach the console API: {error}</div>;
  if (!health) return <div className="status" aria-busy="true">Loading status…</div>;
  const m = health.maintenance;
  const last = m.last_run;
  return (
    <div className="status" role="status" aria-label="System status">
      <Pill label="Console" state={health.status} />
      <Pill label="MCP server" state={health.services.mcp_server?.state ?? "unknown"} />
      <Pill label="Ollama" state={health.services.ollama?.state ?? "unknown"} />
      <Pill label="Last maintenance" state={last?.result ?? "none"} />
      <span className={`pill ${m.stale ? "bad" : "good"}`}>
        <b>Index</b> {m.stale ? "STALE" : "fresh"} · last good {fmtTime(m.last_successful_index)} ({fmtAge(m.index_age_hours)})
      </span>
      <span className="muted version">v{health.version}</span>
    </div>
  );
}
