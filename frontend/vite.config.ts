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
});
