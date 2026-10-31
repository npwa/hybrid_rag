import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to the console process (./run_console.py --demo) on :8300.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8300" } },
  build: { outDir: "dist", sourcemap: false },
});
