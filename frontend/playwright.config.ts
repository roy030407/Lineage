import { defineConfig, devices } from "@playwright/test";

// This is the merge gate for feat/ui-overhaul (see NOTES-OVERNIGHT.md) --
// assertions here must check real, observable behavior (a tick was
// received, a mesh exists at a real position), never just "the page
// returned 200". Assumes the backend is already running on :8000 with the
// default run available (globalSetup loads and plays it); this config only
// starts the frontend.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false, // tests share one backend-loaded run; racing them isn't safe
  workers: 1,
  reporter: "list",
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
    timeout: 30_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
