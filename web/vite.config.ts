import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  server: {
    fs: { allow: [".."] },
    proxy: {
      "/api": { target: "http://localhost:8000", ws: true },
      "/hls": "http://localhost:8000",
      "/models": "http://localhost:8000",
      "/pysrc.zip": "http://localhost:8000",
    },
  },
});
