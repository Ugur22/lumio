/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // The Python runner's loader chunk (~1.4 MB) is only fetched on Run, and the app chunk is ~370 kB gzipped; 500 kB would just be noise.
  build: { chunkSizeWarningLimit: 1500 },
  server: { proxy: { "/api": "http://localhost:8000" } },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
