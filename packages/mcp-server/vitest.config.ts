import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    // live.test.ts needs a deployed server and a real key, so it is a separate
    // run rather than something `make test` can satisfy. It skips itself when the
    // environment is absent, but keeping it out of the default pattern means an
    // ordinary run does not even collect it.
    include: ["tests/**/*.test.ts"],
    exclude: ["tests/live.test.ts", "node_modules/**"],
  },
});
