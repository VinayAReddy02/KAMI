import { expect, type APIRequestContext, type Page } from "@playwright/test";

// Round 7: every node is shown with its number and ward (frontend/src/labels.ts)
export const NODE = { id: "node-2", name: "Gandhi Nagar Tank", label: "Gandhi Nagar Tank (node-2 · Ward 2)", short: "2 · Gandhi Nagar" };
export const THEMES = ["dark", "light"] as const;
export type Theme = (typeof THEMES)[number];

/** Open the app with a fixed theme (the app reads it from localStorage). */
export async function open(page: Page, hash: string, theme: Theme = "dark") {
  await page.addInitScript((t) => window.localStorage.setItem("kami-theme", t), theme);
  await page.goto("/" + hash);
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

/** Inject a sudden infrastructure event through the API and wait until the node has an active alert. */
export async function injectAndWait(request: APIRequestContext, node = NODE.id) {
  const active = async () => (await (await request.get(`/alerts?node=${node}&status=active`)).json()) as unknown[];
  // Each injection draws a new event from the scenario generator; a mild one may not raise an alert. Try up to 4 events.
  for (let attempt = 0; attempt < 4 && (await active()).length === 0; attempt++) {
    const r = await request.post("/demo/inject", { data: { type: "infra_burst", node } });
    expect(r.ok()).toBeTruthy();
    for (let i = 0; i < 80 && (await active()).length === 0; i++) await new Promise((res) => setTimeout(res, 500));
  }
  expect((await active()).length).toBeGreaterThan(0);
}

export async function setPaused(request: APIRequestContext, paused: boolean) {
  expect((await request.post("/demo/control", { data: { paused } })).ok()).toBeTruthy();
}

/** The pages of the app and what shows that each has finished loading. */
export const PAGES = [
  { key: "overview", hash: "#/", ready: async (p: Page) => expect(p.locator(".node-marker")).toHaveCount(8) },
  { key: "node_detail_injected_event", hash: `#/node/${NODE.id}`, ready: async (p: Page) => expect(p.locator("figure.chart svg")).toHaveCount(4) },
  { key: "alerts", hash: "#/alerts", ready: async (p: Page) => expect(p.locator("table tbody tr").first()).toBeVisible() },
  { key: "method", hash: "#/method", ready: async (p: Page) => expect(p.locator(".method-version")).toContainText("frozen Round 2") },
] as const;
