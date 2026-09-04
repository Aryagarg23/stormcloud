import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/v1": {
        target: process.env.STORMCLOUD_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
