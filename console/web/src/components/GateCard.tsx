import type { Exploration } from "../api";

const OUTCOME: Record<string, string> = {
  answered: "retrieve sources and answer from them",
  no_relevant: "reply that nothing relevant was found",
  general_knowledge: "answer from general knowledge (labelled)",
};

export function GateCard({ x }: { x: Exploration }) {
  const g = x.gate;
  return (
    <section className={`card gate ${g.relevant ? "pass" : "fail"}`} aria-labelledby="h-gate">
      <h2 id="h-gate">Relevance gate: <span className={`pill ${g.relevant ? "good" : "bad"}`}>{g.relevant ? "PASSED" : "NOT PASSED"}</span></h2>
      <p>{g.explanation}</p>
      <p className="muted">Production outcome: <b>{OUTCOME[g.production_outcome]}</b>.</p>
      <p className="gate-facts">
        Nearest distance <b>{g.nearest_distance == null ? "–" : g.nearest_distance.toFixed(3)}</b> · threshold <b>{g.distance_threshold}</b> ·
        hits under threshold <b>{g.hits}</b> of {x.dense.length} · hits required <b>{g.required_hits}</b>
      </p>
      <p className="muted whatif">
        What if the required hits were:{" "}
        {Object.entries(g.would_pass_with_min_hits).map(([m, ok]) => (
          <span key={m} className={`pill ${ok ? "good" : "bad"}`} title={ok ? "gate would pass" : "gate would fail"}>{m}: {ok ? "pass" : "fail"}</span>
        ))}
      </p>
    </section>
  );
}
