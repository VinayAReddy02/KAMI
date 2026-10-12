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
  await expect(controls.locator(".toast")).toHaveText("Injected Burst (sudden)");
  const item = page.locator(".overview-feed .alert-item", { hasText: NODE.name }).first();
  await expect(item).toBeVisible({ timeout: 90_000 });
  await expect(item).toContainText("Infrastructure");
  await expect(item.locator(".alert-text")).not.toBeEmpty();
});

test("Node detail shows the four charts and the explanation", async ({ page }) => {
  await open(page, `#/node/${NODE.id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(NODE.name);
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
  for (const cell of await rows.locator("td:nth-child(3)").allTextContents()) expect(cell).toBe(NODE.name);
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

test("the theme toggle switches between dark and light and is remembered", async ({ page }) => {
  await page.goto("/#/");
  const html = page.locator("html");
  await expect(html).toHaveAttribute("data-theme", "dark");
  const dark = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await page.getByRole("button", { name: /Light/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await expect(page.getByRole("button", { name: /Dark/ })).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).not.toBe(dark);
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: /Dark/ }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
});
