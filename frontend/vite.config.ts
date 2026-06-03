import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev: Vite serves the SPA on :5173 and proxies API + webhook calls to the
// FastAPI server on :8000 (single-origin behaviour without CORS).
// Prod: `npm run build` emits to ../web/dist, which FastAPI serves directly —
// matching a real deployment where the built SPA sits behind the API/CDN.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/vapi": "http://localhost:8000",
      "/sample_claims.json": "http://localhost:8000",
    },
  },
  build: {
    outDir: "../web/dist",
    emptyOutDir: true,
  },
});
