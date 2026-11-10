import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * Adds a <link rel="preload"> for the Latin subset of the UI font to the built index.html, so
 * that the font is already on its way when the first text is laid out. The file name is hashed
 * at build time, which is why this cannot be written into index.html by hand.
 */
function preloadFont(pattern: RegExp): Plugin {
  return {
    name: "sourcewise:preload-font",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(_html, context) {
        const file = Object.keys(context.bundle ?? {}).find((name) => pattern.test(name));
        if (!file) return [];
        return [
          {
            tag: "link",
            attrs: { rel: "preload", as: "font", type: "font/woff2", href: `/${file}`, crossorigin: true },
            injectTo: "head",
          },
        ];
      },
    },
  };
}

// In development the Vite server proxies /api to the FastAPI app on port 8102.
// In production FastAPI serves the files built into ./dist, so there is only one port.
export default defineConfig({
  plugins: [react(), tailwindcss(), preloadFont(/inter-latin-opsz-normal.*\.woff2$/)],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8102", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
