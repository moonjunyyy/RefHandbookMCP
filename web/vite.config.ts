import { defineConfig } from 'vite';

// Published at /apps/site/ (deploy/install.sh --app site web/dist) and served for every page path
// (/, /account/…, /agents/…): its assets are named from the site's root, not from the page.
export default defineConfig({
  base: '/apps/site/',
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
