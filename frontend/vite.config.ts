import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxies /api and /ws to the backend (uvicorn on 8000) so the dev server
// avoids CORS entirely -- the frontend only ever talks to its own origin.
export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // The three.js stack dwarfs the app code (the 1.4MB single-chunk
        // warning) and changes far less often -- split it out so app edits
        // don't invalidate the whole cached bundle.
        manualChunks: {
          three: ["three", "@react-three/fiber", "@react-three/drei", "three-mesh-bvh"],
        },
      },
    },
    // The vendor chunk above is ~1.1MB of three.js itself -- irreducible
    // without dropping the 3D Mirror, and deliberately isolated so it
    // caches; don't warn about the thing the split already accounts for.
    chunkSizeWarningLimit: 1200,
  },
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
