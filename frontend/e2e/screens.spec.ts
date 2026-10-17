import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { injectAndWait, NODE, open, PAGES, setPaused, THEMES } from "./helpers";

// Screenshots for the paper: 4 pages x 2 themes x 2 sizes = 16 files in results/screens/. Taken from the running
// demo (replayed semi-synthetic data, alerts in dry run) with one injected event on the node page; never edited by hand.
// Output folder: results/ only when scripts/screenshots.py asks for it (KAMI_E2E_WRITE_RESULTS=1). A plain
// `npx playwright test` and the check scripts write to a scratch folder, so the stored files are never rewritten by accident.
const BASE = process.env.KAMI_E2E_OUT ?? (process.env.KAMI_E2E_WRITE_RESULTS === "1" ? path.resolve(process.cwd(), "..", "results") : path.join(os.tmpdir(), "kami_e2e_out"));
const OUT = path.resolve(BASE, "screens");
const SIZES = [
  { key: "desktop_1440x900", width: 1440, height: 900 },
  { key: "phone_390x844", width: 390, height: 844 },
] as const;
const shots: Record<string, unknown>[] = [];

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ request }) => {
  fs.mkdirSync(OUT, { recursive: true });
  await injectAndWait(request); // sudden infrastructure event on the node shown on the node page
  await setPaused(request, true); // every screenshot shows the same moment of the replay
});

test.afterAll(async ({ request }) => {
  const status = await (await request.get("/demo/status")).json();
  await setPaused(request, false);
  const manifest = {
    created_utc: new Date().toISOString(),
    made_by: "frontend/e2e/screens.spec.ts (Playwright, Chromium); not edited by hand",
    data: "semi-synthetic replay; alert push in dry run",
    replay_time: status.ts,
    injected_event: { type: "infra_burst", node: NODE.id, node_name: NODE.label },
    method: status.method?.label,
    note: "full-page screenshots at the given viewport size; the map background needs internet access for the OpenStreetMap tiles",
    files: shots,
  };
  fs.writeFileSync(path.join(OUT, "manifest.json"), JSON.stringify(manifest, null, 1) + "\n");
});

for (const size of SIZES) {
  for (const theme of THEMES) {
    for (const pg of PAGES) {
      const file = `${pg.key}_${theme}_${size.key}.png`;
      test(`screenshot ${file}`, async ({ page }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        await open(page, pg.hash, theme);
        await pg.ready(page);
        await expect(page.locator("footer")).toContainText("Alerts: dry run");
        let tiles: boolean | null = null;
        if (pg.key === "overview") {
          tiles = await page.locator("img.leaflet-tile-loaded").first().waitFor({ timeout: 20_000 }).then(() => true, () => false);
          if (tiles) await page.waitForLoadState("networkidle", { timeout: 20_000 }).catch(() => undefined);
        }
        if (pg.key === "node_detail_injected_event") {
          await expect(page.locator(".detail-head")).toContainText("Infrastructure"); // the injected event is on screen
        }
        await page.waitForTimeout(400); // let fonts and transitions settle
        const target = path.join(OUT, file);
        await page.screenshot({ path: target, fullPage: true, animations: "disabled" });
        const bytes = fs.statSync(target).size;
        expect(bytes).toBeGreaterThan(5_000);
        shots.push({ file, page: pg.key, theme, viewport: `${size.width}x${size.height}`, bytes, ...(tiles === null ? {} : { map_tiles_loaded: tiles }) });
      });
    }
  }
}
