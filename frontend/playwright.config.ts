import { defineConfig } from "@playwright/test";

// These are HTTP integration tests of the real Next.js proxy + FastAPI, not mocks.
// Use only the isolated local test servers described in docs/browser-scenario.md.
export default defineConfig({
  testDir: "./tests",
  testMatch: "proxy.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  timeout: 30000,
  use: {
    baseURL: "http://localhost:3100",
    extraHTTPHeaders: { "X-Requested-With": "Tempo", Origin: "http://localhost:3100" },
  },
});
