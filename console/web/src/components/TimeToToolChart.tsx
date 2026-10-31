import type { ToolCalls } from "../api";
import { fmtMs } from "../format";

const W = 760, H = 220, L = 52, R = 12, T = 12, B = 30;
const COLORS = ["#2455c3", "#d1493f", "#2f9e6b", "#e0a21a", "#7d6bd1", "#a9b0be"];

/** Scatter of time-to-tool per turn (message received to tool starting), coloured by model. A table of the same
 *  numbers is available to screen readers via the caption; colours are always repeated in the legend text. */
export function TimeToToolChart({ samples }: { samples: NonNullable<ToolCalls["time_to_tool_samples"]> }) {
  if (samples.length === 0) return <p className="muted">No tool starts in this period.</p>;
  const t = samples.map((s) => new Date(s.ts).getTime());
  const t0 = Math.min(...t), t1 = Math.max(...t, t0 + 1);
  const top = Math.max(...samples.map((s) => s.ms), 1000);
  const step = [500, 1000, 2000, 5000, 10000, 15000, 20000, 30000, 60000, 120000, 300000].find((n) => top / n <= 5) ?? 600000;
  const ymax = Math.ceil((top * 1.05) / step) * step;
  const models = [...new Set(samples.map((s) => s.model))];
  const x = (v: number) => L + ((v - t0) / (t1 - t0)) * (W - L - R);
  const y = (v: number) => T + (1 - v / ymax) * (H - T - B);
  const ticks = Array.from({ length: Math.round(ymax / step) + 1 }, (_, i) => i * step);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Time to tool for ${samples.length} turns, median ${fmtMs([...samples].sort((a, b) => a.ms - b.ms)[Math.floor(samples.length / 2)].ms)}`}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} className="gridline" />
            <text x={L - 6} y={y(v) + 4} textAnchor="end" className="axis">{fmtMs(v)}</text>
          </g>
        ))}
        <text x={L} y={H - 8} className="axis">{new Date(t0).toLocaleDateString()}</text>
        <text x={W - R} y={H - 8} textAnchor="end" className="axis">{new Date(t1).toLocaleDateString()}</text>
        {samples.map((s, i) => (
          <circle key={i} cx={x(new Date(s.ts).getTime())} cy={y(s.ms)} r={3.5} fill={COLORS[models.indexOf(s.model) % COLORS.length]} fillOpacity={0.75}>
            <title>{`${s.ts.replace("T", " ")}  ${fmtMs(s.ms)}  ${s.model}`}</title>
          </circle>
        ))}
      </svg>
      <figcaption className="legend">
        {models.map((m, i) => <span key={m}><i className="dot" style={{ background: COLORS[i % COLORS.length] }} />{m}</span>)}
        <span className="muted">· time from the message arriving until the tool starts</span>
      </figcaption>
    </figure>
  );
}
