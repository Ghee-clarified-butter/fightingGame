/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// ./script/server exports these when it runs the pair; the defaults are the ports
// specs/base.md §6 names, so a bare `npm run dev` behaves exactly as specified.
const frontendPort = Number(process.env.FRONTEND_PORT) || 5173;
const backendPort = Number(process.env.BACKEND_PORT) || 5000;

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: frontendPort,
    // The API runs on :5000, so every request from :5173 would be cross-origin and
    // blocked by the browser. Proxying keeps the client on relative /api paths
    // (specs/base.md §6) and removes any need for CORS headers on the backend.
    proxy: {
      "/api": {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/setupTests.ts",
    globals: true,
  },
});
