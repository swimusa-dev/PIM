import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI app serves backend/pim/static/index.html for any non-API route (ARC-01).
export default defineConfig({
  base: "/",
  plugins: [react()],
  build: {
    outDir: "../backend/pim/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
