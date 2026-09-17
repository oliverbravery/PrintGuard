import { readFileSync } from "node:fs";
import { chromium, expect, test as base, type Page } from "@playwright/test";

export type LaunchOptions = { cameraUrl: string };

const VERSION = readFileSync(new URL("../../pyproject.toml", import.meta.url), "utf8").match(/^version = "(.+)"$/m)![1];
const APP_WINDOW = process.env.PRINTGUARD_CDP;
const APP_LOG = process.env.PRINTGUARD_LOG;
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

function tile(page: Page, monitor: string) {
  return page.locator("article").filter({ has: page.getByRole("heading", { name: monitor, exact: true }) });
}

async function risk(page: Page, monitor: string) {
  const label = await tile(page, monitor).getByRole("img", { name: /^risk / }).getAttribute("aria-label");
  return Number(label!.match(/\d+/)![0]);
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

  await page.getByRole("button", { name: "Cameras", exact: true }).click();
  const registry = page.getByRole("dialog", { name: "Camera registry" });
  for (const feed of FEEDS) {
    await registry.getByPlaceholder("Name").fill(feed.camera);
    await registry.getByPlaceholder(/stream URL/).fill(`${cameraUrl}/${feed.path}`);
    await registry.getByRole("button", { name: "Register stream" }).click();
    await expect(registry.getByText(feed.camera, { exact: true })).toBeVisible({ timeout: 60_000 });
  }
  await registry.getByRole("button", { name: "Close dialog" }).click();

  for (const feed of FEEDS) {
    await page.getByRole("button", { name: "+ Monitor" }).click();
    const form = page.getByRole("dialog", { name: "Add monitor" });
    await form.getByPlaceholder("Monitor name").fill(feed.monitor);
    const camera = await form.locator("option", { hasText: feed.camera }).getAttribute("value");
    await form.getByRole("combobox").first().selectOption(camera!);
    await form.getByRole("button", { name: "Add monitor" }).click();
    await expect(form).toBeHidden();
  }

  await page.getByRole("button", { name: "Open Failing print monitor details" }).click();
  await page.getByRole("slider", { name: /Alert threshold/ }).press("Home");
  await page.getByRole("button", { name: "Close monitor details" }).click();

  for (const feed of FEEDS) {
    await expect(tile(page, feed.monitor).getByText(/starting stream|no signal/)).toBeHidden({ timeout: 90_000 });
    await expect(tile(page, feed.monitor).getByText(/^(?!0\.0\/)\d+\.\d\/\d+\.\d$/)).toBeVisible({ timeout: 30_000 });
  }
  await expect(tile(page, "Failing print").getByText("DEFECT DETECTED")).toBeVisible({ timeout: 90_000 });
  await expect(tile(page, "Healthy print").getByText("DEFECT DETECTED")).toBeHidden();
  await expect.poll(async () => (await risk(page, "Failing print")) - (await risk(page, "Healthy print"))).toBeGreaterThan(0);
  await page.screenshot({ path: test.info().outputPath("dashboard.png") });
  expect(crashes).toEqual([]);
});
