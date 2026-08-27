import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies /api and /ws to the backend (uvicorn on 8000) so the dev server
// avoids CORS entirely -- the frontend only ever talks to its own origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  test: {
    // e2e/ holds Playwright specs (a different test() API entirely, run via
    // `npx playwright test`) -- vitest's default glob would otherwise also
    // try to collect and run them as unit tests and fail to parse them.
    exclude: ["e2e/**", "node_modules/**"],
  },
});
