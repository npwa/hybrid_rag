import { useState } from "react";
import { api, type CauseCount } from "../api";
import { useLoad } from "../hooks";
import { fmtBytes, fmtInt } from "../format";

const PAGE = 25;
const COLS: [string, string][] = [["path", "File"], ["extension", "Type"], ["cause", "Cause"], ["status", "Status"], ["ocr_confidence", "OCR conf."], ["size", "Size"]];

export interface Filters { cause: string; extension: string; status: string; q: string }

export function FailuresTable({ causes, filters, onFilters }: { causes: CauseCount[]; filters: Filters; onFilters: (f: Filters) => void }) {
  const [sort, setSort] = useState("path");
  const [desc, setDesc] = useState(false);
  const [offset, setOffset] = useState(0);
  const page = useLoad(() => api.failures({ ...filters, sort, desc, limit: PAGE, offset }), [filters, sort, desc, offset]);
  const set = (patch: Partial<Filters>) => { setOffset(0); onFilters({ ...filters, ...patch }); };
  const total = page.data?.total ?? 0;

  return (
    <div>
      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Filter problem files">
        <label>Cause
          <select value={filters.cause} onChange={(e) => set({ cause: e.target.value })}>
            <option value="">All causes</option>
            {causes.map((c) => <option key={c.cause} value={c.cause}>{c.label} ({fmtInt(c.count)})</option>)}
          </select>
        </label>
        <label>Type <input value={filters.extension} placeholder="pdf" size={6} onChange={(e) => set({ extension: e.target.value.trim().toLowerCase() })} /></label>
        <label>Path contains <input value={filters.q} placeholder="text" onChange={(e) => set({ q: e.target.value })} /></label>
        {(filters.cause || filters.extension || filters.q || filters.status) &&
          <button type="button" onClick={() => set({ cause: "", extension: "", q: "", status: "" })}>Clear filters</button>}
      </form>
      {page.error && <p className="error" role="alert">Could not load files: {page.error}</p>}
      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              {COLS.map(([k, label]) => (
                <th key={k} aria-sort={sort === k ? (desc ? "descending" : "ascending") : "none"}>
                  <button className="sort" onClick={() => { if (sort === k) setDesc(!desc); else { setSort(k); setDesc(false); } setOffset(0); }}>
                    {label}{sort === k ? (desc ? " ▼" : " ▲") : ""}
                  </button>
                </th>
              ))}
              <th>Ticket</th>
            </tr>
          </thead>
          <tbody>
            {page.data?.items.map((i) => (
              <tr key={i.file_id} title={i.error_message ?? undefined}>
                <td className="path">{i.rel_path}</td>
                <td>{i.extension || "–"}</td>
                <td>{i.label}</td>
                <td><code>{i.status}</code></td>
                <td className="num">{i.ocr_confidence == null ? "–" : i.ocr_confidence.toFixed(1)}</td>
                <td className="num">{fmtBytes(i.size_bytes)}</td>
                <td>{i.ticket ? <span title={i.ticket_path ?? ""}>{i.ticket}</span> : "–"}</td>
              </tr>
            ))}
            {page.data && page.data.items.length === 0 && <tr><td colSpan={7} className="muted">No files match.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
        <span>{total === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE, total)}`} of {fmtInt(total)}</span>
        <button disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
      </div>
    </div>
  );
}
