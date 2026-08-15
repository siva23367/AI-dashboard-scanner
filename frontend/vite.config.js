import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Two ways to host this frontend:
//  1. Standalone on Vercel (or similar) at its own domain root -- default,
//     base "/". The backend lives elsewhere (Render etc), reached via
//     VITE_API_BASE_URL (see src/api.js).
//  2. Embedded in the Flask backend itself at /app (webapp.py's `spa` route)
//     -- same origin as the API, no VITE_API_BASE_URL needed. Build with:
//       VITE_BASE_PATH=/app/ npm run build
const BASE_PATH = process.env.VITE_BASE_PATH || "/";
const FLASK_DEV_TARGET = process.env.FLASK_DEV_TARGET || "http://127.0.0.1:8005";

export default defineConfig({
  plugins: [react()],
  base: BASE_PATH,
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
