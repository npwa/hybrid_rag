export const fmtInt = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString("en-US"));
export const fmtPct = (n: number | null | undefined) => (n == null ? "–" : `${n.toFixed(1)}%`);
export const fmtBytes = (n: number | null | undefined) => {
  if (n == null) return "–";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
};
export const fmtTime = (s: string | null | undefined) => (s ? s.replace("T", " ") : "–");
export const fmtAge = (h: number | null | undefined) => {
  if (h == null) return "unknown";
  if (h < 1) return `${Math.round(h * 60)} min ago`;
  if (h < 48) return `${h.toFixed(1)} h ago`;
  return `${(h / 24).toFixed(1)} days ago`;
};
