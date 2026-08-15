import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built app is served by Flask at /app/ (see the `spa` route in
// webapp.py), so every asset URL needs that prefix in production.
// In dev, Vite serves from / directly and proxies /api + /files calls
// to the Flask backend so there's no CORS to deal with.
const FLASK_DEV_TARGET = process.env.FLASK_DEV_TARGET || "http://127.0.0.1:8005";

export default defineConfig({
  plugins: [react()],
  base: "/app/",
  server: {
    port: 5173,
    proxy: {
      "/api": { target: FLASK_DEV_TARGET, changeOrigin: true },
      "/files": { target: FLASK_DEV_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
