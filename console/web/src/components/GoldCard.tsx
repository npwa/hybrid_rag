import type { Exploration, GoldReport } from "../api";
import { fmtTime } from "../format";

/** Last run of the gold question set (scripts/run_gold_set.py). Each row can be explored to see why it passed or failed. */
export function GoldCard({ report, onExplore }: { report: GoldReport | null; onExplore: (q: string) => void }) {
  if (!report) return null;
  if (!report.available) {
    return (
      <section className="card" aria-labelledby="h-gold">
        <h2 id="h-gold">Gold set</h2>
        <p className="muted">{report.detail}</p>
      </section>
    );
  }
  const cmp = report.compared_with;
  return (
    <section className="card" aria-labelledby="h-gold">
      <h2 id="h-gold">Gold set</h2>
      <p className="muted">
        Questions with known answers, checked against retrieval. Last run {fmtTime(report.saved_at)}:{" "}
        <b className={report.failed ? "error" : ""}>{report.passed} of {report.total} passed</b>
        {report.overrides && report.overrides.length > 0 && <> (with overrides {report.overrides.join(", ")})</>}
        {" "}at threshold {report.settings?.distance_threshold}, min hits {report.settings?.min_hits}.
        {cmp && (cmp.regressions.length > 0 ? <span className="error"> Regressions against the baseline: {cmp.regressions.join(", ")}.</span> : " No regressions against the baseline.")}
      </p>
      <div className="tablewrap">
        <table aria-label="Gold set results">
          <thead><tr><th>Id</th><th>Question</th><th>Expected</th><th>Gate</th><th>Result</th><th></th></tr></thead>
          <tbody>
            {report.items!.map((g) => (
              <tr key={g.id} className={g.passed ? "" : "row-bad"}>
                <td>{g.id}</td><td>{g.question}</td><td>{g.expect === "answered" ? "found within " + g.within : "refused"}</td><td>{g.verdict}</td>
                <td>{g.passed ? <span className="pill good">pass</span> : <><span className="pill bad">fail</span> <span className="small">{g.problems.join("; ")}</span></>}</td>
                <td>{!report.masked && <button type="button" className="link" onClick={() => onExplore(g.question)}>Explore</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** When the explored question is a gold question: what the saved run said against what retrieval gives now. */
export function GoldCompare({ report, result }: { report: GoldReport | null; result: Exploration }) {
  const g = report?.items?.find((i) => i.question.trim().toLowerCase() === result.query.trim().toLowerCase());
  if (!g) return null;
  const nowRank = g.sources_any.length ? result.fused.findIndex((f) => g.sources_any.some((s) => f.rel_path.includes(s))) + 1 || null : null;
  const nowOk = result.gate.production_outcome === g.expect && (g.expect !== "answered" || (nowRank != null && nowRank <= g.within));
  return (
    <div className={`banner ${nowOk ? "good" : "bad"}`} role="status">
      Gold question <b>{g.id}</b> expects {g.expect === "answered" ? `a source within the top ${g.within}` : "a refusal"}. Last saved run: {g.passed ? "passed" : "failed"}.
      Now: gate {result.gate.production_outcome}{g.expect === "answered" && <>, expected source {nowRank ? `at rank ${nowRank}` : "not found"}</>} → {nowOk ? "pass" : "fail"}.
    </div>
  );
}
