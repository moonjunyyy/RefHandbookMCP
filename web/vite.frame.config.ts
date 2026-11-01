import { defineConfig } from 'vite';

// The frame (frame/index.ts) as one ES module the sign-in serves to every page of the site at
// /auth/static/site.js (docs/frame.md §1). Not minified: it is read as it is served, and it is committed
// (src/portal/static/site.js) so a fresh install serves it without a build of the pages.
export default defineConfig({
  build: {
    lib: { entry: 'frame/index.ts', formats: ['es'], fileName: () => 'site.js' },
    outDir: '../src/portal/static', emptyOutDir: false, minify: false, sourcemap: false, target: 'es2022',
  },
});
