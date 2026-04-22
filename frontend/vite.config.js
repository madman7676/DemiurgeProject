import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Minimal frontend tooling and API proxy for the React UI shell.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
