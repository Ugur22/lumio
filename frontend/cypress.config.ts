import { defineConfig } from "cypress";

// Targets the built app served by `make e2e-server` (stub upstream, throwaway data), not the Vite dev server.
export default defineConfig({
  e2e: {
    baseUrl: "http://127.0.0.1:18766",
    specPattern: "cypress/e2e/**/*.cy.ts",
    supportFile: false,
    video: false,
  },
});
