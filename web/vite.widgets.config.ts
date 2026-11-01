import { defineConfig } from 'vite';

// The widgets the pages app contributes to the main page (docs/apps-vault-calendar.md §2): one ES module
// per app, built from widgets/<app>.ts into dist/widgets/<app>.js after the pages (emptyOutDir: false),
// served at /apps/site/widgets/<app>.js and declared in the site file as that absolute path. The frame
// (/auth/static/site.js) is imported at run time, never bundled.
export default defineConfig({
  base: '/apps/site/',
  build: {
    lib: { entry: { calendar: 'widgets/calendar.ts', vault: 'widgets/vault.ts', projects: 'widgets/projects.ts' },
           formats: ['es'], fileName: (_format, name) => `widgets/${name}.js` },
    outDir: 'dist', emptyOutDir: false, sourcemap: false, target: 'es2022', cssCodeSplit: false,
    rollupOptions: { external: ['/auth/static/site.js'], output: { chunkFileNames: 'widgets/[name]-[hash].js' } },
  },
});
