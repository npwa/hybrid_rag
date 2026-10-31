import type { QDay } from "../api";

const W = 760, H = 200, L = 40, R = 12, T = 10, B = 28;
const OUTCOMES = [
  { key: "answered", label: "answered", color: "#2f9e6b" },
  { key: "general_knowledge", label: "general knowledge", color: "#7d6bd1" },
  { key: "no_relevant", label: "no relevant document", color: "#e0a21a" },
  { key: "error", label: "error", color: "#d1493f" },
] as const;

const niceMax = (v: number) => { const s = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000].find((n) => n >= v); return s ?? Math.ceil(v / 100) * 100; };
const dayLabel = (d: string) => d.slice(5);

/** Stacked bars: queries per day by outcome. The legend names each colour, and every bar has a <title> with its numbers. */
export function QueriesPerDay({ days }: { days: QDay[] }) {
  if (days.length === 0) return <p className="muted">No queries in this period.</p>;
  const max = niceMax(Math.max(...days.map((d) => d.queries), 1));
  const slot = (W - L - R) / days.length, bw = Math.min(28, slot * 0.7);
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Queries per day, ${days.length} days, most ${Math.max(...days.map((d) => d.queries))} in one day`}>
        {[0, max / 2, max].map((v) => (<g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="gridline" /><text x={L - 6} y={y(v) + 4} textAnchor="end" className="axis">{v}</text></g>))}
        {days.map((d, i) => {
          let acc = 0;
          const cx = L + slot * i + slot / 2;
          return (
            <g key={d.day}>
              <title>{`${d.day}: ${d.queries} queries (${OUTCOMES.map((o) => `${d[o.key]} ${o.label}`).join(", ")})`}</title>
              {OUTCOMES.map((o) => { const n = d[o.key]; const y0 = y(acc), y1 = y(acc + n); acc += n;
                return n ? <rect key={o.key} x={cx - bw / 2} width={bw} y={y1} height={Math.max(y0 - y1, 0)} fill={o.color} /> : null; })}
              {(days.length <= 16 || i % Math.ceil(days.length / 12) === 0) && <text x={cx} y={H - 8} textAnchor="middle" className="axis">{dayLabel(d.day)}</text>}
            </g>
          );
        })}
      </svg>
      <figcaption className="legend">{OUTCOMES.map((o) => <span key={o.key}><i className="dot" style={{ background: o.color }} />{o.label}</span>)}</figcaption>
    </figure>
  );
}

/** Median and 95th percentile of total seconds per day (answered queries), with the slow threshold as a dashed line. */
export function LatencyPerDay({ days, slow }: { days: QDay[]; slow: number }) {
  const pts = days.filter((d) => d.latency_s.count > 0);
  if (pts.length === 0) return <p className="muted">No timed queries in this period.</p>;
  const top = Math.max(...pts.map((d) => d.latency_s.p95 ?? 0), slow, 1);
  const max = niceMax(top * 1.05);
  const x = (i: number) => L + ((W - L - R) * (days.length === 1 ? 0.5 : i / (days.length - 1)));
  const y = (v: number) => T + (1 - v / max) * (H - T - B);
  const line = (pick: (d: QDay) => number | null) => days.map((d, i) => ({ i, v: d.latency_s.count ? pick(d) : null })).filter((p) => p.v != null)
    .map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v as number).toFixed(1)}`).join(" ");
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Median and 95th percentile query time per day, in seconds">
        {[0, max / 2, max].map((v) => (<g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="gridline" /><text x={L - 6} y={y(v) + 4} textAnchor="end" className="axis">{Math.round(v)} s</text></g>))}
        <line x1={L} x2={W - R} y1={y(slow)} y2={y(slow)} stroke="#d1493f" strokeDasharray="5 4" />
        <text x={W - R} y={y(slow) - 4} textAnchor="end" className="axis">slow ≥ {slow} s</text>
        <path d={line((d) => d.latency_s.p95)} fill="none" stroke="#e0a21a" strokeWidth={2} />
        <path d={line((d) => d.latency_s.p50)} fill="none" stroke="#2455c3" strokeWidth={2} />
        {days.map((d, i) => d.latency_s.count ? (
          <g key={d.day}><title>{`${d.day}: median ${d.latency_s.p50} s, p95 ${d.latency_s.p95} s, ${d.latency_s.count} timed queries`}</title>
            <circle cx={x(i)} cy={y(d.latency_s.p50 ?? 0)} r={3} fill="#2455c3" /><circle cx={x(i)} cy={y(d.latency_s.p95 ?? 0)} r={3} fill="#e0a21a" /></g>) : null)}
        {days.map((d, i) => (days.length <= 16 || i % Math.ceil(days.length / 12) === 0) ? <text key={d.day} x={x(i)} y={H - 8} textAnchor="middle" className="axis">{dayLabel(d.day)}</text> : null)}
      </svg>
      <figcaption className="legend"><span><i className="dot" style={{ background: "#2455c3" }} />median</span><span><i className="dot" style={{ background: "#e0a21a" }} />95th percentile</span></figcaption>
    </figure>
  );
}
