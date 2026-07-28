import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    environment: "jsdom",
    include: [
      "components/__tests__/**/*.test.tsx",
      "lib/baseline-editor.test.ts",
      "lib/guided-talk-playbooks.test.ts",
      "lib/talk-template-view-model.test.ts",
    ],
    setupFiles: ["./vitest.setup.ts"],
    restoreMocks: true,
  },
});
