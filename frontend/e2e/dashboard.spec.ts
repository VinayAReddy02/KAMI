import { expect, test } from "@playwright/test";
import { NODE, open } from "./helpers";

test.describe.configure({ mode: "serial" });

test("Overview loads with 8 markers, the demo label and the dry-run alert line", async ({ page }) => {
  await open(page, "#/");
  await expect(page.locator(".node-marker")).toHaveCount(8);
  await expect(page.locator(".map-label")).toHaveText("Demo network, fictional layout");
  await expect(page.locator(".strip-total")).toHaveText("8 nodes");
  await expect(page.locator("footer")).toContainText("Alerts: dry run"); // the test server never sends
});

test("injecting an infrastructure event makes an alert appear in the feed", async ({ page }) => {
  await open(page, "#/");
  await expect(page.locator(".conn")).toContainText("Live");
  const controls = page.getByRole("region", { name: "Replay controls" });
  await controls.getByLabel("Event").selectOption("infra_burst");
  await controls.getByLabel("Node").selectOption(NODE.id);
  await controls.getByRole("button", { name: "Inject event" }).click();
  await expect(controls.locator(".toast")).toHaveText(`Injected Burst (sudden) at ${NODE.short}`);
  const item = page.locator(".overview-feed .alert-item", { hasText: NODE.label }).first();
  await expect(item).toBeVisible({ timeout: 90_000 });
  await expect(item).toContainText("Infrastructure");
  await expect(item.locator(".alert-text")).not.toBeEmpty();
});

test("Node detail shows the four charts and the explanation", async ({ page }) => {
  await open(page, `#/node/${NODE.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(NODE.label);
  await expect(page.locator("figure.chart svg[role=img]")).toHaveCount(4);
  for (const label of ["Flow", "Pressure", "Turbidity", "TDS"]) {
    await expect(page.locator("figure.chart", { hasText: label }).first()).toBeVisible();
  }
  const why = page.getByRole("region", { name: "Explanation" });
  await expect(why.getByRole("heading", { name: "Why" })).toBeVisible();
  await expect(why.locator("p").first()).toContainText(/evidence \d\.\d\d/);
  await expect(why.getByRole("meter")).toHaveCount(2);
  await expect(page.getByRole("region", { name: "Alerts for this node" }).locator(".alert-item").first()).toBeVisible();
});

test("the Alerts table filters by node and category", async ({ page }) => {
  await open(page, "#/alerts");
  const rows = page.locator("table tbody tr");
  await expect(rows.first()).toBeVisible();
  const filters = page.getByRole("form", { name: "Alert filters" });
  const count = filters.locator(".count");
  await filters.getByLabel("Node").selectOption(NODE.id);
  await expect(rows.first()).toBeVisible();
  const n = await rows.count();
  await expect(count).toHaveText(new RegExp(`^${n} of \\d+ alerts$`));
  for (const cell of await rows.locator("td:nth-child(3) a").allInnerTexts()) expect(cell).toBe(NODE.label); // the link text; the short form is hidden at this width (Round 9: a number plate precedes the link)
  await filters.getByLabel("Category").selectOption("Infrastructure");
  await expect(rows.first()).toBeVisible();
  for (const cell of await rows.locator("td:nth-child(2)").allTextContents()) expect(cell).toContain("Infrastructure");
  await filters.getByLabel("Category").selectOption("Quality");
  await filters.getByLabel("Status").selectOption("closed");
  await filters.getByLabel("Priority").selectOption("Low");
  const left = await rows.count();
  await expect(count).toHaveText(new RegExp(`^${left} of \\d+ alerts$`));
  if (left === 0) await expect(page.getByText("No alerts match these filters.")).toBeVisible();
});

test("every node is numbered: map markers, marker titles, both node dropdowns and the node title", async ({ page }) => {
  const shorts = ["1 · Katpadi", "2 · Gandhi Nagar", "3 · Sathuvachari", "4 · Bagayam", "5 · Old Town", "6 · Fort Road", "7 · Viruthampet", "8 · Thorapadi"];
  await open(page, "#/");
  await expect(page.locator(".node-marker .pin-label b")).toHaveText(shorts);
  await expect(page.locator(".leaflet-marker-icon[title^='Bagayam Booster (node-4 · Ward 4): ']")).toHaveCount(1);
  const controls = page.getByRole("region", { name: "Replay controls" });
  await expect(controls.getByLabel("Node").locator("option")).toHaveText(shorts);
  await controls.getByLabel("Node").selectOption({ label: "4 · Bagayam" });
  await expect(controls.getByLabel("Node")).toHaveValue("node-4");
  await open(page, "#/alerts");
  await expect(page.getByRole("form", { name: "Alert filters" }).getByLabel("Node").locator("option", { hasText: "4 · Bagayam" })).toHaveCount(1);
  await open(page, "#/node/node-4");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Bagayam Booster (node-4 · Ward 4)");
});

test("numbered marker labels fit their marker at phone width (390 px)", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await open(page, "#/");
  await expect(page.locator(".node-marker")).toHaveCount(8);
  const widths = await page.locator(".node-marker .pin-label b").evaluateAll((els) => els.map((e) => (e as HTMLElement).getBoundingClientRect().width));
  const box = await page.locator(".node-marker-wrap").first().evaluate((e) => (e as HTMLElement).getBoundingClientRect().width);
  for (const w of widths) expect(w).toBeLessThanOrEqual(box); // nothing runs past the 150 px marker box
  await expect(page.getByRole("region", { name: "Replay controls" }).getByLabel("Node")).toBeVisible();
  await open(page, "#/alerts"); // the table shows the short numbered form at this width, the full label stays for screen readers
  const cell = page.locator("table tbody tr td:nth-child(3)").first();
  await expect(cell).toBeVisible();
  await expect(cell.locator(".node-name-short")).toBeVisible();
  await expect(cell.locator(".node-name-short")).toHaveText(/^\d · [A-Za-z ]+$/);
  expect(await cell.locator(".node-name-full").evaluate((e) => e.getBoundingClientRect().width)).toBeLessThanOrEqual(1); // visually hidden, still read out
  await expect(cell.locator(".node-name-full")).toHaveText(/\(node-\d · Ward \d\)$/);
  for (const hash of ["#/", "#/alerts", `#/node/${NODE.id}`, "#/complaints", "#/method"]) { // no page is wider than the phone (Round 7 fix: chart grid)
    await open(page, hash);
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => document.documentElement.scrollWidth), hash).toBeLessThanOrEqual(390);
  }
});

test("the theme toggle switches between light and dark and is remembered", async ({ page }) => {
  await page.goto("/#/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "light"); // Round 9: the daytime control room and the projector open light
  const light = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await expect(page.getByRole("button", { name: /Dark/ })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: /Dark/ }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(light);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: /Light/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
});
