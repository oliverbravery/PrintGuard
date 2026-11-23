import { readFileSync } from "node:fs";
import { chromium, expect, test as base, type Page } from "@playwright/test";

export type LaunchOptions = { cameraUrl: string };

const VERSION = readFileSync(new URL("../../pyproject.toml", import.meta.url), "utf8").match(/^version = "(.+)"$/m)![1];
const APP_WINDOW = process.env.PRINTGUARD_CDP;
const APP_LOG = process.env.PRINTGUARD_LOG;
const HEALTHY_WATCH_MS = 5_000;
const FEEDS = [
  { camera: "Healthy feed", monitor: "Healthy print", path: "healthy.mjpg" },
  { camera: "Failing feed", monitor: "Failing print", path: "defect.mjpg" },
];

const launch = base.extend<LaunchOptions>({ cameraUrl: ["", { option: true }] });
const test = APP_WINDOW
  ? launch.extend({
      page: async ({}, use) => {
        const browser = await chromium.connectOverCDP(APP_WINDOW);
        await use(browser.contexts()[0].pages()[0]);
        await browser.close();
      },
    })
  : launch;

function row(page: Page, monitor: string) {
  return page.locator("main li").filter({ has: page.getByRole("link", { name: monitor, exact: true }) });
}

async function risk(page: Page, monitor: string) {
  const text = await row(page, monitor).textContent();
  return Number(text!.match(/risk\s*(\d+)%/)![1]);
}

test.describe.configure({ mode: "serial" });

test("the hub starts and reports this version", async ({ request }) => {
  await expect(async () => {
    const health = await request.get("/api/health");
    expect(await health.json()).toEqual({ ok: true, version: VERSION });
  }).toPass({ timeout: 120_000 });
});

test("the app window loads the dashboard", async () => {
  test.skip(!APP_LOG, "the container has no window of its own");
  await expect.poll(() => readFileSync(APP_LOG!, "utf8"), { timeout: 60_000 }).toContain("UI connected");
});

test("a failing print is caught end to end", async ({ page, baseURL, cameraUrl }) => {
  const crashes: Error[] = [];
  page.on("pageerror", (error) => crashes.push(error));
  await page.goto(baseURL!);
  await page.getByRole("dialog", { name: "How PrintGuard works" }).getByRole("button", { name: "Skip" }).click();

  await page.getByRole("link", { name: "Cameras", exact: true }).click();
  for (const feed of FEEDS) {
    await page.getByRole("button", { name: "Add camera" }).click();
    const form = page.getByRole("dialog", { name: "Register a camera" });
    await form.getByPlaceholder("Name").fill(feed.camera);
    await form.getByPlaceholder(/stream URL/).fill(`${cameraUrl}/${feed.path}`);
    await form.getByRole("button", { name: "Register stream" }).click();
    await expect(page.getByRole("heading", { name: feed.camera, exact: true })).toBeVisible({ timeout: 60_000 });
  }

  await page.getByRole("link", { name: "Monitors", exact: true }).click();
  for (const [index, feed] of FEEDS.entries()) {
    await page.getByRole("button", { name: index === 0 ? "Open Add a monitor" : "Add monitor" }).click();
    const form = page.getByRole("dialog", { name: "Add monitor" });
    await form.getByPlaceholder("Monitor name").fill(feed.monitor);
    const camera = await form.locator("option", { hasText: feed.camera }).getAttribute("value");
    await form.getByRole("combobox").first().selectOption(camera!);
    await form.getByRole("button", { name: "Add monitor" }).click();
    await expect(form).toBeHidden();
  }

  await page.getByRole("link", { name: "Failing print", exact: true }).click();
  await page.getByRole("tab", { name: "Tune" }).click();
  await page.getByRole("slider", { name: /Alert threshold/ }).press("Home");

  for (const feed of FEEDS) {
    await page.getByRole("link", { name: feed.monitor, exact: true }).click();
    const selected = page.getByRole("region", { name: `${feed.monitor}, selected monitor` });
    await expect(selected.getByText(/(?<![\d.])(?!0\.0\/)\d+\.\d\/\d+\.\d fps/)).toBeVisible({ timeout: 90_000 });
  }
  await expect(row(page, "Failing print").getByText("defect", { exact: true })).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("DEFECT DETECTED")).toBeVisible();
  await expect.poll(async () => (await risk(page, "Failing print")) - (await risk(page, "Healthy print"))).toBeGreaterThan(0);
  await page.waitForTimeout(HEALTHY_WATCH_MS);
  await expect(row(page, "Healthy print").getByText("defect", { exact: true })).toBeHidden();
  await page.screenshot({ path: test.info().outputPath("dashboard.png") });
  expect(crashes).toEqual([]);
});
