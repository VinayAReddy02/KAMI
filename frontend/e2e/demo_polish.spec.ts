import { expect, test, type Page } from "@playwright/test";
import { NODE, open, THEMES } from "./helpers";

// Round 8 (demo polish, WCAG 2.1 AA): one test per fixed finding of results/demo_polish/audit.md, plus projector sizes.

test.describe.configure({ mode: "serial" });

const ALL_PAGES = ["#/", "#/alerts", `#/node/${NODE.id}`, "#/complaints", "#/method"];

/** WCAG contrast ratio of two CSS colours, computed in the page. */
async function contrast(page: Page, a: string, b: string): Promise<number> {
  return page.evaluate(([x, y]) => {
    const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
    const lum = (c: string) => {
      const [r, g, b2] = rgb(c).map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
      return 0.2126 * r + 0.7152 * g + 0.0722 * b2;
    };
    const [hi, lo] = [lum(x), lum(y)].sort((m, n) => n - m);
    return (hi + 0.05) / (lo + 0.05);
  }, [a, b]);
}

test("F01: a focused map marker opens its node with Enter, the report marker opens Complaints with Space", async ({ page }) => {
  await open(page, "#/");
  await expect(page.locator(".node-marker")).toHaveCount(8);
  await page.locator(".leaflet-marker-icon[title^='Bagayam Booster (node-4 · Ward 4)']").focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#\/node\/node-4$/);
  await open(page, "#/");
  await page.locator(".leaflet-marker-icon[title^='Citizen report 1']").focus();
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/#\/complaints$/);
});

test("F02: no page scrolls sideways at 320 px (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  for (const hash of ALL_PAGES) {
    await open(page, hash);
    await expect(page.locator("footer")).toContainText(/Alerts: (dry run|Telegram on)/); // late content (header pill) included
    await page.waitForTimeout(600);
    const wide = await page.evaluate(() => [...document.querySelectorAll("body *")]
      .filter((e) => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1 && !e.closest(".leaflet-pane"))
      .slice(0, 4).map((e) => `${e.tagName}.${typeof e.className === "string" ? e.className.slice(0, 30) : "svg"}`).join(", "));
    expect(await page.evaluate(() => document.documentElement.scrollWidth), `${hash} ${wide}`).toBeLessThanOrEqual(320);
  }
  await expect(page.getByRole("link", { name: "Method" })).toBeInViewport();
});

test("F03, F04, F08: legend without a prohibited name, legible tabular chart ticks, steady confidence numbers", async ({ page }) => {
  await open(page, `#/node/${NODE.id}`);
  await expect(page.locator("figure.chart svg")).toHaveCount(4);
  await expect(page.locator(".legend")).not.toHaveAttribute("aria-label", /.*/);
  const tick = page.locator("text.tick").first();
  expect(Number.parseFloat(await tick.evaluate((e) => getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(13);
  expect(await tick.evaluate((e) => getComputedStyle(e).fontVariantNumeric)).toContain("tabular-nums");
  expect(await page.locator(".conf").evaluate((e) => getComputedStyle(e).fontVariantNumeric)).toContain("tabular-nums");
  await open(page, "#/alerts");
  await expect(page.locator("table tbody tr").first()).toBeVisible();
  expect(await page.locator("td.num").first().evaluate((e) => getComputedStyle(e).fontVariantNumeric)).toContain("tabular-nums");
});

for (const theme of THEMES) {
  test(`F05, F06, F07: control boundaries at least 3:1, critical colour from its token, no side tab on Method (${theme} theme)`, async ({ page }) => {
    await open(page, "#/", theme);
    const bar = page.getByRole("region", { name: "Replay controls" });
    const panel = await bar.evaluate((e) => getComputedStyle(e).backgroundColor);
    for (const control of [bar.getByLabel("Node"), bar.getByRole("button", { name: /Pause|Resume/ })]) {
      const border = await control.evaluate((e) => getComputedStyle(e).borderTopColor);
      expect(await contrast(page, border, panel)).toBeGreaterThanOrEqual(3);
    }
    const critical = await page.evaluate(() => {
      const probe = document.createElement("span");
      probe.className = "prio-critical";
      document.body.append(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return { c, token: getComputedStyle(document.documentElement).getPropertyValue("--c-critical").trim() };
    });
    expect(critical.token).not.toBe("");
    expect(await contrast(page, critical.c, await page.evaluate(() => getComputedStyle(document.body).backgroundColor))).toBeGreaterThanOrEqual(4.5);
    await open(page, "#/method", theme);
    expect(await page.locator(".method-version").evaluate((e) => Number.parseFloat(getComputedStyle(e).borderLeftWidth))).toBeLessThanOrEqual(1);
  });
}

for (const [w, h] of [[1920, 1080], [1280, 720]]) {
  test(`projector ${w}x${h}: map, markers, replay controls and alert feed fit without sideways scroll`, async ({ page }) => {
    await page.setViewportSize({ width: w, height: h });
    await open(page, "#/");
    await expect(page.locator(".node-marker")).toHaveCount(8);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(w);
    await expect(page.getByRole("region", { name: "Replay controls" }).getByRole("button", { name: "Inject event" })).toBeInViewport();
    await expect(page.locator(".map")).toBeInViewport();
  });
}
