import type { Exploration } from "../api";

const Excerpt = ({ text }: { text: string }) => (
  <details><summary>excerpt</summary><p className="excerpt">{text || "(empty)"}</p></details>
);

function Badge({ branch }: { branch: string }) {
  return <span className={`pill branch-${branch.replace("+", "-")}`}>{branch === "dense+sparse" ? "both" : branch === "dense" ? "dense only" : "keyword only"}</span>;
}

export function HitLists({ x }: { x: Exploration }) {
  const s = x.settings;
  return (
    <div className="three">
      <section className="card" aria-labelledby="h-dense">
        <h2 id="h-dense">Dense (meaning) <span className="muted">top {s.top_n_dense}</span></h2>
        <p className="muted small">Smaller distance is closer. <span className="ok-mark">●</span> under the threshold ({s.distance_threshold}); the gate counts these.</p>
        <ol className="hits">
          {x.dense.map((h) => (
            <li key={h.chunk_id} className={h.in_fused ? "infused" : ""}>
              <div><span className="rank">{h.rank}</span> <span className="path">{h.rel_path}</span></div>
              <div className="meta">
                <span className={h.passes_threshold ? "ok-mark" : "no-mark"} title={h.passes_threshold ? "under threshold" : "over threshold"}>{h.passes_threshold ? "●" : "○"}</span>{" "}
                distance {h.distance.toFixed(3)}{h.also_sparse && " · also keyword"}{h.in_fused && " · in fused list"}
              </div>
              <Excerpt text={h.excerpt} />
            </li>
          ))}
        </ol>
      </section>
      <section className="card" aria-labelledby="h-sparse">
        <h2 id="h-sparse">Keyword (BM25) <span className="muted">top {s.top_n_sparse}</span></h2>
        <p className="muted small">More negative is a better match.</p>
        {x.sparse.length === 0 ? <p className="muted">No keyword matches (none of the words occur in the index).</p> : (
          <ol className="hits">
            {x.sparse.map((h) => (
              <li key={h.chunk_id} className={h.in_fused ? "infused" : ""}>
                <div><span className="rank">{h.rank}</span> <span className="path">{h.rel_path}</span></div>
                <div className="meta">bm25 {h.bm25.toFixed(2)}{h.also_dense && " · also dense"}{h.in_fused && " · in fused list"}</div>
                <Excerpt text={h.excerpt} />
              </li>
            ))}
          </ol>
        )}
      </section>
      <section className="card" aria-labelledby="h-fused">
        <h2 id="h-fused">Fused ranking (RRF) <span className="muted">top {s.top_k_fused}, k={s.rrf_k}</span></h2>
        <p className="muted small">What the language model would be shown, in this order.</p>
        <ol className="hits">
          {x.fused.map((h) => (
            <li key={h.chunk_id}>
              <div><span className="rank">{h.rank}</span> <span className="path">{h.rel_path}</span> <Badge branch={h.branch} /></div>
              <div className="meta">
                rrf {h.rrf_score}
                {h.dense_rank != null && <> · dense #{h.dense_rank} (d {h.dense_distance?.toFixed(3)})</>}
                {h.sparse_rank != null && <> · keyword #{h.sparse_rank} ({h.sparse_bm25?.toFixed(2)})</>}
              </div>
              <Excerpt text={h.excerpt} />
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
