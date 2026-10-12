import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { open, THEMES } from "./helpers";

// Citizen pipe-damage tickets on the dashboard (Round 6, C5). The test server holds one ticket that it made from a
// generated picture (scripts/e2e_server.py): no citizen photo and no Telegram message is involved.

test("a citizen report has its own marker on the map, apart from the 8 sensor markers", async ({ page }) => {
  await open(page, "#/");
  await expect(page.locator(".node-marker")).toHaveCount(8);
  const ticket = page.locator(".ticket-marker");
  await expect(ticket).toHaveCount(1);
  await expect(ticket).toHaveText("Report #1"); // text and shape, not colour alone
  await expect(ticket.locator("svg")).toHaveCount(1);
  await expect(page.locator(".leaflet-marker-icon[title^='Citizen report 1, open']")).toHaveCount(1);
  await ticket.click();
  await expect(page).toHaveURL(/#\/complaints$/);
  await expect(page.getByRole("heading", { level: 1, name: "Complaints" })).toBeVisible();
});

test("the Complaints list shows the photo thumbnail, time, nearest sensor point and status", async ({ page }) => {
  await open(page, "#/");
  await page.getByRole("link", { name: "Complaints" }).click();
  await expect(page.getByRole("note")).toContainText("nothing analyses them automatically");
  const row = page.locator("table tbody tr");
  await expect(row).toHaveCount(1);
  await expect(page.locator(".complaints .count")).toHaveText("1 report");
  const img = row.locator("img.thumb");
  await expect(img).toHaveAttribute("alt", "Photo sent with report 1");
  await expect.poll(async () => img.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(50); // the picture really loaded
  await expect(row.locator("td").nth(1)).toContainText("#1");
  await expect(row.locator("td").nth(1)).toContainText("test data");
  await expect(row.locator("td").nth(2)).toHaveText(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC/);
  await expect(row.locator("td").nth(3)).toHaveText(/^Old Town Junction · \d\.\d+ km$/);
  await expect(row.locator("td").nth(4)).not.toBeEmpty(); // what the sensors showed at that point when the report came in
  await expect(row.locator("td").nth(5)).toHaveText("Open");
  await row.getByRole("link", { name: "Old Town Junction" }).click();
  await expect(page).toHaveURL(/#\/node\/node-5$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Old Town Junction");
});

for (const theme of THEMES) {
  test(`the Complaints page has no serious or critical accessibility finding (${theme} theme)`, async ({ page }) => {
    await open(page, "#/complaints", theme);
    await expect(page.locator("table tbody tr")).toHaveCount(1);
    const result = await new AxeBuilder({ page }).analyze();
    const blocking = result.violations.filter((v) => v.impact === "serious" || v.impact === "critical").map((v) => `${v.id} -> ${v.nodes[0]?.target.join(" ")}`);
    expect(blocking).toEqual([]);
  });
}
