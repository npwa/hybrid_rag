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

export const api = {
  health: () => get<Health>("/health"),
  summary: () => get<Summary>("/index/summary"),
  failures: (p: Record<string, string | number | boolean | undefined>) => get<FailurePage>("/index/failures", p),
  runs: (limit = 10) => get<{ total: number; items: Run[] }>("/maintenance/runs", { limit }),
};
