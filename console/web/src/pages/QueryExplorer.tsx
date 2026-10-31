import { useState } from "react";
import { api, ApiError, type Exploration, type Health } from "../api";
import { GateCard } from "../components/GateCard";
import { HitLists } from "../components/HitLists";

const DEMO_EXAMPLES = ["how do I reset the demo widget", "which seedlings go in the raised bed", "who was wolfgang amadeus mozart"];

export function QueryExplorer({ health }: { health: Health | null }) {
  const [text, setText] = useState("");
  const [generate, setGenerate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Exploration | null>(null);
  const demo = health?.demo ?? false;

  async function run(q: string) {
    if (!q.trim() || busy) return;
    setBusy(true); setError(null);
    try { setResult(await api.explore(q.trim(), generate && !demo)); }
    catch (e) { setResult(null); setError(e instanceof ApiError ? (e.status === 429 ? "Another exploration is running; try again in a moment." : e.message) : String(e)); }
    finally { setBusy(false); }
  }

  return (
    <>
      <section className="card" aria-labelledby="h-explore">
        <h2 id="h-explore">Query explorer</h2>
        <p className="muted">See how retrieval reaches its ranking for a question. This never changes the index and is not recorded in the production query logs.</p>
        <form className="explore-form" onSubmit={(e) => { e.preventDefault(); run(text); }}>
          <label className="grow">Question
            <input value={text} onChange={(e) => setText(e.target.value)} maxLength={1000} placeholder="e.g. home router external IP address" autoFocus />
          </label>
          <button type="submit" disabled={busy || !text.trim()}>{busy ? "Exploring…" : "Explore"}</button>
        </form>
        <label className="check">
          <input type="checkbox" checked={generate && !demo} disabled={demo} onChange={(e) => setGenerate(e.target.checked)} />
          Also generate an answer (uses the GPU{demo ? "; not available in demo mode" : ""})
        </label>
        {demo && <p className="muted small">Try: {DEMO_EXAMPLES.map((q) => <button key={q} type="button" className="link" onClick={() => { setText(q); run(q); }}>{q}</button>)}</p>}
        {error && <p className="error" role="alert">Could not explore: {error}</p>}
      </section>

      {result && (
        <>
          <div className="timings" aria-label="Timings">
            {Object.entries(result.timings).map(([k, v]) => <span key={k} className="pill"><b>{k.replace("_s", "")}</b> {(v * 1000).toFixed(0)} ms</span>)}
          </div>
          <GateCard x={result} />
          {(result.answer || result.generation_error) && (
            <section className="card" aria-labelledby="h-answer">
              <h2 id="h-answer">Generated answer</h2>
              {result.answer ? <p className="answer">{result.answer}</p> : <p className="error" role="alert">{result.generation_error}</p>}
            </section>
          )}
          <HitLists x={result} />
        </>
      )}
    </>
  );
}
