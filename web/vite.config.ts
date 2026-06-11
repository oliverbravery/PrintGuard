import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": { target: "http://localhost:8000", ws: true },
      "/models": "http://localhost:8000",
      "/pysrc.zip": "http://localhost:8000",
    },
  },
});
