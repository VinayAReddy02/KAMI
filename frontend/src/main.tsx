import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "@fontsource/hind/400";
import "@fontsource/hind/500";
import "@fontsource/hind/600";
import "@fontsource/hind/700";
import "@fontsource/big-shoulders-stencil-display/800";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
