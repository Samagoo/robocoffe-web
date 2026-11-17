import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In Docker the backend is http://backend:8000; running natively it's localhost.
const target = process.env.VITE_PROXY_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // listen on 0.0.0.0 so the container port is reachable
    port: 5173,
    watch: { usePolling: true }, // hot reload with Windows bind mounts
    proxy: {
      // REST now, WebSocket (/api/ws/...) from Phase 3 — same origin, no CORS
      "/api": { target, changeOrigin: true, ws: true },
    },
  },
});
