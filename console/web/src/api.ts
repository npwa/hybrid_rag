// Typed, read-only client for the console API (Doc/step-9-requirements.md section 5).

export interface Warn { id: string; text: string; runbook: string | null }
export interface Source { name: string; path: string; present: boolean; read_only: boolean | null; note: string | null }
export interface Health {
  status: string; version: string; demo: boolean; time: string;
  sources: Source[];
  warnings: Warn[];
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

export interface Pctl { count: number; p50: number | null; p95: number | null; max: number | null }
export interface ModelRow { model: string; turns: number; tool_starts: number; tool_rate: number | null; looks_like: number; time_to_tool_ms: Pctl }
export interface DayRow {
  day: string; turns: number; tool_starts: number; looks_like_tool_call: number; desktop_mcp_calls: number; matched: number;
  agent_starts_without_desktop_call: number; mcp_connect_failures: number; host_gaps: number; models: string[]; time_to_tool_ms: Pctl;
}
export interface Flag { kind: string; runbook?: string | null; ts: string; model: string; detail: string; turns_without_tool_after?: number }
export interface ToolCalls {
  available: boolean; detail?: string; warnings?: Warn[];
  sources: { files: number; newest_file: string | null; age_hours: number | null; agent_logs_dir: string; config_summary: Record<string, unknown> | null; pull_script: string };
  days?: number; coverage?: { first: string | null; last: string | null };
  totals?: { turns: number; tool_starts: number; matched: number; matched_by_time_only: number; agent_starts_without_desktop_call: number; desktop_calls_without_agent_start: number;
             looks_like_tool_call: number; mcp_connect_failures: number; tool_removed_by_policy: number };
  models?: ModelRow[]; by_day?: DayRow[]; time_to_tool_ms?: Pctl;
  time_to_tool_samples?: { ts: string; ms: number; model: string }[];
  desktop?: { calls: number; total_s: { count: number; p50: number | null; p95: number | null; max: number | null }; by_outcome: Record<string, number> };
  flags?: Flag[]; jsonl_days_with_mcp_records?: number;
}

export interface QStats { count: number; p50: number | null; p95: number | null; max: number | null }
export interface QDay { day: string; queries: number; answered: number; no_relevant: number; general_knowledge: number; error: number; slow: number; latency_s: QStats; tok_per_s: number | null; format: string | null }
export interface QueryStats {
  available: boolean; warnings: Warn[]; days: number; slow_seconds: number; masked: boolean;
  coverage: { days_with_data: number; first: string | null; last: string | null; jsonl_days: number; text_days: number };
  totals: { queries: number; system_queries: number; by_outcome: Record<string, number>; zero_sources: number; timed: number; slow: number };
  rates: { no_relevant: number | null; general_knowledge: number | null; error: number | null; zero_sources: number | null; slow: number | null };
  latency_s: QStats; tok_per_s: number | null; by_caller: Record<string, number>; by_day: QDay[];
  top_queries: { query: string; count: number; last_seen: string; no_relevant: number; errors: number }[];
  top_terms: { term: string; queries: number }[];
}
export interface QueryRow { ts: string; query: string; outcome: string; caller: string | null; total_s: number | null; n_sources: number; sources: string[]; error: string | null }
export interface QueryList { kind: string; days: number; slow_seconds: number; total: number; masked: boolean; items: QueryRow[] }

export interface GoldItem { id: string; question: string; expect: string; verdict: string; passed: boolean; problems: string[]; hits: number;
  nearest_distance: number | null; first_expected_rank: number | null; within: number; sources_any: string[]; top_sources: string[] }
export interface GoldReport {
  available: boolean; detail?: string; masked?: boolean; saved_at?: string; overrides?: string[];
  settings?: { distance_threshold: number; min_hits: number; top_k_fused: number; rrf_k: number };
  total?: number; passed?: number; failed?: number; compared_with?: { regressions: string[]; fixed: string[]; new: string[] } | null; items?: GoldItem[];
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
  toolcalls: (days: number) => get<ToolCalls>("/toolcalls/summary", { days }),
  queryStats: (days: number) => get<QueryStats>("/queries/stats", { days }),
  queryList: (kind: string, days: number) => get<QueryList>("/queries/slow", { kind, days, limit: 15 }),
  gold: () => get<GoldReport>("/gold"),
  runs: (limit = 10) => get<{ total: number; items: Run[] }>("/maintenance/runs", { limit }),
};
