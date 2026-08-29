import { defineConfig, devices } from "@playwright/test";

// A deliberately unprimed sibling of playwright.config.ts.
//
// That config's globalSetup issues load / set_speed 60 / play before every
// run, which is correct for the smoke suite but makes the cold-start state
// unobservable. That is not a hypothetical gap: it is why a four-link
// failure chain (backend never autoloaded, the WebSocket replayed an empty
// history, Line3D gated station meshes on tick state, and TopBar disabled
// Play whenever lineState was null) sat in a green suite while the app
// opened on a dead end.
//
// globalSetup is config-level in Playwright and cannot be disabled per
// project, so a second config with none at all is the only way to see a
// genuinely cold backend.
//
// PRECONDITION: the backend must have been restarted since any other suite
// ran, because those leave the replay advanced and the run partly consumed.
// This config cannot enforce that, exactly as the sibling config cannot
// enforce that a backend is running at all. Run it deliberately.
export default defineConfig({
  testDir: "./e2e",
  testMatch: /cold-start\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
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
