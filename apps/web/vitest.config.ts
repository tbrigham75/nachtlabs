import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
export default defineConfig({
  // The application uses the "@/" alias, so tests must resolve it too.
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: { environment: "jsdom", setupFiles: ["./tests/setup.ts"] },
});
