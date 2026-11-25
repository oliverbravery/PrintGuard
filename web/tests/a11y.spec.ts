import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { camera, dashboard, emit, engine, monitor, printer, review } from "./fixtures";

const WCAG_22_AA = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

const base = engine();
const state = engine({
  settings: { ...base.settings, theme: "system" },
  cameras: [camera(), camera({ id: "c2", name: "Garage", online: false, reason: "no frames for 30s" })],
  printers: [printer(), printer({ id: "p2", name: "MK4", device_state: { status: "paused", progress: 62, job: "bracket.gcode", remaining_s: 900, nozzle: { actual: 215, target: 215 }, bed: { actual: 60, target: 60 } } })],
  monitors: [
    monitor({ printer_id: "p1" }),
    monitor({ id: "m2", name: "MK4", camera_id: "c2", printer_id: "p2", alert: { score: 0.86, action: "pause", ts: 1 } }),
  ],
  reviews: [review()],
  prints: [{ id: "f1", name: "benchy", filename: "benchy.gcode", ext: "gcode", size: 2_000_000, printer_ids: ["p1"], uploaded: 1, meta: {}, thumbnail: null }],
});

const ROUTES = [
  "/",
  "/monitors/m2",
  "/monitors/m1/history",
  "/monitors/m1/review/r1",
  "/prints",
  "/prints/f1",
  "/cameras",
  "/cameras/c1",
  "/printers",
  "/printers/p1",
  "/settings",
  "/settings/appearance",
  "/settings/alerts",
  "/settings/detection",
  "/settings/plugins",
  "/settings/home-assistant",
  "/settings/updates",
  "/settings/api",
  "/settings/storage",
];

const DIALOGS = ["monitor", "camera", "printer", "guide", "intro", "report", "update"];

const VIEWPORTS = [
  { name: "phone", width: 390, height: 844 },
  { name: "desktop", width: 1440, height: 900 },
];

for (const theme of ["dark", "light"] as const) {
  for (const viewport of VIEWPORTS) {
    test.describe(`${theme} on a ${viewport.name}`, () => {
      test.use({ viewport, colorScheme: theme, contextOptions: { reducedMotion: "reduce" } });

      for (const route of ROUTES) {
        test(`${route} meets WCAG 2.2 AA`, async ({ page }) => {
          await dashboard(page, { engine: state }, route);
          await expect(page.locator("main h1")).toBeAttached();
          const { violations } = await new AxeBuilder({ page }).withTags(WCAG_22_AA).exclude("video").analyze();
          expect(violations.map(({ id, nodes }) => `${id}: ${nodes.map((node) => node.target.join(" ")).join(", ")}`)).toEqual([]);
        });
      }

      for (const dialog of DIALOGS) {
        test(`the ${dialog} dialog meets WCAG 2.2 AA`, async ({ page }) => {
          await dashboard(page, { engine: state, dialog });
          await expect(page.getByRole("dialog")).toBeVisible();
          const { violations } = await new AxeBuilder({ page }).withTags(WCAG_22_AA).include("dialog").analyze();
          expect(violations.map(({ id, nodes }) => `${id}: ${nodes.map((node) => node.target.join(" ")).join(", ")}`)).toEqual([]);
          if (dialog === "intro") {
            const next = page.getByRole("button", { name: "Next", exact: true });
            while (await next.isVisible()) {
              await next.click();
              const step = await new AxeBuilder({ page }).withTags(WCAG_22_AA).include("dialog").analyze();
              expect(step.violations.map(({ id, nodes }) => `${id}: ${nodes.map((node) => node.target.join(" ")).join(", ")}`)).toEqual([]);
            }
          }
        });
      }
    });
  }
}

test.describe("glass", () => {
  test.use({ contextOptions: { reducedMotion: "reduce" } });

  for (const tone of [0, 1]) {
    test(`an armed confirm button on ${tone ? "light" : "dark"} glass meets WCAG 2.2 AA`, async ({ page }) => {
      await dashboard(page, { engine: state }, "/monitors/m1");
      await emit(page, { event: "state", ...state, settings: { ...state.settings, theme: "glass", glass: { opacity: 0, tone } } });
      await page.getByRole("button", { name: "Remove", exact: true }).click();
      await expect(page.getByRole("button", { name: "Confirm" })).toBeVisible();
      await expect
        .poll(async () => {
          const { violations, incomplete } = await new AxeBuilder({ page }).withRules(["color-contrast"]).include(".btn-armed").analyze();
          return [...violations, ...incomplete].map(({ id }) => id);
        })
        .toEqual([]);
    });
  }
});
