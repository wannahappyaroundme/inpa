import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    include: ["components/__tests__/**/*.test.tsx"],
    setupFiles: ["./vitest.setup.ts"],
    restoreMocks: true,
  },
});
