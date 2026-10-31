import type { TypeRow } from "../api";
import { fmtInt } from "../format";

const KINDS: [keyof TypeRow, string][] = [["indexed", "Indexed"], ["failed", "Failed"], ["needs_attention", "Needs attention"], ["skipped", "Skipped"], ["other", "Other"]];

/** Horizontal stacked bars per file type; the numbers are always printed so colour is never the only cue. */
export function TypeBars({ rows }: { rows: TypeRow[] }) {
  const max = Math.max(1, ...rows.map((r) => r.total));
  return (
    <div className="typebars" role="table" aria-label="Files by type and outcome">
      <div className="legend" aria-hidden="true">{KINDS.map(([k, l]) => <span key={k}><i className={`dot ${k}`} />{l}</span>)}</div>
      {rows.map((r) => (
        <div className="row" role="row" key={r.extension}>
          <span className="ext" role="rowheader">{r.extension === "" ? "(none)" : r.extension}</span>
          <span className="bar" aria-hidden="true">
            {KINDS.map(([k]) => (r[k] as number) > 0 && <span key={k} className={`seg ${k}`} style={{ width: `${(100 * (r[k] as number)) / max}%` }} />)}
          </span>
          <span className="nums" role="cell">
            {fmtInt(r.total)} <span className="muted">({fmtInt(r.indexed)} indexed, {fmtInt(r.failed)} failed)</span>
          </span>
        </div>
      ))}
    </div>
  );
}
