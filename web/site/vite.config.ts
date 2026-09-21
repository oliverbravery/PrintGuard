import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  publicDir: false,
  plugins: [react(), tailwindcss()],
  build: { outDir: "../dist-site", emptyOutDir: true },
  server: { fs: { allow: ["../.."] } },
});
