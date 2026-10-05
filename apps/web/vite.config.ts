import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
  test: { include: ["src/**/*.test.ts"], coverage: { include: ["src/api.ts"], thresholds: { lines: 80, functions: 80, statements: 80 } } },
});
