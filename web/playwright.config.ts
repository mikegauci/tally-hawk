import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: "http://localhost:3109",
    channel: process.env.PLAYWRIGHT_CHANNEL || "chrome",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node tests/mock-api.mjs",
      url: "http://127.0.0.1:8109/reset",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 3109",
      url: "http://localhost:3109/login",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        TALLYHAWK_API_URL: "http://127.0.0.1:8109",
        TALLYHAWK_API_KEY: "test-api-key",
        WEB_PASSWORD: "test-password",
        SESSION_SECRET: "test-only-secret-do-not-deploy",
        WEB_REVIEWER_NAME: "Test reviewer",
      },
    },
  ],
});
