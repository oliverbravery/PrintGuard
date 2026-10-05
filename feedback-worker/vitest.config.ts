import { cloudflareTest } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: { TOKEN_SECRET: "test-secret", REMINDER_TO: "to@example.com", REMINDER_FROM: "from@example.com" },
      },
    }),
  ],
});
