import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  workers: 1,
  reporter: "list",
  projects: [
    { name: "screenshots", testDir: "screenshots" },
    { name: "sandbox", testDir: "tests", use: { ...devices["Desktop Chrome"] } },
    { name: "sandbox-webkit", testDir: "tests", use: { ...devices["Desktop Safari"] } },
  ],
  webServer: {
    command: "npm run dev -- --port 4180 --strictPort",
    url: "http://localhost:4180",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  use: { baseURL: "http://localhost:4180" },
});
