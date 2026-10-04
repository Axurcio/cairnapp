import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs separately (`make api`); proxying /v1 keeps the site and
// the API on one origin, so the session cookie works without CORS.
const apiUrl = process.env.CAIRN_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/v1": { target: apiUrl, changeOrigin: false },
      "/health": { target: apiUrl },
    },
  },
  test: {
    environment: "node",
  },
});
