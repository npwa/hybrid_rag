// Typed, read-only client for the console API (Doc/step-9-requirements.md section 5).

export interface Source { name: string; path: string; present: boolean; read_only: boolean | null; note: string | null }
export interface Health {
  status: string; version: string; demo: boolean; time: string;
  sources: Source[];
  services: Record<string, { state: string; port?: number; url?: string }>;
  maintenance: {
    last_run: { started: string | null; ended: string | null; result: string | null; seconds: number | null;
                added: number | null; changed: number | null; removed: number | null } | null;
    last_successful_index: string | null; index_age_hours: number | null; stale_after_hours: number; stale: boolean;
  };
  index: { chunks: number | null; ann_threshold_chunks: number };
}
export interface Groups { indexed: number; failed: number; needs_attention: number; skipped: number; other: number }
export interface TypeRow extends Groups { extension: string; total: number }
export interface CauseCount { cause: string; label: string; ticket: string | null; ticket_path: string | null; runbook: string; count: number }
export interface Summary {
  files_total: number; files_by_status: Record<string, number>; chunks_total: number;
  chunks_by_embedding_status: Record<string, number>;
  outcome_groups: Groups; attempted: number; percent_indexed: number | null; percent_failed: number | null;
  files_by_type: TypeRow[]; problems_by_cause: CauseCount[];
  ann: { chunks: number; threshold: number; percent_of_threshold: number; has_ann_index: boolean | null; state: string; ticket: string };
}
export interface FailureItem {
  file_id: string; rel_path: string; extension: string; size_bytes: number | null; status: string;
  ocr_confidence: number | null; error_message: string | null; last_processed: string | null;
  cause: string; label: string; ticket: string | null; ticket_path: string | null; runbook: string;
}
export interface FailurePage { total: number; limit: number; offset: number; items: FailureItem[] }
export interface Run {
  started: string | null; ended: string | null; result: string | null; seconds: number | null;
  added: number | null; changed: number | null; removed: number | null; stages: Record<string, string>; index_ok_at: string | null;
}

export interface DenseHit { rank: number; chunk_id: string; rel_path: string; distance: number; passes_threshold: boolean; in_fused: boolean; also_sparse: boolean; excerpt: string }
export interface SparseHit { rank: number; chunk_id: string; rel_path: string; bm25: number; in_fused: boolean; also_dense: boolean; excerpt: string }
export interface FusedHit {
  rank: number; chunk_id: string; rel_path: string; rrf_score: number; branch: string;
  dense_rank: number | null; dense_distance: number | null; sparse_rank: number | null; sparse_bm25: number | null; excerpt: string;
}
export interface Gate {
  relevant: boolean; hits: number; required_hits: number; distance_threshold: number; nearest_distance: number | null;
  production_outcome: "answered" | "no_relevant" | "general_knowledge"; explanation: string;
  would_pass_with_min_hits: Record<string, boolean>;
}
export interface Exploration {
  query: string; demo: boolean; generated: boolean;
  settings: { top_n_dense: number; top_n_sparse: number; rrf_k: number; top_k_fused: number; distance_threshold: number; min_hits: number; allow_general_knowledge: boolean };
  gate: Gate; dense: DenseHit[]; sparse: SparseHit[]; fused: FusedHit[];
  timings: Record<string, number>; answer: string | null; generation_error: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(`${status}: ${detail}`); }
}

async function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const qs = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([k, v]) => { if (v !== undefined && v !== "") qs.set(k, String(v)); });
  const res = await fetch(`/api/v1${path}${qs.toString() ? "?" + qs : ""}`);
  if (!res.ok) {
    let detail = res.statusText;
    try { const j = await res.json(); detail = j.detail ? (typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail)) : j.error ?? detail; } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : Array.isArray(j.detail) ? j.detail.map((d: { msg?: string }) => d.msg).join("; ") : j.error ?? detail;
    } catch { /* not JSON */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  explore: (query: string, generate: boolean) => post<Exploration>("/explore", { query, generate }),
  health: () => get<Health>("/health"),
  summary: () => get<Summary>("/index/summary"),
  failures: (p: Record<string, string | number | boolean | undefined>) => get<FailurePage>("/index/failures", p),
  runs: (limit = 10) => get<{ total: number; items: Run[] }>("/maintenance/runs", { limit }),
};
