import { defineConfig, devices } from "@playwright/test";
import type { LaunchOptions } from "./launch/launch.spec.ts";

const HUB = process.env.PRINTGUARD_URL;
const CAMERA_PORT = 8090;
const DEV_PORT = Number(process.env.PW_PORT ?? 4180);
const launch = {
  testDir: "launch",
  timeout: 240_000,
  use: {
    cameraUrl: `http://${process.env.PRINTGUARD_CAMERA_HOST || "127.0.0.1"}:${CAMERA_PORT}`,
    screenshot: "only-on-failure",
  },
} as const;

export default defineConfig<LaunchOptions>({
  workers: 1,
  forbidOnly: !!process.env.CI,
  reporter: "list",
  projects: [
    { name: "screenshots", testDir: "screenshots" },
    { name: "sandbox", testDir: "tests", use: { ...devices["Desktop Chrome"] } },
    { name: "sandbox-webkit", testDir: "tests", use: { ...devices["Desktop Safari"] } },
    { name: "launch", ...launch, use: { ...devices["Desktop Chrome"], channel: "chrome", ...launch.use } },
    { name: "launch-webkit", ...launch, use: { ...devices["Desktop Safari"], ...launch.use } },
  ],
  webServer: HUB
    ? { command: `node launch/camera.ts ${CAMERA_PORT}`, url: `http://127.0.0.1:${CAMERA_PORT}` }
    : {
        command: `npm run dev -- --port ${DEV_PORT} --strictPort`,
        url: `http://localhost:${DEV_PORT}`,
        reuseExistingServer: true,
        timeout: 120_000,
      },
  use: { baseURL: HUB ?? `http://localhost:${DEV_PORT}` },
});
