import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { input: {
    app: fileURLToPath(new URL("./index.html", import.meta.url)),
    guide: fileURLToPath(new URL("./guide.html", import.meta.url)),
  } } },
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { include: ["src/**/*.test.ts"], coverage: { include: ["src/api.ts", "src/http.ts", "src/identity.ts"], thresholds: { lines: 80, functions: 80, statements: 80 } } },
});
