import { useEffect, useState } from "react";
import { ControlBar } from "./components/ControlBar";
import { LiveProvider, useLive } from "./live";
import { Alerts } from "./pages/Alerts";
import { Method } from "./pages/Method";
import { NodeDetail } from "./pages/NodeDetail";
import { Overview } from "./pages/Overview";

function useHash(): string {
  const [h, setH] = useState(window.location.hash || "#/");
  useEffect(() => {
    const f = () => setH(window.location.hash || "#/");
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);
  return h;
}

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("kami-theme") ?? "dark";
    } catch {
      return "dark";
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("kami-theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))];
}

const CONN_TEXT = { live: "Live", connecting: "Connecting…", reconnecting: "Reconnecting…" } as const;

function Shell() {
  const hash = useHash();
  const [theme, toggle] = useTheme();
  const { conn, status } = useLive();
  const nodeMatch = hash.match(/^#\/node\/(.+)$/);
  const page = nodeMatch ? "node" : hash.startsWith("#/alerts") ? "alerts" : hash.startsWith("#/method") ? "method" : "overview";
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="brand">
          <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true"><path d="M16 3c5 7 9 11.500 9 16a9 9 0 0 1-18 0c0-4.500 4-9 9-16z" fill="var(--c-quality)" /></svg>
          <span>KAMI</span>
          <span className="chip" title="All data are replayed public datasets with injected scenarios">Demo network · fictional layout</span>
        </div>
        <nav aria-label="Main">
          <a href="#/" aria-current={page === "overview" ? "page" : undefined}>Overview</a>
          <a href="#/alerts" aria-current={page === "alerts" ? "page" : undefined}>Alerts</a>
          <a href="#/method" aria-current={page === "method" ? "page" : undefined}>Method</a>
        </nav>
        <div className="top-right">
          <span className={`conn conn-${conn}`} role="status" aria-label={`Connection: ${CONN_TEXT[conn]}`}>
            <i aria-hidden="true" />
            {CONN_TEXT[conn]}
          </span>
          {status && <span className="chip" title="Backend mode">{status.mode === "docker" ? "MQTT + TimescaleDB" : "Fallback: in-process bus + SQLite"}</span>}
          <button type="button" className="btn" onClick={toggle} aria-pressed={theme === "light"}>
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </div>
      </header>
      {page === "overview" && <ControlBar />}
      <main id="main" tabIndex={-1}>
        {page === "overview" && <Overview />}
        {page === "node" && nodeMatch && <NodeDetail id={decodeURIComponent(nodeMatch[1])} />}
        {page === "alerts" && <Alerts />}
        {page === "method" && <Method />}
      </main>
    </>
  );
}

export default function App() {
  return (
    <LiveProvider>
      <Shell />
    </LiveProvider>
  );
}
