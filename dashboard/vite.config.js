import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle is served from an S3 website endpoint at the bucket root, so the
// default absolute base path is correct. VITE_API_URL is baked in at build time
// by scripts/deploy_web.sh.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 700,
  },
  server: {
    port: 5173,
  },
});
