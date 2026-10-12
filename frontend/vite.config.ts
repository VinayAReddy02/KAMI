/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/network": API,
      "/nodes": API,
      "/alerts": API,
      "/demo": API,
      "/notifications": API,
      "/complaints": API,
      "/citizen": API,
      "/health": API,
      "/readings": API,
      "/ws": { target: API, ws: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    exclude: ["e2e/**", "node_modules/**", "dist/**"], // e2e/ holds the Playwright browser tests
    css: false,
  },
});
