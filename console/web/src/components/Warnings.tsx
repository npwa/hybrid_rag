import type { Warn } from "../api";

/** Warnings from the API, each with the runbook that explains it (FR-X.2). */
export function Warnings({ items }: { items: Warn[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="banner bad" role="alert">
      <ul className="warnlist">
        {items.map((w) => (
          <li key={w.id}>{w.text}{w.runbook && <> Runbook: <code>{w.runbook}</code></>}</li>
        ))}
      </ul>
    </div>
  );
}
