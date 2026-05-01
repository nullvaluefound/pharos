import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const apiTarget = process.env.PHAROS_API_URL || "http://localhost:8000";
// PHAROS_BASE_URL: prefix the SPA is served under (e.g. "/pharos/" when
// nginx mounts it at https://omnoptikon.com/pharos/). Defaults to "/" for
// dev / standalone Docker.
const baseUrl = process.env.PHAROS_BASE_URL || "/";

export default defineConfig({
  base: baseUrl,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3000,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
