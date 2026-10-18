import { useEffect, useState } from "react";
import { AlertPushStatus } from "./components/AlertPushStatus";
import { MoonIcon, SunIcon } from "./components/Icons";
import { ControlBar } from "./components/ControlBar";
import { LiveProvider, useLive } from "./live";
import { Alerts } from "./pages/Alerts";
import { Complaints } from "./pages/Complaints";
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
      return localStorage.getItem("kami-theme") ?? "light"; // daytime control room and classroom projector (Round 9)
    } catch {
      return "light";
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
  const page = nodeMatch ? "node" : hash.startsWith("#/alerts") ? "alerts" : hash.startsWith("#/complaints") ? "complaints" : hash.startsWith("#/method") ? "method" : "overview";
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <div className="brand">
          <span className="wordmark">KAMI</span>
          <span className="chip" title="All data are replayed public datasets with injected scenarios">Demo network · fictional layout</span>
          <AlertPushStatus chip />
        </div>
        <nav aria-label="Main">
          <a href="#/" aria-current={page === "overview" ? "page" : undefined}>Overview</a>
          <a href="#/alerts" aria-current={page === "alerts" ? "page" : undefined}>Alerts</a>
          <a href="#/complaints" aria-current={page === "complaints" ? "page" : undefined}>Complaints</a>
          <a href="#/method" aria-current={page === "method" ? "page" : undefined}>Method</a>
        </nav>
        <div className="top-right">
          <span className={`conn conn-${conn}`} role="status" aria-label={`Connection: ${CONN_TEXT[conn]}`}>
            <i aria-hidden="true" />
            {CONN_TEXT[conn]}
          </span>
          {status && <span className="chip" title="Backend mode">{status.mode === "docker" ? "MQTT + TimescaleDB" : "Fallback: in-process bus + SQLite"}</span>}
          <button type="button" className="btn" onClick={toggle} aria-pressed={theme === "light"}>
            {theme === "dark" ? <><SunIcon /> Light</> : <><MoonIcon /> Dark</>}
          </button>
        </div>
      </header>
      {page === "overview" && <ControlBar />}
      {page === "node" && nodeMatch && <ControlBar key={nodeMatch[1]} defaultNode={decodeURIComponent(nodeMatch[1])} />}
      <main id="main" tabIndex={-1}>
        {page === "overview" && <Overview />}
        {page === "node" && nodeMatch && <NodeDetail id={decodeURIComponent(nodeMatch[1])} />}
        {page === "alerts" && <Alerts />}
        {page === "complaints" && <Complaints />}
        {page === "method" && <Method />}
      </main>
      <footer className="footer">
        <AlertPushStatus />
        <span>Simulated data · demo network</span>
      </footer>
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
