import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "screenshots",
  workers: 1,
  reporter: "list",
  webServer: {
    command: "npm run dev -- --port 4180 --strictPort",
    url: "http://localhost:4180",
    reuseExistingServer: true,
    timeout: 120_000,
  },
  use: { baseURL: "http://localhost:4180" },
});
