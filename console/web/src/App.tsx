import { useEffect, useState } from "react";
import { api } from "./api";
import { useLoad } from "./hooks";
import { StatusHeader } from "./components/StatusHeader";
import { IndexHealth } from "./pages/IndexHealth";
import { QueryAnalytics } from "./pages/QueryAnalytics";
import { ToolCalls } from "./pages/ToolCalls";
import { QueryExplorer } from "./pages/QueryExplorer";

const PAGES = [
  { id: "index", label: "Index health" },
  { id: "explorer", label: "Query explorer" },
  { id: "tools", label: "Tool-call monitor" },
  { id: "analytics", label: "Query analytics" },
] as const;
type PageId = (typeof PAGES)[number]["id"];

const fromHash = (): PageId => (PAGES.find((p) => `#/${p.id}` === window.location.hash)?.id ?? "index");

export function App() {
  const [page, setPage] = useState<PageId>(fromHash());
  useEffect(() => {
    const on = () => setPage(fromHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const health = useLoad(api.health, [], 30_000);

  return (
    <div className="app">
      <header className="top">
        <h1>Hybrid RAG console</h1>
        <nav aria-label="Pages">
          {PAGES.map((p) => (
            <a key={p.id} href={`#/${p.id}`} aria-current={p.id === page ? "page" : undefined} className={p.id === page ? "active" : ""}>
              {p.label}
            </a>
          ))}
        </nav>
      </header>
      <StatusHeader health={health.data} error={health.error} />
      <main>
        {page === "index" && <IndexHealth health={health.data} />}
        {page === "explorer" && <QueryExplorer health={health.data} />}
        {page === "tools" && <ToolCalls />}
        {page === "analytics" && <QueryAnalytics />}
      </main>
      <footer>Read-only view. {health.data?.demo ? "Showing synthetic demo data." : "Shows personal data: keep this page on this machine."}</footer>
    </div>
  );
}
