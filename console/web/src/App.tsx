import { useEffect, useState } from "react";
import { api } from "./api";
import { useLoad } from "./hooks";
import { StatusHeader } from "./components/StatusHeader";
import { IndexHealth } from "./pages/IndexHealth";
import { Planned } from "./pages/Planned";

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
        {page === "explorer" && <Planned title="Query explorer" milestone="M3" text="Type a question and see the dense and keyword hits side by side, the fused ranking, and which relevance gate passed or failed." />}
        {page === "tools" && <Planned title="Tool-call monitor" milestone="M4" text="How often the agent model makes a real structured tool call, time to tool, and sessions that started while the MCP server was down." />}
        {page === "analytics" && <Planned title="Query analytics" milestone="M5" text="Latency over time, no-result and error rates, slow queries and recurring questions." />}
      </main>
      <footer>Read-only view. {health.data?.demo ? "Showing synthetic demo data." : "Shows personal data: keep this page on this machine."}</footer>
    </div>
  );
}
