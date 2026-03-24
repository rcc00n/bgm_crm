import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../../static/storefront"),
    emptyOutDir: true,
    sourcemap: true,
    manifest: "manifest.json",
    cssCodeSplit: false,
    rollupOptions: {
      input: resolve(__dirname, "src/main.jsx"),
      output: {
        format: "es",
        entryFileNames: "storefront-[hash].js",
        chunkFileNames: "chunks/[name]-[hash].js",
        assetFileNames: (assetInfo) => {
          if ((assetInfo.name || "").endsWith(".css")) {
            return "storefront-[hash][extname]";
          }
          return "assets/[name]-[hash][extname]";
        },
      },
    },
  },
});
