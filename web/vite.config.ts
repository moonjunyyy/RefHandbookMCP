import { defineConfig } from 'vite';

// Published at /apps/site/ (deploy/install.sh --app site web/dist) and served for every page path
// (/, /account/…, /agents/…): its assets are named from the site's root, not from the page. The frame
// (/auth/static/site.js) is imported at run time from the sign-in, never bundled (docs/frame.md §1).
export default defineConfig({
  base: '/apps/site/',
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false, rollupOptions: { external: ['/auth/static/site.js'] } },
});
