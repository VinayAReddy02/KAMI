import { defineConfig } from "@playwright/test";

// The browser tests start their own demo server (scripts/e2e_server.py): fallback mode, temporary store, alert
// messages forced to dry run. That process cannot reach Telegram. Build the frontend first: npm run build.
const PORT = 8210; // 7981-8080 is a reserved range on the development machine

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, browserName: "chromium", viewport: { width: 1440, height: 900 } },
  webServer: {
    command: `..\\.venv\\Scripts\\python.exe ..\\scripts\\e2e_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/health`,
    reuseExistingServer: false,
    timeout: 180_000,
  },
});
