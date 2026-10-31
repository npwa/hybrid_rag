import type { Summary } from "../api";
import { fmtInt } from "../format";

const TEXT: Record<string, string> = {
  ok: "Brute-force dense search is still fast at this size.",
  approaching: "Approaching the size where dense search needs an ANN index.",
  needs_index: "Above the threshold: create an ANN index (IVF-PQ) before queries slow down.",
  indexed: "An ANN index exists.",
};

export function AnnGauge({ ann }: { ann: Summary["ann"] }) {
  const pct = Math.min(100, ann.percent_of_threshold);
  return (
    <div className={`gauge ${ann.state}`}>
      <div className="gauge-head">
        <b>{fmtInt(ann.chunks)}</b> chunks of the <b>{fmtInt(ann.threshold)}</b> where an ANN index becomes necessary ({ann.percent_of_threshold}%)
      </div>
      <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Chunks against ANN threshold">
        <div className="meter-fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="muted">{TEXT[ann.state]} <span>Ticket {ann.ticket}; runbook <code>Doc/Runbooks/ann-index-needed.md</code>.</span></p>
    </div>
  );
}
